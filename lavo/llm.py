"""Base (peça 0) — INTEGRAÇÃO COM A API DA LLM
   Peça 8 — STREAMING
   Peça 10 — PROMPT CACHING
   Peça 11 — FALLBACK

Tudo que fala com o modelo passa por aqui:

* Streaming: o texto é entregue pedaço por pedaço (``ao_receber_texto``), para o
  usuário não achar que travou durante uma resposta de 20 segundos.
* Prompt caching: o começo do prompt que nunca muda (ferramentas + system) leva
  ``cache_control``; a conversa usa cache automático. Você não paga de novo pelo
  prompt gigante a cada chamada — confira ``cache_read_input_tokens`` nos traces.
* Fallback: se o provedor cair (429, 5xx, 529 sobrecarregado, timeout, rede),
  tenta de novo com backoff exponencial; se continuar falhando, troca de modelo
  (``LAVO_MODELOS=claude-opus-5-5,claude-sonnet-5-5``). Além disso, recusas de
  segurança do modelo principal são reprocessadas no servidor (``fallbacks``).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import anthropic
from pydantic import BaseModel

from .config import config
from .observabilidade import custo_usd, span, uso_para_dict

T = TypeVar("T", bound=BaseModel)

# Fallback de recusa no servidor (opt-in): a API reprocessa no modelo indicado
# quando o principal recusa por política. "default" escolhe o modelo pela categoria.
BETA_FALLBACK_RECUSA = "server-side-fallback-2026-07-01"
MODELOS_COM_FALLBACK_RECUSA = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-opus-5"}


class TodosOsModelosFalharam(RuntimeError):
    """Nenhum modelo da cadeia de fallback conseguiu responder."""


@dataclass
class Resposta:
    conteudo: list[dict[str, Any]]  # blocos do assistente, prontos para voltar ao histórico
    stop_reason: str | None
    modelo: str
    uso: dict[str, int]
    custo_usd: float

    @property
    def texto(self) -> str:
        return "".join(b.get("text", "") for b in self.conteudo if b.get("type") == "text")

    @property
    def chamadas_de_ferramenta(self) -> list[dict[str, Any]]:
        return [b for b in self.conteudo if b.get("type") == "tool_use"]


def _erro_temporario(e: Exception) -> bool:
    """Erros em que vale tentar de novo / trocar de modelo."""
    if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError)):
        return True
    if isinstance(e, anthropic.APIStatusError):
        return e.status_code in (408, 409, 429) or e.status_code >= 500
    return False


def _bloco_para_dict(bloco: Any) -> dict[str, Any]:
    if isinstance(bloco, dict):
        return bloco
    return bloco.model_dump(by_alias=True, exclude_none=True, mode="json")


def system_com_cache(texto_fixo: str) -> list[dict[str, Any]]:
    """System prompt estável, marcado para cache. Nada variável (datas, ids) aqui!"""
    return [{"type": "text", "text": texto_fixo, "cache_control": {"type": "ephemeral"}}]


def ferramentas_com_cache(ferramentas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Marca a última ferramenta: tudo até ela (lista de tools) entra no cache."""
    if not ferramentas:
        return []
    *resto, ultima = ferramentas
    return [*resto, {**ultima, "cache_control": {"type": "ephemeral"}}]


class LLM:
    def __init__(
        self,
        cliente: anthropic.Anthropic | None = None,
        modelos: list[str] | None = None,
        tentativas_por_modelo: int | None = None,
        espera_base: float = 1.0,
    ) -> None:
        # max_retries=0: as novas tentativas são feitas aqui, para aparecerem nos traces
        self.cliente = cliente or anthropic.Anthropic(max_retries=0)
        self.modelos = modelos or config.modelos
        self.tentativas = tentativas_por_modelo or config.tentativas_por_modelo
        self.espera_base = espera_base

    # ------------------------------------------------------------------ fallback
    def _com_fallback(self, nome: str, chamada: Callable[[str], Any], modelos: list[str] | None = None) -> Any:
        ultimo_erro: Exception | None = None
        for i, modelo in enumerate(modelos or self.modelos):
            if i > 0:
                with span("fallback", "fallback", de=(modelos or self.modelos)[i - 1], para=modelo,
                          motivo=str(ultimo_erro)):
                    pass
            for tentativa in range(1, self.tentativas + 1):
                try:
                    return chamada(modelo)
                except Exception as e:  # noqa: BLE001 - classificamos abaixo
                    if not _erro_temporario(e):
                        raise
                    ultimo_erro = e
                    if tentativa < self.tentativas:
                        espera = min(self.espera_base * 2 ** (tentativa - 1) + random.uniform(0, 0.5), 30)
                        with span("nova_tentativa", "retry", chamada=nome, modelo=modelo,
                                  tentativa=tentativa, erro=str(e), espera_s=round(espera, 2)):
                            time.sleep(espera)
        raise TodosOsModelosFalharam(f"{nome}: todos os modelos falharam. Último erro: {ultimo_erro}")

    # ------------------------------------------------------------------ streaming
    def conversar(
        self,
        *,
        system: str,
        mensagens: list[dict[str, Any]],
        ferramentas: list[dict[str, Any]] | None = None,
        ao_receber_texto: Callable[[str], None] | None = None,
        ao_reiniciar: Callable[[str], None] | None = None,
    ) -> Resposta:
        """Uma volta do modelo, com streaming, cache e fallback."""
        ferramentas = ferramentas_com_cache(ferramentas or [])

        def chamada(modelo: str) -> Resposta:
            parametros: dict[str, Any] = dict(
                model=modelo,
                max_tokens=config.max_tokens,
                system=system_com_cache(system),
                messages=mensagens,
                output_config={"effort": config.esforco},
                cache_control={"type": "ephemeral"},  # cache automático da conversa
            )
            if ferramentas:
                parametros["tools"] = ferramentas
            if modelo in MODELOS_COM_FALLBACK_RECUSA:
                parametros["betas"] = [BETA_FALLBACK_RECUSA]
                parametros["fallbacks"] = "default"
            else:
                parametros["betas"] = []

            emitiu = False
            with span("llm.stream", "llm", modelo=modelo, n_mensagens=len(mensagens),
                      ultima_mensagem=mensagens[-1] if mensagens else None) as s:
                try:
                    with self.cliente.beta.messages.stream(**parametros) as stream:
                        for evento in stream:
                            if evento.type == "text" and ao_receber_texto:
                                emitiu = True
                                ao_receber_texto(evento.text)
                        final = stream.get_final_message()
                except Exception:
                    if emitiu and ao_reiniciar:
                        ao_reiniciar(modelo)  # a UI descarta o texto parcial
                    raise
                uso = uso_para_dict(final.usage)
                modelo_usado = getattr(final, "model", modelo) or modelo
                custo = custo_usd(modelo_usado, uso)
                conteudo = [_bloco_para_dict(b) for b in final.content]
                s.registrar(
                    modelo_usado=modelo_usado,
                    stop_reason=final.stop_reason,
                    uso=uso,
                    custo_usd=round(custo, 6),
                    resposta=[b for b in conteudo if b.get("type") in ("text", "tool_use")],
                )
            return Resposta(conteudo, final.stop_reason, modelo_usado, uso, custo)

        return self._com_fallback("conversar", chamada)

    # ------------------------------------------------------------------ estruturado
    def estruturado(
        self,
        *,
        system: str,
        mensagem: str,
        formato: type[T],
        modelo: str | None = None,
        esforco: str = "low",
        max_tokens: int = 4000,
    ) -> T:
        """Peça 7 — resposta obrigatoriamente no schema (Pydantic), com fallback."""
        modelos = [modelo] if modelo else self.modelos

        def chamada(m: str) -> T:
            with span("llm.estruturado", "llm", modelo=m, formato=formato.__name__) as s:
                r = self.cliente.messages.parse(
                    model=m,
                    max_tokens=max_tokens,
                    system=system_com_cache(system),
                    messages=[{"role": "user", "content": mensagem}],
                    output_config={"effort": esforco},
                    output_format=formato,
                )
                uso = uso_para_dict(r.usage)
                s.registrar(uso=uso, custo_usd=round(custo_usd(m, uso), 6), stop_reason=r.stop_reason)
                if r.stop_reason == "refusal" or r.parsed_output is None:
                    raise ValueError(f"modelo não devolveu {formato.__name__} (stop_reason={r.stop_reason})")
                s.registrar(saida=r.parsed_output.model_dump())
                return r.parsed_output

        return self._com_fallback(f"estruturado:{formato.__name__}", chamada, modelos)

    def contar_tokens(self, *, system: str, mensagens: list[dict[str, Any]],
                      ferramentas: list[dict[str, Any]] | None = None) -> int:
        params: dict[str, Any] = dict(model=self.modelos[0], system=system, messages=mensagens)
        if ferramentas:
            params["tools"] = ferramentas
        return self.cliente.messages.count_tokens(**params).input_tokens
