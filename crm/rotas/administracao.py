"""Usuários, agente (liga/desliga programado), WhatsApp, relatórios e auditoria."""

from __future__ import annotations

import hmac
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import atendimento as at
from .. import serializar as s
from .. import whatsapp
from ..agenda import DIAS, estado_do_agente
from ..config import GATEWAY_TOKEN, WHATSAPP_SIMULADO
from ..db import obter_db
from ..eventos import barramento
from ..modelos import (
    PAPEIS,
    Auditoria,
    Conversa,
    ExcecaoAgente,
    HorarioAgente,
    Mensagem,
    Usuario,
    agora,
)
from ..preferencias import PADROES, ler_config, salvar_config
from ..seguranca import gerar_hash
from .base import admin, gestor, usuario_logado

rotas = APIRouter(prefix="/api", tags=["administração"])
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


# ---------------------------------------------------------------- usuários
class NovoUsuario(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    senha: str = Field(min_length=8)
    papel: str = "atendente"
    cor: str = "#2a78d6"


class EdicaoUsuario(BaseModel):
    nome: str | None = None
    papel: str | None = None
    ativo: bool | None = None
    cor: str | None = None
    senha: str | None = Field(None, min_length=8)


@rotas.get("/usuarios")
def usuarios(u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    return [s.usuario(x) for x in db.scalars(select(Usuario).order_by(Usuario.nome))]


@rotas.post("/usuarios")
def criar_usuario(d: NovoUsuario, u: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    if d.papel not in PAPEIS:
        raise HTTPException(400, "Papel inválido.")
    novo = Usuario(nome=d.nome.strip(), email=d.email.lower().strip(), senha_hash=gerar_hash(d.senha),
                   papel=d.papel, cor=d.cor)
    db.add(novo)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "E-mail já cadastrado.") from e
    at.auditar(db, u, "usuario_criado", "usuario", novo.id, papel=d.papel)
    db.commit()
    return s.usuario(novo)


@rotas.patch("/usuarios/{usuario_id}")
def editar_usuario(usuario_id: int, d: EdicaoUsuario, u: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    alvo = db.get(Usuario, usuario_id)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado.")
    if d.papel is not None and d.papel not in PAPEIS:
        raise HTTPException(400, "Papel inválido.")
    if alvo.id == u.id and (d.ativo is False or (d.papel and d.papel != "admin")):
        raise HTTPException(400, "Você não pode desativar nem rebaixar a si mesmo.")
    for campo in ("nome", "papel", "ativo", "cor"):
        valor = getattr(d, campo)
        if valor is not None:
            setattr(alvo, campo, valor)
    if d.senha:
        alvo.senha_hash = gerar_hash(d.senha)
    if d.senha or d.ativo is False:
        alvo.versao_sessao += 1  # derruba sessões abertas
    at.auditar(db, u, "usuario_editado", "usuario", alvo.id, **d.model_dump(exclude_unset=True, exclude={"senha"}))
    db.commit()
    return s.usuario(alvo)


# ---------------------------------------------------------------- agente: estado e programação
class ConfigAgente(BaseModel):
    agente_modo: str | None = Field(None, pattern="^(automatico|ligado|desligado)$")
    fuso_horario: str | None = None
    agente_nome: str | None = Field(None, max_length=60)
    espera_agrupar_s: int | None = Field(None, ge=0, le=60)
    devolver_ao_agente_min: int | None = Field(None, ge=0, le=10080)
    mensagem_fora_horario: str | None = Field(None, max_length=1000)
    mensagem_transferencia: str | None = Field(None, max_length=1000)


class Horario(BaseModel):
    dia_semana: int = Field(ge=0, le=6)
    inicio: str = Field(pattern=HHMM)
    fim: str = Field(pattern=HHMM)


class Excecao(BaseModel):
    descricao: str = Field(min_length=1, max_length=160)
    inicio: datetime
    fim: datetime
    agente_ativo: bool


def _estado_json(db: Session) -> dict:
    e = estado_do_agente(db)
    return {"ativo": e.ativo, "motivo": e.motivo, "modo": e.modo, "proxima_mudanca": s.iso(e.proxima_mudanca)}


@rotas.get("/agente/status")
def agente_status(u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    return _estado_json(db)


@rotas.get("/agente/config")
def agente_config(u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    cfg = ler_config(db)
    fuso = ZoneInfo(cfg["fuso_horario"])
    return {
        "config": cfg,
        "horarios": [{"id": h.id, "dia_semana": h.dia_semana, "inicio": h.inicio, "fim": h.fim}
                     for h in db.scalars(select(HorarioAgente).order_by(HorarioAgente.dia_semana, HorarioAgente.inicio))],
        "excecoes": [{"id": x.id, "descricao": x.descricao, "agente_ativo": x.agente_ativo,
                      "inicio": x.inicio.astimezone(fuso).isoformat(), "fim": x.fim.astimezone(fuso).isoformat()}
                     for x in db.scalars(select(ExcecaoAgente).where(ExcecaoAgente.fim > agora() - timedelta(days=30))
                                         .order_by(ExcecaoAgente.inicio))],
        "dias": DIAS,
        "estado": _estado_json(db),
    }


@rotas.put("/agente/config")
def salvar_agente_config(d: ConfigAgente, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    alteracoes = d.model_dump(exclude_unset=True, exclude_none=True)
    if "fuso_horario" in alteracoes:
        try:
            ZoneInfo(alteracoes["fuso_horario"])
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise HTTPException(400, "Fuso horário inválido.") from e
    salvar_config(db, alteracoes)
    at.auditar(db, u, "agente_config_alterada", **alteracoes)
    db.commit()
    barramento.publicar("agente_status", _estado_json(db))
    return _estado_json(db)


@rotas.put("/agente/horarios")
def salvar_horarios(horarios: list[Horario], u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    for h in horarios:
        if h.inicio == h.fim:
            raise HTTPException(400, f"{DIAS[h.dia_semana]}: início e fim iguais.")
    db.query(HorarioAgente).delete()
    for h in horarios:
        db.add(HorarioAgente(**h.model_dump()))
    at.auditar(db, u, "agente_horarios_alterados", total=len(horarios))
    db.commit()
    barramento.publicar("agente_status", _estado_json(db))
    return _estado_json(db)


@rotas.post("/agente/excecoes")
def criar_excecao(d: Excecao, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    fuso = ZoneInfo(ler_config(db)["fuso_horario"])
    inicio = d.inicio if d.inicio.tzinfo else d.inicio.replace(tzinfo=fuso)
    fim = d.fim if d.fim.tzinfo else d.fim.replace(tzinfo=fuso)
    if fim <= inicio:
        raise HTTPException(400, "O fim precisa ser depois do início.")
    x = ExcecaoAgente(descricao=d.descricao, inicio=inicio, fim=fim, agente_ativo=d.agente_ativo)
    db.add(x)
    db.flush()
    at.auditar(db, u, "agente_excecao_criada", "excecao", x.id, descricao=d.descricao, agente_ativo=d.agente_ativo)
    db.commit()
    barramento.publicar("agente_status", _estado_json(db))
    return {"id": x.id}


@rotas.delete("/agente/excecoes/{excecao_id}")
def excluir_excecao(excecao_id: int, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    x = db.get(ExcecaoAgente, excecao_id)
    if x:
        at.auditar(db, u, "agente_excecao_excluida", "excecao", x.id, descricao=x.descricao)
        db.delete(x)
        db.commit()
    barramento.publicar("agente_status", _estado_json(db))
    return {"ok": True}


# ---------------------------------------------------------------- WhatsApp
class Simulacao(BaseModel):
    telefone: str = Field(min_length=8, max_length=20)
    nome: str | None = None
    texto: str = Field(min_length=1, max_length=4000)


@rotas.get("/whatsapp/status")
async def wpp_status(u: Usuario = Depends(usuario_logado)):
    return await whatsapp.status()


@rotas.post("/whatsapp/conectar")
async def wpp_conectar(u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    try:
        r = await whatsapp.conectar()
    except whatsapp.ErroWhatsapp as e:
        raise HTTPException(502, str(e)) from e
    at.auditar(db, u, "whatsapp_conectar")
    db.commit()
    return r


@rotas.post("/whatsapp/desconectar")
async def wpp_desconectar(u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    try:
        r = await whatsapp.desconectar()
    except whatsapp.ErroWhatsapp as e:
        raise HTTPException(502, str(e)) from e
    at.auditar(db, u, "whatsapp_desconectado")
    db.commit()
    return r


@rotas.post("/whatsapp/webhook", include_in_schema=False)
async def wpp_webhook(request: Request, x_gateway_token: str | None = Header(default=None)):
    """Chamado pelo gateway (whatsapp-gateway/) a cada mensagem ou mudança de status."""
    if not GATEWAY_TOKEN or not hmac.compare_digest(x_gateway_token or "", GATEWAY_TOKEN):
        raise HTTPException(401, "token inválido")
    evento = await request.json()
    if evento.get("tipo") == "status":
        whatsapp.ultimo_status.update({k: evento.get(k) for k in ("estado", "qr", "numero", "nome", "erro")})
        barramento.publicar("whatsapp", whatsapp.ultimo_status)
    elif evento.get("tipo") == "mensagem":
        await at.receber_do_whatsapp(evento)
    return {"ok": True}


@rotas.post("/whatsapp/simular")
async def wpp_simular(d: Simulacao, u: Usuario = Depends(gestor)):
    """Só no modo simulado: finge que um contato mandou uma mensagem."""
    if not WHATSAPP_SIMULADO:
        raise HTTPException(409, "Simulador disponível só no modo simulado.")
    tel = at.so_digitos(d.telefone)
    conv_id = await at.receber_do_whatsapp({
        "tipo": "mensagem", "id": f"simin-{datetime.now().timestamp()}", "jid": whatsapp.jid_de_telefone(tel),
        "telefone": tel, "nome": d.nome, "de_mim": False, "texto": d.texto, "midia": None})
    return {"conversa_id": conv_id}


# ---------------------------------------------------------------- relatórios
@rotas.get("/relatorios/resumo")
def resumo(dias: int = 7, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    dias = min(max(dias, 1), 90)
    fuso = ZoneInfo(ler_config(db)["fuso_horario"])
    inicio = agora() - timedelta(days=dias)
    convs = list(db.scalars(select(Conversa).where(Conversa.criada_em >= inicio)))
    msgs = list(db.scalars(select(Mensagem).where(Mensagem.criada_em >= inicio, Mensagem.direcao == "saida")))
    ids_com_humano = {m.conversa_id for m in msgs if m.autor_tipo == "humano"}
    ids_com_agente = {m.conversa_id for m in msgs if m.autor_tipo == "agente"}
    resolvidas = [c for c in convs if c.status == "resolvida"]
    tempos = [(c.primeira_resposta_em - c.criada_em).total_seconds() for c in convs if c.primeira_resposta_em]

    por_dia: dict[str, dict[str, int]] = {}
    for i in range(dias):
        d = (agora() - timedelta(days=dias - 1 - i)).astimezone(fuso).date().isoformat()
        por_dia[d] = {"agente": 0, "humano": 0}
    for m in msgs:
        d = m.criada_em.astimezone(fuso).date().isoformat()
        if d in por_dia and m.autor_tipo in ("agente", "humano"):
            por_dia[d][m.autor_tipo] += 1

    por_usuario: dict[str, dict] = {}
    for m in msgs:
        if m.autor_tipo != "humano":
            continue
        chave = m.usuario.nome if m.usuario else "Celular da empresa"
        item = por_usuario.setdefault(chave, {"nome": chave, "mensagens": 0, "conversas": set(), "resolvidas": 0})
        item["mensagens"] += 1
        item["conversas"].add(m.conversa_id)
    for c in resolvidas:
        if c.resolvida_por_id:
            nome = db.get(Usuario, c.resolvida_por_id).nome
            por_usuario.setdefault(nome, {"nome": nome, "mensagens": 0, "conversas": set(), "resolvidas": 0})
            por_usuario[nome]["resolvidas"] += 1

    return {
        "dias": dias,
        "conversas_novas": len(convs),
        "conversas_resolvidas": len(resolvidas),
        # atendidas só pelo agente: o agente respondeu e nenhum humano precisou entrar
        "sem_humano": sum(1 for c in convs if c.id in ids_com_agente and c.id not in ids_com_humano),
        "com_humano": len({c.id for c in convs} & ids_com_humano),
        "mensagens_agente": sum(1 for m in msgs if m.autor_tipo == "agente"),
        "mensagens_humanos": sum(1 for m in msgs if m.autor_tipo == "humano"),
        "tempo_primeira_resposta_s": round(sum(tempos) / len(tempos)) if tempos else None,
        "custo_agente_usd": round(sum(m.custo_usd or 0 for m in msgs), 4),
        "fila_agora": db.scalar(select(func.count()).where(Conversa.status == "aberta", Conversa.modo == "fila")),
        "por_dia": [{"dia": d, **v} for d, v in por_dia.items()],
        "por_usuario": sorted(({**v, "conversas": len(v["conversas"])} for v in por_usuario.values()),
                              key=lambda x: -x["mensagens"]),
    }


# ---------------------------------------------------------------- auditoria
@rotas.get("/auditoria")
def auditoria(acao: str = "", usuario_id: int | None = None, limite: int = 200,
              u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    q = select(Auditoria)
    if acao:
        q = q.where(Auditoria.acao.ilike(f"%{re.sub(r'[%_]', '', acao)}%"))
    if usuario_id:
        q = q.where(Auditoria.usuario_id == usuario_id)
    return [{"id": a.id, "acao": a.acao, "entidade": a.entidade, "entidade_id": a.entidade_id, "detalhes": a.detalhes,
             "usuario": a.usuario.nome if a.usuario else "Sistema", "criado_em": s.iso(a.criado_em)}
            for a in db.scalars(q.order_by(Auditoria.id.desc()).limit(min(limite, 1000)))]


__all__ = ["rotas", "PADROES"]
