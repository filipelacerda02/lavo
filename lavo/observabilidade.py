"""Peça 13 — OBSERVABILIDADE.

"Um cliente reclama de resposta errada e você não faz ideia do que aconteceu.
Então você grava cada passo: prompt, ferramentas, tokens e custo."

Cada interação vira um *trace* (um arquivo JSONL por dia em ``traces/``), composto
de *spans*: chamada ao LLM, busca no RAG, ferramenta executada, guardrail, fallback.
Cada span guarda entrada, saída, duração, tokens e custo em dólar.

Ver os traces:  ``python -m lavo.observabilidade``  (resumo)  ou
                ``python -m lavo.observabilidade <trace_id>``  (passo a passo)
"""

from __future__ import annotations

import contextvars
import json
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import config

# Preço em US$ por 1M de tokens: (entrada, saída, leitura de cache).
# Escrita de cache custa 1,25x a entrada (TTL de 5 min).
PRECOS: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
}


def custo_usd(modelo: str, uso: dict[str, int]) -> float:
    entrada, saida, leitura = PRECOS.get(modelo, PRECOS["claude-opus-5-5"])
    return (
        uso.get("input_tokens", 0) * entrada
        + uso.get("cache_creation_input_tokens", 0) * entrada * 1.25
        + uso.get("cache_read_input_tokens", 0) * leitura
        + uso.get("output_tokens", 0) * saida
    ) / 1_000_000


def uso_para_dict(usage: Any) -> dict[str, int]:
    """Converte ``response.usage`` do SDK num dict só com os contadores."""
    if usage is None:
        return {}
    campos = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    return {c: int(getattr(usage, c, 0) or 0) for c in campos}


def _resumir(valor: Any, limite: int = 4000) -> Any:
    """Evita traces gigantes: corta strings longas, mantém estrutura."""
    if isinstance(valor, str):
        return valor if len(valor) <= limite else valor[:limite] + f"... [+{len(valor) - limite} chars]"
    if isinstance(valor, dict):
        return {k: _resumir(v, limite) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_resumir(v, limite) for v in valor]
    if isinstance(valor, (int, float, bool)) or valor is None:
        return valor
    return _resumir(str(valor), limite)


@dataclass
class Span:
    nome: str
    tipo: str
    trace_id: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    pai: str | None = None
    inicio: float = field(default_factory=time.time)
    dados: dict[str, Any] = field(default_factory=dict)

    def registrar(self, **kv: Any) -> None:
        self.dados.update(kv)


class Trace:
    def __init__(self, nome: str, **meta: Any) -> None:
        self.id = uuid.uuid4().hex[:16]
        self.nome = nome
        self.meta = meta
        self.inicio = time.time()
        self.spans: list[dict[str, Any]] = []
        self._pilha: list[Span] = []

    @property
    def custo_total(self) -> float:
        return sum(s.get("custo_usd", 0.0) for s in self.spans)

    @property
    def tokens_total(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for s in self.spans:
            for k, v in (s.get("uso") or {}).items():
                total[k] = total.get(k, 0) + v
        return total

    @contextmanager
    def span(self, nome: str, tipo: str, **dados: Any) -> Iterator[Span]:
        pai = self._pilha[-1].span_id if self._pilha else None
        s = Span(nome=nome, tipo=tipo, trace_id=self.id, pai=pai, dados=dict(dados))
        self._pilha.append(s)
        erro: str | None = None
        try:
            yield s
        except BaseException as e:  # registra e propaga
            erro = f"{type(e).__name__}: {e}"
            raise
        finally:
            self._pilha.pop()
            registro = {
                "trace_id": self.id,
                "span_id": s.span_id,
                "pai": s.pai,
                "nome": nome,
                "tipo": tipo,
                "inicio": datetime.fromtimestamp(s.inicio, timezone.utc).isoformat(),
                "duracao_ms": round((time.time() - s.inicio) * 1000, 1),
                **_resumir(s.dados),
            }
            if erro:
                registro["erro"] = erro
            self.spans.append(registro)

    def finalizar(self, **dados: Any) -> dict[str, Any]:
        registro = {
            "trace_id": self.id,
            "nome": self.nome,
            "tipo": "trace",
            "inicio": datetime.fromtimestamp(self.inicio, timezone.utc).isoformat(),
            "duracao_ms": round((time.time() - self.inicio) * 1000, 1),
            "custo_usd": round(self.custo_total, 6),
            "uso": self.tokens_total,
            "meta": _resumir(self.meta),
            **_resumir(dados),
        }
        _gravar([*self.spans, registro])
        return registro


_trace_atual: contextvars.ContextVar[Trace | None] = contextvars.ContextVar("trace", default=None)


def trace_atual() -> Trace | None:
    return _trace_atual.get()


@contextmanager
def novo_trace(nome: str, **meta: Any) -> Iterator[Trace]:
    t = Trace(nome, **meta)
    token = _trace_atual.set(t)
    resultado: dict[str, Any] = {}
    try:
        yield t
    except BaseException as e:
        resultado["erro"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        _trace_atual.reset(token)
        t.finalizar(**resultado)


@contextmanager
def span(nome: str, tipo: str, **dados: Any) -> Iterator[Span]:
    """Abre um span no trace atual; se não houver trace, vira no-op."""
    t = trace_atual()
    if t is None:
        yield Span(nome=nome, tipo=tipo, trace_id="-", dados=dict(dados))
        return
    with t.span(nome, tipo, **dados) as s:
        yield s


def _gravar(registros: list[dict[str, Any]]) -> None:
    pasta = config.pasta_traces
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
    with arquivo.open("a", encoding="utf-8") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def ler_traces(pasta: Path | None = None) -> list[dict[str, Any]]:
    pasta = pasta or config.pasta_traces
    registros: list[dict[str, Any]] = []
    for arq in sorted(pasta.glob("*.jsonl")):
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                registros.append(json.loads(linha))
    return registros


def _main(argv: list[str]) -> None:
    registros = ler_traces()
    if not registros:
        print("Nenhum trace ainda. Converse com o agente primeiro.")
        return
    if argv:
        alvo = argv[0]
        spans = [r for r in registros if r["trace_id"].startswith(alvo)]
        for r in spans:
            recuo = "  " if r.get("pai") else ""
            linha = f"{recuo}[{r['tipo']}] {r['nome']}  {r['duracao_ms']}ms"
            if r.get("custo_usd"):
                linha += f"  ${r['custo_usd']:.5f}"
            print(linha)
            for k, v in r.items():
                if k in {"trace_id", "span_id", "pai", "nome", "tipo", "inicio", "duracao_ms"}:
                    continue
                print(f"{recuo}    {k}: {json.dumps(v, ensure_ascii=False)[:300]}")
        return
    traces = [r for r in registros if r["tipo"] == "trace"]
    print(f"{'trace_id':18} {'quando':20} {'ms':>8} {'custo':>10}  pergunta")
    for t in traces[-30:]:
        pergunta = str((t.get("meta") or {}).get("pergunta", ""))[:50]
        print(
            f"{t['trace_id']:18} {t['inicio'][:19]:20} {t['duracao_ms']:>8.0f} "
            f"${t.get('custo_usd', 0):>9.5f}  {pergunta}"
        )
    total = sum(t.get("custo_usd", 0) for t in traces)
    print(f"\n{len(traces)} traces, custo total ${total:.4f}")


if __name__ == "__main__":
    _main(sys.argv[1:])
