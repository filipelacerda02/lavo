"""Fixtures: cliente Anthropic falso (sem rede) e pastas temporárias."""

from __future__ import annotations

import copy
import dataclasses
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lavo import observabilidade
from lavo.config import RAIZ, config
from lavo.embeddings import HashEmbeddings
from lavo.ferramentas import Loja
from lavo.rag import RAG
from lavo.vetores import BancoVetorial


@pytest.fixture(autouse=True)
def traces_temporarios(tmp_path, monkeypatch):
    monkeypatch.setattr(observabilidade, "config", dataclasses.replace(config, pasta_traces=tmp_path / "traces"))
    return tmp_path / "traces"


@pytest.fixture
def loja(tmp_path) -> Loja:
    copia = tmp_path / "clientes.json"
    shutil.copy(RAIZ / "dados" / "clientes.json", copia)
    return Loja(copia)


@pytest.fixture
def rag() -> RAG:
    emb = HashEmbeddings()
    r = RAG(embeddings=emb, banco=BancoVetorial(f"teste-{uuid.uuid4().hex[:8]}", em_memoria=True))
    r.indexar(RAIZ / "docs")
    return r


def uso(entrada=100, saida=50, cache_leitura=0, cache_escrita=0):
    return SimpleNamespace(input_tokens=entrada, output_tokens=saida,
                           cache_read_input_tokens=cache_leitura, cache_creation_input_tokens=cache_escrita)


def texto(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


def ferramenta(nome: str, entrada: dict[str, Any], id_: str = "toolu_1") -> dict[str, Any]:
    return {"type": "tool_use", "id": id_, "name": nome, "input": entrada}


class _Stream:
    def __init__(self, resposta):
        self.resposta = resposta

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for b in self.resposta.content:
            if b["type"] == "text":
                # entrega em pedaços pequenos, como o streaming real
                for i in range(0, len(b["text"]), 7):
                    yield SimpleNamespace(type="text", text=b["text"][i : i + 7])

    def get_final_message(self):
        return self.resposta


class ClienteFalso:
    """Imita anthropic.Anthropic: devolve respostas roteirizadas ou levanta erros."""

    def __init__(self, roteiro: list[Any]):
        self.roteiro = list(roteiro)
        self.chamadas: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))
        self.messages = SimpleNamespace(parse=self._parse, count_tokens=lambda **k: SimpleNamespace(input_tokens=10))

    def _proximo(self, params):
        self.chamadas.append(copy.deepcopy(params))  # o agente continua alterando a lista
        item = self.roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def _stream(self, **params):
        item = self._proximo(params)
        conteudo, stop = item
        return _Stream(SimpleNamespace(content=conteudo, stop_reason=stop, usage=uso(), model=params["model"]))

    def _parse(self, **params):
        item = self._proximo(params)
        return SimpleNamespace(parsed_output=item, stop_reason="end_turn", usage=uso())


@pytest.fixture
def cliente_falso():
    return ClienteFalso
