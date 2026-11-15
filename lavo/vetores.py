"""Peça 4 — BANCO VETORIAL.

"Comparar a pergunta com um milhão de trechos, um por um, demora demais. Então
você guarda tudo num banco que acha os vizinhos mais próximos em milissegundos."

Usa o ChromaDB (índice HNSW, persistido em ``.vetores/``). Cada provedor de
embeddings tem sua própria coleção, porque vetores de modelos diferentes não
são comparáveis.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb

from .config import config


@dataclass
class Trecho:
    id: str
    texto: str
    fonte: str
    titulo: str
    similaridade: float = 0.0


class BancoVetorial:
    def __init__(self, nome_embeddings: str, pasta: Path | None = None, em_memoria: bool = False) -> None:
        if em_memoria:
            self.cliente = chromadb.EphemeralClient()
        else:
            pasta = pasta or config.pasta_vetores
            pasta.mkdir(parents=True, exist_ok=True)
            self.cliente = chromadb.PersistentClient(path=str(pasta))
        self.colecao = self.cliente.get_or_create_collection(
            name=f"docs-{nome_embeddings}"[:60],
            metadata={"hnsw:space": "cosine"},
        )

    def __len__(self) -> int:
        return self.colecao.count()

    def assinaturas_por_fonte(self) -> dict[str, str]:
        """fonte -> hash do arquivo indexado (para reindexar só o que mudou)."""
        dados = self.colecao.get(include=["metadatas"])
        return {m["fonte"]: m["hash_arquivo"] for m in dados["metadatas"] or []}

    def remover_fonte(self, fonte: str) -> None:
        self.colecao.delete(where={"fonte": fonte})

    def adicionar(self, trechos: list[Trecho], vetores: list[list[float]], meta_extra: dict[str, Any]) -> None:
        if not trechos:
            return
        self.colecao.upsert(
            ids=[t.id for t in trechos],
            documents=[t.texto for t in trechos],
            embeddings=vetores,
            metadatas=[{"fonte": t.fonte, "titulo": t.titulo, **meta_extra} for t in trechos],
        )

    def vizinhos(self, vetor: list[float], k: int) -> list[Trecho]:
        if len(self) == 0:
            return []
        r = self.colecao.query(query_embeddings=[vetor], n_results=min(k, len(self)),
                               include=["documents", "metadatas", "distances"])
        return [
            Trecho(id=i, texto=d, fonte=m["fonte"], titulo=m["titulo"], similaridade=round(1 - dist, 4))
            for i, d, m, dist in zip(r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0])
        ]
