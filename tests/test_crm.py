"""Testes do CRM: fluxo WhatsApp -> agente -> humano, programação do agente e permissões.

Usa WhatsApp em modo simulado e um cliente Anthropic falso (nenhuma rede).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_PASTA = tempfile.mkdtemp(prefix="crm-teste-")
os.environ["CRM_DADOS"] = _PASTA
os.environ["WHATSAPP_GATEWAY_TOKEN"] = "token-teste"
os.environ.pop("WHATSAPP_GATEWAY_URL", None)
os.environ["CRM_AQUECER_AGENTE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from crm import atendimento  # noqa: E402
from crm.agenda import _na_grade  # noqa: E402
from crm.db import sessao  # noqa: E402
from crm.main import app  # noqa: E402
from crm.modelos import Conversa, HorarioAgente, Mensagem  # noqa: E402
from lavo.llm import LLM  # noqa: E402

from .conftest import ClienteFalso, ferramenta, texto  # noqa: E402

H = {"X-Requested-With": "lavo"}
TEL_ANA = "5511988881111"  # bate com o cadastro de exemplo (11) 98888-1111


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        r = c.post("/api/setup", json={"nome": "Admin", "email": "admin@lavo.com", "senha": "senha-forte-1"}, headers=H)
        assert r.status_code == 200, r.text
        r = c.put("/api/agente/config", json={"espera_agrupar_s": 0, "agente_modo": "ligado"}, headers=H)
        assert r.status_code == 200, r.text
        r = c.post("/api/usuarios", json={"nome": "Maria Atendente", "email": "maria@lavo.com", "senha": "senha-maria-1",
                                          "papel": "atendente", "cor": "#eb6834"}, headers=H)
        assert r.status_code == 200, r.text
        yield c


def roteiro(*respostas, rag=None):
    falso = ClienteFalso(list(respostas))
    atendimento.definir_componentes(LLM(cliente=falso, espera_base=0), rag)
    return falso


def entrar(c, email, senha):
    r = c.post("/api/login", json={"email": email, "senha": senha}, headers=H)
    assert r.status_code == 200, r.text


_seq = iter(range(1, 10**6))


def simular(c, tel, txt, nome=None):
    """Mensagem chegando do WhatsApp, pelo mesmo webhook que o gateway usa."""
    evento = {"tipo": "mensagem", "id": f"in-{next(_seq)}", "jid": f"{tel}@s.whatsapp.net", "telefone": tel,
              "nome": nome, "de_mim": False, "texto": txt, "midia": None}
    r = c.post("/api/whatsapp/webhook", json=evento, headers={"X-Gateway-Token": "token-teste"})
    assert r.status_code == 200, r.text
    with sessao() as db:
        return db.query(Conversa).join(Conversa.contato).filter_by(telefone=tel).order_by(Conversa.id.desc()).first().id


def esperar(condicao, segundos=5.0):
    fim = time.time() + segundos
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(0.05)
    return False


def mensagens(conv_id):
    with sessao() as db:
        return [(m.autor_tipo, m.direcao, m.texto, m.usuario.nome if m.usuario else None)
                for m in db.query(Mensagem).filter_by(conversa_id=conv_id).order_by(Mensagem.id)]


def conversa(conv_id):
    with sessao() as db:
        cv = db.get(Conversa, conv_id)
        return cv.modo, cv.atendente.nome if cv.atendente else None, cv.status, cv.motivo_fila


def autores(conv_id, tipo):
    return [m for m in mensagens(conv_id) if m[0] == tipo and m[1] == "saida"]


# ---------------------------------------------------------------- fluxo principal
def test_simulador(cliente, rag):
    roteiro(([texto("Olá!")], "end_turn"), rag=rag)
    r = cliente.post("/api/whatsapp/simular", json={"telefone": "5511900001111", "texto": "Oi", "nome": "Sim"}, headers=H)
    assert r.status_code == 200 and r.json()["conversa_id"]
    assert esperar(lambda: autores(r.json()["conversa_id"], "agente"))


def test_paginas_e_login(cliente):
    assert cliente.get("/conversas").status_code == 200
    assert cliente.get("/whatsapp").status_code == 200
    assert cliente.get("/configuracoes").status_code == 200
    assert cliente.post("/api/setup", json={"nome": "Xx", "email": "x@x.com", "senha": "12345678"}, headers=H).status_code == 409


def test_agente_atende_e_humano_assume(cliente, rag):
    falso = roteiro(([texto("Oi, Ana! Como posso ajudar?")], "end_turn"), rag=rag)
    conv_id = simular(cliente, TEL_ANA, "Oi, tudo bem?", "Ana")

    assert esperar(lambda: autores(conv_id, "agente")), mensagens(conv_id)
    assert conversa(conv_id)[0] == "agente"
    # contato vinculado ao cadastro pelo telefone -> agente sabe quem é
    assert "Ana Souza" in json.dumps(falso.chamadas[0]["messages"], ensure_ascii=False)
    lista = cliente.get("/api/conversas?filtro=agente").json()
    assert any(c["id"] == conv_id and c["responsavel"]["tipo"] == "agente" for c in lista["conversas"])

    # Maria (atendente) entra e responde: assume a conversa
    entrar(cliente, "maria@lavo.com", "senha-maria-1")
    r = cliente.post(f"/api/conversas/{conv_id}/mensagens", json={"texto": "Oi Ana, aqui é a Maria!"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["autor"] == {"tipo": "humano", "nome": "Maria Atendente", "usuario_id": r.json()["autor"]["usuario_id"],
                                 "cor": "#eb6834", "papel": "atendente"}
    assert conversa(conv_id)[:2] == ("humano", "Maria Atendente")

    # nova mensagem do cliente: o agente NÃO responde (humano no comando)
    chamadas_antes = len(falso.chamadas)
    simular(cliente, TEL_ANA, "Obrigada, Maria")
    time.sleep(0.5)
    assert len(falso.chamadas) == chamadas_antes
    assert len(autores(conv_id, "agente")) == 1
    detalhe = cliente.get(f"/api/conversas/{conv_id}").json()
    assert detalhe["conversa"]["responsavel"]["nome"] == "Maria Atendente"
    assert any("Maria Atendente assumiu" in m["texto"] for m in detalhe["mensagens"])

    # devolve ao agente: ele volta a responder sabendo o que a Maria falou
    falso.roteiro.append(([texto("Estou de volta, posso ajudar em algo mais?")], "end_turn"))
    assert cliente.post(f"/api/conversas/{conv_id}/devolver-agente", headers=H).status_code == 200
    simular(cliente, TEL_ANA, "Qual o prazo do lavar e passar?")
    assert esperar(lambda: len(autores(conv_id, "agente")) == 2), mensagens(conv_id)
    enviado = json.dumps(falso.chamadas[-1]["messages"], ensure_ascii=False)
    assert "Atendente Maria Atendente: Oi Ana, aqui é a Maria!" in enviado
    assert "Obrigada, Maria" in enviado  # o que o cliente disse ao humano vira contexto, não pergunta nova

    # resolver
    assert cliente.post(f"/api/conversas/{conv_id}/resolver", headers=H).status_code == 200
    assert conversa(conv_id)[2] == "resolvida"
    entrar(cliente, "admin@lavo.com", "senha-forte-1")


def test_agente_transfere_para_humano(cliente, rag):
    roteiro(
        ([ferramenta("transferir_para_humano", {"motivo": "Cliente pediu uma pessoa", "resumo_para_atendente": "Quer falar com alguém"})], "tool_use"),
        ([texto("Vou te passar para um atendente, só um instante.")], "end_turn"),
        rag=rag,
    )
    conv_id = simular(cliente, "5511977770000", "Quero falar com uma pessoa", "Rui")
    assert esperar(lambda: autores(conv_id, "agente")), mensagens(conv_id)
    modo, atendente, _, motivo = conversa(conv_id)
    assert modo == "fila" and atendente is None and motivo == "Cliente pediu uma pessoa"
    assert any("Agente transferiu" in m[2] for m in mensagens(conv_id))


def test_resposta_descartada_se_humano_assume_durante(cliente, rag):
    """Se um humano assume enquanto o agente pensa, a resposta do agente não é enviada."""
    roteiro(([texto("resposta atrasada")], "end_turn"), rag=rag)
    original = atendimento._rodar_agente

    def lento(*a, **k):
        time.sleep(0.6)
        return original(*a, **k)

    atendimento._rodar_agente = lento
    try:
        conv_id = simular(cliente, "5511966660000", "Olá", "Bia")
        time.sleep(0.2)
        assert cliente.post(f"/api/conversas/{conv_id}/assumir", headers=H).status_code == 200
        assert esperar(lambda: any("descartada" in m[2] for m in mensagens(conv_id)))
        assert not autores(conv_id, "agente")
    finally:
        atendimento._rodar_agente = original


def test_mensagem_pelo_celular_pausa_agente(cliente, rag):
    roteiro(([texto("Olá!")], "end_turn"), rag=rag)
    conv_id = simular(cliente, "5511955550000", "Bom dia", "Caio")
    assert esperar(lambda: autores(conv_id, "agente"))
    evento = {"tipo": "mensagem", "id": "cel-1", "jid": "5511955550000@s.whatsapp.net", "telefone": "5511955550000",
              "de_mim": True, "texto": "Caio, te respondo por aqui", "midia": None}
    assert cliente.post("/api/whatsapp/webhook", json=evento).status_code == 401  # sem token
    r = cliente.post("/api/whatsapp/webhook", json=evento, headers={"X-Gateway-Token": "token-teste"})
    assert r.status_code == 200
    assert conversa(conv_id)[:2] == ("humano", None)
    det = cliente.get(f"/api/conversas/{conv_id}").json()
    ultima = [m for m in det["mensagens"] if m["direcao"] == "saida"][-1]
    assert ultima["autor"]["nome"] == "Celular da empresa"


def test_agente_desligado_vai_para_fila_com_aviso(cliente, rag):
    falso = roteiro(rag=rag)
    assert cliente.put("/api/agente/config", json={"agente_modo": "desligado"}, headers=H).status_code == 200
    try:
        conv_id = simular(cliente, "5511944440000", "Tem alguém aí?", "Dani")
        time.sleep(0.3)
        modo, _, _, motivo = conversa(conv_id)
        assert modo == "fila" and motivo.startswith("Agente desligado")
        assert autores(conv_id, "sistema")  # mensagem automática de fora do horário
        assert falso.chamadas == []
    finally:
        cliente.put("/api/agente/config", json={"agente_modo": "ligado"}, headers=H)


def test_contato_so_humano(cliente, rag):
    falso = roteiro(rag=rag)
    contato = cliente.post("/api/contatos", json={"nome": "Eva", "telefone": "11933330000", "agente_bloqueado": True},
                           headers=H).json()
    assert contato["telefone"] == "5511933330000"
    conv_id = simular(cliente, "5511933330000", "Oi")
    time.sleep(0.3)
    assert conversa(conv_id)[0] == "fila" and falso.chamadas == []


# ---------------------------------------------------------------- programação
def test_grade_semanal():
    fuso = ZoneInfo("America/Sao_Paulo")
    h = [HorarioAgente(dia_semana=0, inicio="18:00", fim="08:59")]  # segunda 18h -> terça 8h59
    seg_19h = datetime(2026, 11, 16, 19, 0, tzinfo=fuso)
    ter_07h = datetime(2026, 11, 17, 7, 0, tzinfo=fuso)
    ter_10h = datetime(2026, 11, 17, 10, 0, tzinfo=fuso)
    assert _na_grade(seg_19h, h) and _na_grade(ter_07h, h) and not _na_grade(ter_10h, h)


def test_programacao_e_excecao(cliente):
    assert cliente.put("/api/agente/config", json={"agente_modo": "automatico"}, headers=H).status_code == 200
    try:
        assert cliente.put("/api/agente/horarios", json=[], headers=H).status_code == 200
        st = cliente.get("/api/agente/status").json()
        assert st["ativo"] is False and st["motivo"] == "fora do horário programado"
        agora = datetime.now(timezone.utc)
        r = cliente.post("/api/agente/excecoes", headers=H, json={
            "descricao": "Plantão", "inicio": (agora.replace(microsecond=0)).isoformat(),
            "fim": agora.replace(year=agora.year + 1).isoformat(), "agente_ativo": True})
        assert r.status_code == 200, r.text
        st = cliente.get("/api/agente/status").json()
        assert st["ativo"] is True and "Plantão" in st["motivo"]
        cliente.delete(f"/api/agente/excecoes/{r.json()['id']}", headers=H)
    finally:
        cliente.put("/api/agente/horarios", json=[{"dia_semana": d, "inicio": "00:00", "fim": "23:59"} for d in range(7)], headers=H)
        cliente.put("/api/agente/config", json={"agente_modo": "ligado"}, headers=H)


def test_rotina_desliga_e_manda_para_fila(cliente, rag):
    roteiro(([texto("Oi!")], "end_turn"), rag=rag)
    conv_id = simular(cliente, "5511922220000", "Olá", "Gil")
    assert esperar(lambda: autores(conv_id, "agente"))
    import asyncio

    asyncio.run(atendimento.rotina_periodica())  # registra o estado atual (ligado)
    cliente.put("/api/agente/config", json={"agente_modo": "desligado"}, headers=H)
    try:
        asyncio.run(atendimento.rotina_periodica())
        assert conversa(conv_id)[0] == "fila"
    finally:
        cliente.put("/api/agente/config", json={"agente_modo": "ligado"}, headers=H)


# ---------------------------------------------------------------- CRM e segurança
def test_crm_basico(cliente):
    c = cliente.post("/api/contatos", json={"nome": "Lead Novo", "telefone": "21 99999-0000"}, headers=H).json()
    n = cliente.post("/api/negocios", json={"titulo": "Plano Premium", "valor": 449.9, "contato_id": c["id"]}, headers=H)
    assert n.status_code == 200
    etapas = cliente.get("/api/funil").json()["etapas"]
    assert cliente.patch(f"/api/negocios/{n.json()['id']}", json={"etapa_id": etapas[2]["id"]}, headers=H).status_code == 200
    t = cliente.post("/api/tarefas", json={"titulo": "Ligar para o lead", "contato_id": c["id"]}, headers=H)
    assert t.status_code == 200
    assert cliente.patch(f"/api/tarefas/{t.json()['id']}", json={"concluida": True}, headers=H).json()["concluida"]
    csv = cliente.get("/api/contatos/exportar.csv").text
    assert "Lead Novo" in csv
    imp = cliente.post("/api/contatos/importar", headers=H,
                       files={"arquivo": ("c.csv", "nome,telefone,etiquetas\nZé,11911112222,VIP;Novo\n", "text/csv")})
    assert imp.json()["criados"] == 1
    r = cliente.get("/api/relatorios/resumo?dias=7").json()
    assert r["mensagens_agente"] >= 1 and r["mensagens_humanos"] >= 1
    assert any(a["acao"] == "conversa_assumida" for a in cliente.get("/api/auditoria").json())


def test_seguranca(cliente):
    assert cliente.post("/api/contatos", json={"nome": "Sem header"}).status_code == 403  # CSRF
    entrar(cliente, "maria@lavo.com", "senha-maria-1")
    try:
        assert cliente.put("/api/agente/config", json={"agente_modo": "desligado"}, headers=H).status_code == 403
        assert cliente.post("/api/usuarios", json={"nome": "X", "email": "x@x.com", "senha": "12345678"}, headers=H).status_code == 403
        assert cliente.get("/configuracoes", follow_redirects=False).status_code == 307
    finally:
        entrar(cliente, "admin@lavo.com", "senha-forte-1")
    cliente.post("/api/logout", headers=H)
    assert cliente.get("/api/conversas").status_code == 401
    assert cliente.post("/api/login", json={"email": "admin@lavo.com", "senha": "errada"}, headers=H).status_code == 401
    entrar(cliente, "admin@lavo.com", "senha-forte-1")
