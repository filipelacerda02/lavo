"""Peça 2 — RAG (Retrieval-Augmented Generation).

"O usuário pergunta sobre a política da empresa e o modelo inventa a resposta.
Então você busca os trechos certos nos documentos e cola no prompt. Isso é RAG."

Fluxo: documentos (``docs/``: .md, .txt, .pdf) -> trechos -> embeddings (peça 3)
-> banco vetorial (peça 4). Na pergunta: embedding da pergunta -> vizinhos mais
próximos -> guardrail nos trechos (peça 9) -> trechos colados no prompt.

Indexar:  ``python -m lavo.rag``  (só reprocessa arquivos que mudaram)
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from .config import config
from .embeddings import Embeddings, criar_embeddings
from .guardrails import verificar_documento
from .observabilidade import span
from .vetores import BancoVetorial, Trecho

TAMANHO_TRECHO = 900


def ler_arquivo(caminho: Path) -> str:
    if caminho.suffix.lower() == ".pdf":
        from pypdf import PdfReader  # pip install pypdf

        return "\n".join(p.extract_text() or "" for p in PdfReader(str(caminho)).pages)
    return caminho.read_text(encoding="utf-8")


def dividir_em_trechos(texto: str, fonte: str, tamanho: int = TAMANHO_TRECHO) -> list[Trecho]:
    """Divide por seções (títulos markdown) e, se preciso, por parágrafos."""
    secoes: list[tuple[str, str]] = []
    titulo, corpo = Path(fonte).stem, []
    for linha in texto.splitlines():
        if re.match(r"^#{1,6} ", linha):
            if "".join(corpo).strip():
                secoes.append((titulo, "\n".join(corpo).strip()))
            titulo, corpo = linha.lstrip("#").strip(), []
        else:
            corpo.append(linha)
    if "".join(corpo).strip():
        secoes.append((titulo, "\n".join(corpo).strip()))

    trechos: list[Trecho] = []
    for titulo, corpo in secoes:
        atual = ""
        for paragrafo in re.split(r"\n\s*\n", corpo):
            if atual and len(atual) + len(paragrafo) > tamanho:
                trechos.append(_trecho(fonte, titulo, atual, len(trechos)))
                atual = ""
            atual = f"{atual}\n\n{paragrafo}".strip()
        if atual:
            trechos.append(_trecho(fonte, titulo, atual, len(trechos)))
    return trechos


def _trecho(fonte: str, titulo: str, texto: str, n: int) -> Trecho:
    return Trecho(id=f"{fonte}#{n}", texto=f"{titulo}\n{texto}", fonte=fonte, titulo=titulo)


class RAG:
    def __init__(self, embeddings: Embeddings | None = None, banco: BancoVetorial | None = None) -> None:
        self.embeddings = embeddings or criar_embeddings()
        self.banco = banco or BancoVetorial(self.embeddings.nome)

    def indexar(self, pasta: Path | None = None) -> dict[str, int]:
        pasta = pasta or config.pasta_docs
        ja_indexados = self.banco.assinaturas_por_fonte()
        arquivos = sorted(p for p in pasta.rglob("*") if p.suffix.lower() in {".md", ".txt", ".pdf"})
        stats = {"arquivos": len(arquivos), "reindexados": 0, "trechos": 0, "bloqueados": 0}
        vistos = set()
        for arq in arquivos:
            fonte = str(arq.relative_to(pasta))
            vistos.add(fonte)
            conteudo = ler_arquivo(arq)
            assinatura = hashlib.sha256(conteudo.encode()).hexdigest()[:16]
            if ja_indexados.get(fonte) == assinatura:
                continue
            self.banco.remover_fonte(fonte)
            trechos = dividir_em_trechos(conteudo, fonte)
            # Guardrail na ENTRADA do índice: trecho com instrução escondida nem entra.
            limpos = []
            for t in trechos:
                if verificar_documento(t.texto).bloqueado:
                    stats["bloqueados"] += 1
                else:
                    limpos.append(t)
            self.banco.adicionar(limpos, self.embeddings.documentos([t.texto for t in limpos]),
                                 {"hash_arquivo": assinatura})
            stats["reindexados"] += 1
            stats["trechos"] += len(limpos)
        for fonte in set(ja_indexados) - vistos:
            self.banco.remover_fonte(fonte)
        return stats

    def buscar(self, pergunta: str, k: int | None = None) -> list[Trecho]:
        k = k or config.trechos_por_busca
        with span("rag.buscar", "rag", pergunta=pergunta, k=k, embeddings=self.embeddings.nome) as s:
            trechos = self.banco.vizinhos(self.embeddings.consulta(pergunta), k)
            # Guardrail na SAÍDA da busca também (defesa em profundidade).
            seguros = [t for t in trechos if not verificar_documento(t.texto).bloqueado]
            s.registrar(
                resultados=[{"id": t.id, "similaridade": t.similaridade} for t in trechos],
                descartados=len(trechos) - len(seguros),
            )
        return seguros


def formatar_contexto(trechos: list[Trecho]) -> str:
    """Trechos como DADOS delimitados, nunca como instruções."""
    if not trechos:
        return "<documentos>\nNenhum trecho relevante encontrado.\n</documentos>"
    partes = [
        f'<documento fonte="{t.fonte}" secao="{t.titulo}" similaridade="{t.similaridade}">\n{t.texto}\n</documento>'
        for t in trechos
    ]
    return "<documentos>\n" + "\n".join(partes) + "\n</documentos>"


if __name__ == "__main__":
    rag = RAG()
    print(f"Embeddings: {rag.embeddings.nome}")
    print(rag.indexar())
    if len(sys.argv) > 1:
        for t in rag.buscar(" ".join(sys.argv[1:])):
            print(f"\n[{t.similaridade}] {t.fonte} — {t.titulo}\n{t.texto[:300]}")
