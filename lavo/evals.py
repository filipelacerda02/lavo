"""Peça 12 — EVALS.

"Você mudou uma linha do prompt e quebrou três respostas que funcionavam. Então
você roda uma bateria de casos de teste a cada mudança. Esses são os evals."

    python -m lavo.evals             # roda tudo (usa a API)
    python -m lavo.evals --offline   # só os casos que não chamam o modelo
    python -m lavo.evals -k triagem  # filtra por id

Cada caso roda numa cópia isolada dos dados. Checagens disponíveis:
``contem``, ``nao_contem``, ``ferramentas``, ``sem_ferramentas``, ``estado``
(valor no "banco" depois da conversa), ``bloqueado``, ``campos`` (structured
output) e ``criterio_juiz`` (um modelo avalia a resposta contra o critério).

Os resultados vão para ``evals/resultados/`` e são comparados com a rodada
anterior: o relatório aponta REGRESSÕES (casos que passavam e quebraram).
Sai com código 1 se algum caso falhar — dá para usar no CI.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import RAIZ, config
from .guardrails import verificar_documento, verificar_entrada, verificar_saida

PASTA = RAIZ / "evals"


class Veredito(BaseModel):
    aprovado: bool
    motivo: str = Field(description="Uma frase justificando")


def _norm(t: str) -> str:
    return t.lower()


def _valor(dados: dict[str, Any], caminho: str) -> Any:
    atual: Any = dados
    for parte in caminho.split("."):
        atual = atual.get(parte) if isinstance(atual, dict) else None
    return atual


def checar_texto(texto: str, esperado: dict[str, Any]) -> list[str]:
    falhas = []
    for t in esperado.get("contem", []):
        if _norm(t) not in _norm(texto):
            falhas.append(f"deveria conter {t!r}")
    for t in esperado.get("nao_contem", []):
        if _norm(t) in _norm(texto):
            falhas.append(f"não deveria conter {t!r}")
    return falhas


def julgar(llm: Any, pergunta: str, resposta: str, criterio: str) -> list[str]:
    v = llm.estruturado(
        system=("Você avalia respostas de um assistente de atendimento. Aprove somente se a resposta "
                "cumpre TODO o critério. Seja rigoroso e objetivo."),
        mensagem=f"<conversa>\n{pergunta}\n</conversa>\n<resposta>\n{resposta}\n</resposta>\n<criterio>\n{criterio}\n</criterio>",
        formato=Veredito,
        modelo=config.modelo_auxiliar,
    )
    return [] if v.aprovado else [f"juiz: {v.motivo}"]


def rodar_caso(caso: dict[str, Any], llm: Any = None, rag: Any = None) -> dict[str, Any]:
    tipo, esp = caso["tipo"], caso["esperado"]
    inicio = time.time()
    falhas: list[str] = []
    detalhes: dict[str, Any] = {}

    if tipo == "guardrail_entrada":
        v = verificar_entrada(caso["entrada"])
        detalhes["motivos"] = v.motivos
        if v.bloqueado != esp["bloqueado"]:
            falhas.append(f"bloqueado={v.bloqueado}, esperado {esp['bloqueado']}")

    elif tipo == "guardrail_documento":
        v = verificar_documento(caso["entrada"])
        detalhes["motivos"] = v.motivos
        if v.bloqueado != esp["bloqueado"]:
            falhas.append(f"bloqueado={v.bloqueado}, esperado {esp['bloqueado']}")

    elif tipo == "guardrail_saida":
        from .ferramentas import Ferramentas

        permitidos = Ferramentas(caso["cliente_id"]).dados_pessoais_permitidos()
        v = verificar_saida(caso["entrada"], permitidos)
        detalhes["saida"] = v.texto
        falhas += checar_texto(v.texto or "", esp)

    elif tipo == "triagem":
        from .saida_estruturada import triar

        t = triar(caso["entrada"], llm)
        detalhes["saida"] = t.model_dump()
        for campo, valor in esp.get("campos", {}).items():
            if getattr(t, campo) != valor:
                falhas.append(f"{campo}={getattr(t, campo)!r}, esperado {valor!r}")

    elif tipo == "agente":
        from .agente import Agente
        from .ferramentas import Ferramentas, Loja

        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "clientes.json"
            shutil.copy(config.dados_clientes, copia)
            loja = Loja(copia)
            agente = Agente(caso["cliente_id"], llm=llm, rag=rag,
                            ferramentas=Ferramentas(caso["cliente_id"], loja=loja, rag=rag))
            respostas, usadas, custo = [], [], 0.0
            for turno in caso["turnos"]:
                r = agente.responder(turno)
                respostas.append(r.texto)
                usadas += r.ferramentas_usadas
                custo += r.custo_usd
            final = respostas[-1]
            detalhes.update(resposta=final, ferramentas=usadas, custo_usd=round(custo, 5))
            falhas += checar_texto(final, esp)
            for f in esp.get("ferramentas", []):
                if f not in usadas:
                    falhas.append(f"deveria chamar {f}")
            for f in esp.get("sem_ferramentas", []):
                if f in usadas:
                    falhas.append(f"não deveria chamar {f}")
            dados = loja.ler()
            for caminho, valor in esp.get("estado", {}).items():
                atual = _valor(dados, caminho)
                if atual != valor:
                    falhas.append(f"{caminho}={atual!r}, esperado {valor!r}")
            if esp.get("criterio_juiz"):
                conversa = "\n".join(f"cliente: {t}\nassistente: {r}" for t, r in zip(caso["turnos"], respostas))
                falhas += julgar(llm, conversa, final, esp["criterio_juiz"])
    else:
        falhas.append(f"tipo desconhecido: {tipo}")

    return {"id": caso["id"], "tipo": tipo, "passou": not falhas, "falhas": falhas,
            "duracao_s": round(time.time() - inicio, 2), **detalhes}


OFFLINE = {"guardrail_entrada", "guardrail_documento", "guardrail_saida"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Roda a bateria de evals")
    ap.add_argument("--offline", action="store_true", help="só casos que não usam a API")
    ap.add_argument("-k", help="filtra casos cujo id contém este texto")
    args = ap.parse_args(argv)

    casos = json.loads((PASTA / "casos.json").read_text(encoding="utf-8"))
    if args.offline:
        casos = [c for c in casos if c["tipo"] in OFFLINE]
    if args.k:
        casos = [c for c in casos if args.k in c["id"]]

    llm = rag = None
    if any(c["tipo"] not in OFFLINE for c in casos):
        from .llm import LLM
        from .rag import RAG

        llm, rag = LLM(), RAG()
        rag.indexar()

    from .observabilidade import novo_trace

    resultados = []
    for caso in casos:
        with novo_trace("eval", pergunta=f"[eval] {caso['id']}"):
            try:
                r = rodar_caso(caso, llm, rag)
            except Exception as e:  # noqa: BLE001 - um caso quebrado não derruba a bateria
                r = {"id": caso["id"], "tipo": caso["tipo"], "passou": False, "falhas": [f"erro: {e!r}"]}
        resultados.append(r)
        marca = "PASSOU" if r["passou"] else "FALHOU"
        print(f"[{marca}] {caso['id']}" + ("" if r["passou"] else f"  -> {'; '.join(r['falhas'])}"))

    pasta_res = PASTA / "resultados"
    pasta_res.mkdir(exist_ok=True)
    anteriores = sorted(pasta_res.glob("*.json"))
    regressoes: list[str] = []
    if anteriores:
        antes = {r["id"]: r["passou"] for r in json.loads(anteriores[-1].read_text(encoding="utf-8"))["resultados"]}
        regressoes = [r["id"] for r in resultados if antes.get(r["id"]) and not r["passou"]]

    aprovados = sum(r["passou"] for r in resultados)
    resumo = {"quando": datetime.now().isoformat(timespec="seconds"), "aprovados": aprovados,
              "total": len(resultados), "regressoes": regressoes, "resultados": resultados}
    (pasta_res / f"{datetime.now():%Y%m%d-%H%M%S}.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{aprovados}/{len(resultados)} casos passaram.")
    if regressoes:
        print(f"REGRESSÕES (passavam na rodada anterior): {', '.join(regressoes)}")
    return 0 if aprovados == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
