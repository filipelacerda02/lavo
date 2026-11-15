"""Caixa de entrada: conversas, mensagens e ações de atendimento."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import atendimento as at
from .. import serializar as s
from ..db import obter_db
from ..eventos import barramento
from ..modelos import (Contato, Conversa, Equipe, Etiqueta, Mensagem, MensagemAgendada, Usuario, agora,
                       contato_etiquetas)
from ..preferencias import PRIORIDADES, ler_config
from ..recursos import distribuir_fila, notificar, solicitar_csat
from .base import usuario_logado

rotas = APIRouter(prefix="/api/conversas", tags=["conversas"])


class Texto(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)


class Transferencia(BaseModel):
    usuario_id: int | None = None
    equipe_id: int | None = None  # sem usuário: vai para a fila da equipe


class Edicao(BaseModel):
    prioridade: str | None = Field(None, pattern="^(baixa|media|alta|urgente)$")
    equipe_id: int | None = None


class Agendamento(BaseModel):
    texto: str = Field("", max_length=4000)
    enviar_em: datetime
    modelo_id: int | None = None      # usado se a janela de 24h estiver fechada na hora do envio
    parametros: list[str] = []


def _conversa(db: Session, conversa_id: int) -> Conversa:
    conv = db.get(Conversa, conversa_id)
    if not conv:
        raise HTTPException(404, "Conversa não encontrada.")
    return conv


def _ultimas(db: Session, ids: list[int]) -> dict[int, Mensagem]:
    if not ids:
        return {}
    sub = (select(Mensagem.conversa_id, func.max(Mensagem.id).label("mid"))
           .where(Mensagem.conversa_id.in_(ids), Mensagem.direcao != "interna")
           .group_by(Mensagem.conversa_id).subquery())
    return {m.conversa_id: m for m in db.scalars(select(Mensagem).join(sub, Mensagem.id == sub.c.mid))}


@rotas.get("")
def listar(filtro: str = "abertas", busca: str = "", etiqueta_id: int | None = None,
           equipe_id: int | None = None, prioridade: str | None = None, limite: int = Query(100, le=300), u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    q = select(Conversa).join(Contato)
    filtros = {
        "abertas": Conversa.status == "aberta",
        "minhas": (Conversa.status == "aberta") & (Conversa.modo == "humano") & (Conversa.atendente_id == u.id),
        "fila": (Conversa.status == "aberta") & (Conversa.modo == "fila"),
        "agente": (Conversa.status == "aberta") & (Conversa.modo == "agente"),
        "humano": (Conversa.status == "aberta") & (Conversa.modo == "humano"),
        "resolvidas": Conversa.status == "resolvida",
        "todas": None,
    }
    if filtro not in filtros:
        raise HTTPException(400, "Filtro inválido.")
    if filtros[filtro] is not None:
        q = q.where(filtros[filtro])
    if busca:
        termo = f"%{busca.strip()}%"
        q = q.where(or_(Contato.nome.ilike(termo), Contato.telefone.ilike(termo), Contato.email.ilike(termo)))
    if etiqueta_id:
        q = q.join(contato_etiquetas, contato_etiquetas.c.contato_id == Contato.id).where(
            contato_etiquetas.c.etiqueta_id == etiqueta_id)
    if equipe_id:
        q = q.where(Conversa.equipe_id == equipe_id)
    if prioridade:
        q = q.where(Conversa.prioridade == prioridade)
    convs = list(db.scalars(q.order_by(Conversa.ultima_mensagem_em.desc()).limit(limite)).unique())
    if filtro == "fila":  # fila: mais urgente e mais antiga primeiro
        convs.sort(key=lambda c: (-PRIORIDADES.index(c.prioridade or "media"), c.modo_desde))
    ultimas = _ultimas(db, [c.id for c in convs])
    cfg = ler_config(db)
    nome_agente = cfg["agente_nome"]
    contagem = dict(db.execute(select(Conversa.modo, func.count()).where(Conversa.status == "aberta")
                               .group_by(Conversa.modo)).all())
    minhas = db.scalar(select(func.count()).where(Conversa.status == "aberta", Conversa.modo == "humano",
                                                  Conversa.atendente_id == u.id))
    return {"conversas": [s.conversa(c, ultimas.get(c.id), nome_agente, cfg) for c in convs],
            "contagem": {"agente": contagem.get("agente", 0), "fila": contagem.get("fila", 0),
                         "humano": contagem.get("humano", 0), "minhas": minhas}}


@rotas.get("/{conversa_id}")
def detalhe(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    cfg = ler_config(db)
    nome_agente = cfg["agente_nome"]
    msgs = db.scalars(select(Mensagem).where(Mensagem.conversa_id == conv.id).order_by(Mensagem.id))
    anteriores = db.scalars(select(Conversa).where(Conversa.contato_id == conv.contato_id, Conversa.id != conv.id)
                            .order_by(Conversa.id.desc()).limit(10))
    agendadas = db.scalars(select(MensagemAgendada).where(MensagemAgendada.conversa_id == conv.id,
                                                           MensagemAgendada.status.in_(["pendente", "erro"]))
                           .order_by(MensagemAgendada.enviar_em))
    return {"conversa": s.conversa(conv, None, nome_agente, cfg),
            "agendadas": [s.agendada(a) for a in agendadas],
            "mensagens": [s.mensagem(m, nome_agente, conv.contato) for m in msgs],
            "anteriores": [{"id": c.id, "status": c.status, "criada_em": s.iso(c.criada_em)} for c in anteriores]}


@rotas.post("/{conversa_id}/lida")
def marcar_lida(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    conv.nao_lidas = 0
    db.commit()
    at.publicar_conversa(conv.id)
    return {"ok": True}


def _executar(db: Session, conv: Conversa, acao) -> dict:
    try:
        acao()
    except at.ErroAtendimento as e:
        db.rollback()
        raise HTTPException(e.status, str(e)) from e
    db.commit()
    at.publicar_conversa(conv.id)
    return {"ok": True}


@rotas.post("/{conversa_id}/mensagens")
async def enviar(conversa_id: int, dados: Texto, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    u = db.merge(u)
    try:
        m = await at.enviar_humano(db, conv, u, dados.texto)
    except at.ErroAtendimento as e:
        db.rollback()
        raise HTTPException(e.status, str(e)) from e
    return s.mensagem(m, ler_config(db)["agente_nome"], conv.contato)


@rotas.post("/{conversa_id}/notas")
def nota(conversa_id: int, dados: Texto, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    m = at.nota_interna(db, conv, db.merge(u), dados.texto)
    return s.mensagem(m, ler_config(db)["agente_nome"], conv.contato)


@rotas.post("/{conversa_id}/assumir")
def assumir(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    return _executar(db, conv, lambda: at.assumir(db, conv, db.merge(u)))


@rotas.post("/{conversa_id}/devolver-agente")
def devolver(conversa_id: int, forcar: bool = False, u: Usuario = Depends(usuario_logado),
             db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    r = _executar(db, conv, lambda: at.devolver_ao_agente(db, conv, db.merge(u), forcar=forcar))
    pendente = db.scalar(select(Mensagem.id).where(Mensagem.conversa_id == conv.id, Mensagem.direcao == "entrada",
                                                   Mensagem.processada_pelo_agente.is_(False)))
    if pendente:
        at.agendar_agente(conv.id, espera=1)
    return r


@rotas.post("/{conversa_id}/fila")
async def para_fila(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    r = _executar(db, conv, lambda: at.enviar_para_fila(db, conv, db.merge(u)))
    await asyncio.to_thread(distribuir_fila, {conv.id: u.id})
    return r


@rotas.post("/{conversa_id}/transferir")
async def transferir(conversa_id: int, dados: Transferencia, u: Usuario = Depends(usuario_logado),
                     db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    if dados.usuario_id:
        destino = db.get(Usuario, dados.usuario_id)
        if not destino:
            raise HTTPException(404, "Colaborador não encontrado.")
        if dados.equipe_id is not None:
            conv.equipe_id = dados.equipe_id
        r = _executar(db, conv, lambda: at.transferir(db, conv, db.merge(u), destino))
        notificar("atribuida", f"{u.nome} transferiu uma conversa para você: {conv.contato.nome}", conv.id, destino.id)
        return r
    equipe = db.get(Equipe, dados.equipe_id) if dados.equipe_id else None
    if not equipe:
        raise HTTPException(400, "Informe um colaborador ou uma equipe.")
    conv.equipe_id = equipe.id
    r = _executar(db, conv, lambda: at.enviar_para_fila(db, conv, db.merge(u), motivo=f"Transferida para a equipe {equipe.nome}"))
    await asyncio.to_thread(distribuir_fila)
    return r


@rotas.patch("/{conversa_id}")
def editar(conversa_id: int, dados: Edicao, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    mudancas = dados.model_dump(exclude_unset=True)
    textos = []
    if "prioridade" in mudancas and mudancas["prioridade"] != conv.prioridade:
        conv.prioridade = mudancas["prioridade"]
        textos.append(f"prioridade → {conv.prioridade}")
    if "equipe_id" in mudancas and mudancas["equipe_id"] != conv.equipe_id:
        equipe = db.get(Equipe, mudancas["equipe_id"]) if mudancas["equipe_id"] else None
        conv.equipe_id = equipe.id if equipe else None
        textos.append(f"equipe → {equipe.nome if equipe else 'nenhuma'}")
    if textos:
        at.evento_sistema(db, conv, f"✏️ {u.nome} alterou " + ", ".join(textos) + ".", u)
        at.auditar(db, u, "conversa_editada", "conversa", conv.id, **mudancas)
    db.commit()
    at.publicar_conversa(conv.id)
    return {"ok": True}


@rotas.post("/{conversa_id}/resolver")
async def resolver(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    r = _executar(db, conv, lambda: at.resolver(db, conv, db.merge(u)))
    await solicitar_csat(conv.id)
    return r


# ---------------------------------------------------------------- mensagens agendadas
@rotas.post("/{conversa_id}/agendadas")
def agendar(conversa_id: int, dados: Agendamento, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    quando = dados.enviar_em if dados.enviar_em.tzinfo else dados.enviar_em.replace(
        tzinfo=ZoneInfo(ler_config(db)["fuso_horario"]))
    if quando <= agora():
        raise HTTPException(400, "Escolha um horário no futuro.")
    if not dados.texto.strip() and not dados.modelo_id:
        raise HTTPException(400, "Escreva a mensagem ou escolha um modelo.")
    texto = dados.texto.strip()
    if dados.modelo_id:
        from ..campanhas import renderizar, validar_parametros
        from ..modelos import ModeloMensagem

        modelo = db.get(ModeloMensagem, dados.modelo_id)
        if not modelo:
            raise HTTPException(404, "Modelo não encontrado.")
        try:
            validar_parametros(modelo, dados.parametros, None)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        texto = texto or renderizar(modelo, dados.parametros)
    a = MensagemAgendada(conversa_id=conv.id, texto=texto, enviar_em=quando, criada_por_id=u.id,
                         modelo_id=dados.modelo_id, parametros=dados.parametros or None)
    db.add(a)
    db.flush()
    at.evento_sistema(db, conv, f"⏰ {u.nome} agendou uma mensagem para {quando.astimezone(ZoneInfo(ler_config(db)['fuso_horario'])):%d/%m %H:%M}.", u)
    at.auditar(db, u, "mensagem_agendada", "conversa", conv.id, agendada_id=a.id)
    db.commit()
    barramento.publicar("mensagem", {"conversa_id": conv.id})
    return s.agendada(a)


@rotas.delete("/agendadas/{agendada_id}")
def cancelar_agendada(agendada_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    a = db.get(MensagemAgendada, agendada_id)
    if not a or a.status != "pendente":
        raise HTTPException(404, "Agendamento não encontrado ou já enviado.")
    a.status = "cancelada"
    at.auditar(db, u, "agendamento_cancelado", "conversa", a.conversa_id, agendada_id=a.id)
    db.commit()
    barramento.publicar("mensagem", {"conversa_id": a.conversa_id})
    return {"ok": True}


@rotas.post("/{conversa_id}/reabrir")
def reabrir(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    return _executar(db, conv, lambda: at.reabrir(db, conv, db.merge(u)))


__all__ = ["rotas", "Etiqueta"]
