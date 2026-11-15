"""Configuração central, lida de variáveis de ambiente (veja .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _carregar_dotenv() -> None:
    """Carrega um .env simples (CHAVE=valor) sem depender de bibliotecas extras."""
    arquivo = RAIZ / ".env"
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


_carregar_dotenv()


def _lista(nome: str, padrao: str) -> list[str]:
    return [p.strip() for p in os.getenv(nome, padrao).split(",") if p.strip()]


@dataclass(frozen=True)
class Config:
    # Peça 0 + 11: modelo principal e cadeia de fallback (troca de modelo se o provedor cair)
    modelos: list[str] = field(
        default_factory=lambda: _lista("LAVO_MODELOS", "claude-opus-5-5,claude-sonnet-5-5")
    )
    # Modelo barato para tarefas auxiliares (guardrail por LLM, juiz das evals, resumo)
    modelo_auxiliar: str = os.getenv("LAVO_MODELO_AUXILIAR", "claude-haiku-5-5")
    esforco: str = os.getenv("LAVO_ESFORCO", "medium")
    max_tokens: int = int(os.getenv("LAVO_MAX_TOKENS", "16000"))
    tentativas_por_modelo: int = int(os.getenv("LAVO_TENTATIVAS", "3"))

    # Peça 1: janela de contexto. Acima disso a conversa é resumida.
    limite_tokens_historico: int = int(os.getenv("LAVO_LIMITE_HISTORICO", "60000"))

    # Peças 2, 3, 4: RAG, embeddings, banco vetorial
    pasta_docs: Path = Path(os.getenv("LAVO_DOCS", str(RAIZ / "docs")))
    pasta_vetores: Path = Path(os.getenv("LAVO_VETORES", str(RAIZ / ".vetores")))
    provedor_embeddings: str = os.getenv("LAVO_EMBEDDINGS", "auto")  # auto|voyage|local|hash
    modelo_voyage: str = os.getenv("LAVO_MODELO_VOYAGE", "voyage-3.5")
    modelo_local: str = os.getenv(
        "LAVO_MODELO_LOCAL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    trechos_por_busca: int = int(os.getenv("LAVO_TOP_K", "4"))

    # Peça 6: limite de voltas do loop do agente
    max_passos_agente: int = int(os.getenv("LAVO_MAX_PASSOS", "8"))

    # Peça 9: guardrail extra com LLM (além das regras locais)
    guardrail_llm: bool = os.getenv("LAVO_GUARDRAIL_LLM", "0") == "1"

    # Peça 13 (observabilidade): onde os traces são gravados
    pasta_traces: Path = Path(os.getenv("LAVO_TRACES", str(RAIZ / "traces")))

    dados_clientes: Path = Path(os.getenv("LAVO_DADOS", str(RAIZ / "dados" / "clientes.json")))


config = Config()
