"""Peça 1 — HISTÓRICO / JANELA DE CONTEXTO.

"Na segunda mensagem ela já esqueceu a primeira. Então você manda a conversa
inteira junto em toda chamada. Essa é a janela de contexto."

A API não guarda estado: cada chamada recebe o histórico completo. O histórico
aqui é *append-only* (só cresce, nunca é editado no meio) — isso mantém o cache
de prompt válido e preserva os blocos de raciocínio do modelo.

Quando a conversa passa de ``LAVO_LIMITE_HISTORICO`` tokens, ela é resumida e
recomeça a partir do resumo (uma conversa nova, não uma edição da antiga).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import config
from .observabilidade import span


class ResumoDaConversa(BaseModel):
    resumo: str = Field(description="Resumo fiel do que foi conversado e decidido")
    fatos_do_cliente: list[str] = Field(description="Fatos sobre o cliente que precisam ser lembrados")
    pendencias: list[str] = Field(description="O que ainda está em aberto")


@dataclass
class Conversa:
    cliente_id: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    mensagens: list[dict[str, Any]] = field(default_factory=list)
    tokens_ultima_chamada: int = 0  # tamanho real do contexto, medido pela API
    resumos: int = 0

    def adicionar_usuario(self, conteudo: str | list[dict[str, Any]]) -> None:
        self.mensagens.append({"role": "user", "content": conteudo})

    def adicionar_assistente(self, blocos: list[dict[str, Any]]) -> None:
        # Guarda os blocos completos (texto, tool_use, thinking...), sem reescrever nada.
        self.mensagens.append({"role": "assistant", "content": blocos})

    def registrar_uso(self, uso: dict[str, int]) -> None:
        self.tokens_ultima_chamada = (
            uso.get("input_tokens", 0)
            + uso.get("cache_read_input_tokens", 0)
            + uso.get("cache_creation_input_tokens", 0)
            + uso.get("output_tokens", 0)
        )

    def precisa_resumir(self, limite: int | None = None) -> bool:
        return self.tokens_ultima_chamada > (limite or config.limite_tokens_historico)

    def resumir(self, llm: Any) -> None:
        """Compacta o histórico num resumo e recomeça a conversa a partir dele."""
        transcricao = []
        for m in self.mensagens:
            if isinstance(m["content"], str):
                transcricao.append(f"{m['role']}: {m['content']}")
                continue
            for b in m["content"]:
                if b.get("type") == "text":
                    transcricao.append(f"{m['role']}: {b['text']}")
                elif b.get("type") == "tool_use":
                    transcricao.append(f"ferramenta chamada: {b['name']}({json.dumps(b['input'], ensure_ascii=False)})")
                elif b.get("type") == "tool_result":
                    transcricao.append(f"resultado: {str(b.get('content'))[:500]}")
        with span("conversa.resumir", "contexto", tokens_antes=self.tokens_ultima_chamada):
            r = llm.estruturado(
                system="Você resume conversas de atendimento sem perder fatos, números e decisões.",
                mensagem="\n".join(transcricao),
                formato=ResumoDaConversa,
                modelo=config.modelo_auxiliar,
            )
        texto = (
            "[Resumo da conversa anterior]\n"
            f"{r.resumo}\n\nFatos do cliente:\n- " + "\n- ".join(r.fatos_do_cliente or ["(nenhum)"])
            + "\n\nPendências:\n- " + "\n- ".join(r.pendencias or ["(nenhuma)"])
        )
        self.mensagens = [{"role": "user", "content": texto}]
        self.tokens_ultima_chamada = 0
        self.resumos += 1

    # Persistência simples (o servidor HTTP guarda uma conversa por sessão)
    def salvar(self, pasta: Path) -> None:
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / f"{self.id}.json").write_text(
            json.dumps(self.__dict__, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def carregar(cls, pasta: Path, conversa_id: str) -> "Conversa | None":
        arq = pasta / f"{conversa_id}.json"
        if not arq.exists():
            return None
        return cls(**json.loads(arq.read_text(encoding="utf-8")))
