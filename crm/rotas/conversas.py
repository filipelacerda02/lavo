"""Caixa de entrada: conversas, mensagens e ações de atendimento."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import atendimento as at
from .. import serializar as s
from ..db import obter_db
from ..modelos import Contato, Conversa, Etiqueta, Mensagem, Usuario, contato_etiquetas
from ..preferencias import ler_config
from .base import usuario_logado

rotas = APIRouter(prefix="/api/conversas", tags=["conversas"])


class Texto(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)


class Transferencia(BaseModel):
    usuario_id: int


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
           limite: int = Query(100, le=300), u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
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
    convs = list(db.scalars(q.order_by(Conversa.ultima_mensagem_em.desc()).limit(limite)).unique())
    ultimas = _ultimas(db, [c.id for c in convs])
    nome_agente = ler_config(db)["agente_nome"]
    contagem = dict(db.execute(select(Conversa.modo, func.count()).where(Conversa.status == "aberta")
                               .group_by(Conversa.modo)).all())
    minhas = db.scalar(select(func.count()).where(Conversa.status == "aberta", Conversa.modo == "humano",
                                                  Conversa.atendente_id == u.id))
    return {"conversas": [s.conversa(c, ultimas.get(c.id), nome_agente) for c in convs],
            "contagem": {"agente": contagem.get("agente", 0), "fila": contagem.get("fila", 0),
                         "humano": contagem.get("humano", 0), "minhas": minhas}}


@rotas.get("/{conversa_id}")
def detalhe(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    nome_agente = ler_config(db)["agente_nome"]
    msgs = db.scalars(select(Mensagem).where(Mensagem.conversa_id == conv.id).order_by(Mensagem.id))
    anteriores = db.scalars(select(Conversa).where(Conversa.contato_id == conv.contato_id, Conversa.id != conv.id)
                            .order_by(Conversa.id.desc()).limit(10))
    return {"conversa": s.conversa(conv, None, nome_agente),
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
def para_fila(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    return _executar(db, conv, lambda: at.enviar_para_fila(db, conv, db.merge(u)))


@rotas.post("/{conversa_id}/transferir")
def transferir(conversa_id: int, dados: Transferencia, u: Usuario = Depends(usuario_logado),
               db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    destino = db.get(Usuario, dados.usuario_id)
    if not destino:
        raise HTTPException(404, "Colaborador não encontrado.")
    return _executar(db, conv, lambda: at.transferir(db, conv, db.merge(u), destino))


@rotas.post("/{conversa_id}/resolver")
def resolver(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    return _executar(db, conv, lambda: at.resolver(db, conv, db.merge(u)))


@rotas.post("/{conversa_id}/reabrir")
def reabrir(conversa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = _conversa(db, conversa_id)
    return _executar(db, conv, lambda: at.reabrir(db, conv, db.merge(u)))


__all__ = ["rotas", "Etiqueta"]
