"""Peça 3 — EMBEDDINGS.

"Buscar por palavra não acha 'cancelar plano' quando o documento diz 'encerrar
assinatura'. Então você transforma cada trecho numa lista de números que
representa o significado. Esses são embeddings."

Provedores (``LAVO_EMBEDDINGS``):
* ``voyage`` — Voyage AI (recomendado pela Anthropic; precisa de VOYAGE_API_KEY).
* ``local``  — sentence-transformers multilíngue, roda na sua máquina.
* ``hash``   — sem rede e sem modelo; NÃO entende significado. Só para testes.
* ``auto``   — voyage se houver chave, senão local se instalado, senão hash.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import unicodedata
import warnings
from typing import Protocol

from .config import config


class Embeddings(Protocol):
    nome: str

    def documentos(self, textos: list[str]) -> list[list[float]]: ...
    def consulta(self, texto: str) -> list[float]: ...


class VoyageEmbeddings:
    def __init__(self, modelo: str) -> None:
        import voyageai  # pip install voyageai

        self.cliente = voyageai.Client()
        self.modelo = modelo
        self.nome = f"voyage-{modelo}"

    def documentos(self, textos: list[str]) -> list[list[float]]:
        saida: list[list[float]] = []
        for i in range(0, len(textos), 128):
            r = self.cliente.embed(textos[i : i + 128], model=self.modelo, input_type="document")
            saida.extend(r.embeddings)
        return saida

    def consulta(self, texto: str) -> list[float]:
        return self.cliente.embed([texto], model=self.modelo, input_type="query").embeddings[0]


class LocalEmbeddings:
    def __init__(self, modelo: str) -> None:
        from sentence_transformers import SentenceTransformer  # pip install sentence-transformers

        self.modelo = SentenceTransformer(modelo)
        self.nome = "local-" + re.sub(r"[^a-z0-9]+", "-", modelo.lower()).strip("-")

    def documentos(self, textos: list[str]) -> list[list[float]]:
        return self.modelo.encode(textos, normalize_embeddings=True).tolist()

    def consulta(self, texto: str) -> list[float]:
        return self.modelo.encode([texto], normalize_embeddings=True)[0].tolist()


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


class HashEmbeddings:
    """Vetor de n-gramas com hashing. Determinístico e offline, mas sem semântica."""

    def __init__(self, dimensoes: int = 512) -> None:
        self.dim = dimensoes
        self.nome = f"hash-{dimensoes}"

    def _vetor(self, texto: str) -> list[float]:
        v = [0.0] * self.dim
        palavras = re.findall(r"[a-z0-9]+", _normalizar(texto))
        tokens = palavras + [p[i : i + 4] for p in palavras if len(p) > 4 for i in range(len(p) - 3)]
        for t in tokens:
            h = int(hashlib.md5(t.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 8) & 1 else -1.0
        norma = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norma for x in v]

    def documentos(self, textos: list[str]) -> list[list[float]]:
        return [self._vetor(t) for t in textos]

    def consulta(self, texto: str) -> list[float]:
        return self._vetor(texto)


def criar_embeddings(provedor: str | None = None) -> Embeddings:
    provedor = provedor or config.provedor_embeddings
    if provedor == "voyage" or (provedor == "auto" and os.getenv("VOYAGE_API_KEY")):
        return VoyageEmbeddings(config.modelo_voyage)
    if provedor in ("local", "auto"):
        try:
            return LocalEmbeddings(config.modelo_local)
        except ImportError:
            if provedor == "local":
                raise
    if provedor not in ("hash", "auto"):
        raise ValueError(f"provedor de embeddings desconhecido: {provedor}")
    if provedor == "auto":
        warnings.warn(
            "Usando embeddings 'hash' (sem semântica). Defina VOYAGE_API_KEY ou "
            "instale sentence-transformers para busca por significado.",
            stacklevel=2,
        )
    return HashEmbeddings()
