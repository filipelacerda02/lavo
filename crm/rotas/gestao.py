"""Funil de vendas (negócios), tarefas e respostas rápidas."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import atendimento as at
from .. import serializar as s
from ..db import obter_db
from ..eventos import barramento
from ..modelos import EtapaFunil, Negocio, RespostaRapida, Tarefa, Usuario, agora
from .base import gestor, usuario_logado

rotas = APIRouter(prefix="/api", tags=["gestão"])


# ---------------------------------------------------------------- funil
class DadosEtapa(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    cor: str = "#2a78d6"
    ordem: int | None = None


class DadosNegocio(BaseModel):
    titulo: str | None = Field(None, max_length=160)
    contato_id: int | None = None
    etapa_id: int | None = None
    valor: float | None = None
    responsavel_id: int | None = None
    status: str | None = Field(None, pattern="^(aberto|ganho|perdido)$")
    previsao_fechamento: str | None = None
    observacoes: str | None = None
    ordem: int | None = None


@rotas.get("/funil")
def funil(u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    etapas = db.scalars(select(EtapaFunil).order_by(EtapaFunil.ordem, EtapaFunil.id))
    negocios = db.scalars(select(Negocio).order_by(Negocio.ordem, Negocio.id))
    return {"etapas": [{"id": e.id, "nome": e.nome, "cor": e.cor, "ordem": e.ordem} for e in etapas],
            "negocios": [s.negocio(n) for n in negocios]}


@rotas.post("/funil/etapas")
def criar_etapa(d: DadosEtapa, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    ordem = d.ordem if d.ordem is not None else (db.scalar(select(func.max(EtapaFunil.ordem))) or 0) + 1
    e = EtapaFunil(nome=d.nome, cor=d.cor, ordem=ordem)
    db.add(e)
    db.commit()
    return {"id": e.id}


@rotas.patch("/funil/etapas/{etapa_id}")
def editar_etapa(etapa_id: int, d: DadosEtapa, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    e = db.get(EtapaFunil, etapa_id) or _404()
    e.nome, e.cor = d.nome, d.cor
    if d.ordem is not None:
        e.ordem = d.ordem
    db.commit()
    return {"ok": True}


@rotas.delete("/funil/etapas/{etapa_id}")
def excluir_etapa(etapa_id: int, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    e = db.get(EtapaFunil, etapa_id) or _404()
    if db.scalar(select(func.count()).where(Negocio.etapa_id == e.id)):
        raise HTTPException(409, "Mova os negócios desta etapa antes de excluí-la.")
    db.delete(e)
    db.commit()
    return {"ok": True}


@rotas.post("/negocios")
def criar_negocio(d: DadosNegocio, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    if not d.titulo:
        raise HTTPException(400, "Informe o título.")
    etapa_id = d.etapa_id or db.scalar(select(EtapaFunil.id).order_by(EtapaFunil.ordem).limit(1))
    if not etapa_id:
        raise HTTPException(400, "Crie uma etapa do funil primeiro.")
    n = Negocio(titulo=d.titulo, contato_id=d.contato_id, etapa_id=etapa_id, valor=d.valor or 0,
                responsavel_id=d.responsavel_id or u.id, previsao_fechamento=d.previsao_fechamento,
                observacoes=d.observacoes or "")
    db.add(n)
    db.flush()
    at.auditar(db, u, "negocio_criado", "negocio", n.id)
    db.commit()
    barramento.publicar("funil", {"id": n.id})
    return s.negocio(n)


@rotas.patch("/negocios/{negocio_id}")
def editar_negocio(negocio_id: int, d: DadosNegocio, u: Usuario = Depends(usuario_logado),
                   db: Session = Depends(obter_db)):
    n = db.get(Negocio, negocio_id) or _404()
    alteracoes = d.model_dump(exclude_unset=True)
    for k, v in alteracoes.items():
        setattr(n, k, v)
    at.auditar(db, u, "negocio_editado", "negocio", n.id, **{k: v for k, v in alteracoes.items()
                                                              if k in ("etapa_id", "status", "valor")})
    db.commit()
    barramento.publicar("funil", {"id": n.id})
    return s.negocio(n)


@rotas.delete("/negocios/{negocio_id}")
def excluir_negocio(negocio_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    n = db.get(Negocio, negocio_id) or _404()
    at.auditar(db, u, "negocio_excluido", "negocio", n.id, titulo=n.titulo)
    db.delete(n)
    db.commit()
    barramento.publicar("funil", {"id": negocio_id})
    return {"ok": True}


# ---------------------------------------------------------------- tarefas
class DadosTarefa(BaseModel):
    titulo: str | None = Field(None, max_length=200)
    descricao: str | None = None
    contato_id: int | None = None
    conversa_id: int | None = None
    responsavel_id: int | None = None
    prioridade: str | None = Field(None, pattern="^(baixa|media|alta)$")
    vencimento: datetime | None = None
    concluida: bool | None = None


@rotas.get("/tarefas")
def tarefas(filtro: str = "pendentes", u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    q = select(Tarefa)
    if filtro == "pendentes":
        q = q.where(Tarefa.concluida.is_(False))
    elif filtro == "minhas":
        q = q.where(Tarefa.concluida.is_(False), Tarefa.responsavel_id == u.id)
    elif filtro == "atrasadas":
        q = q.where(Tarefa.concluida.is_(False), Tarefa.vencimento < agora())
    elif filtro == "sem_responsavel":
        q = q.where(Tarefa.concluida.is_(False), Tarefa.responsavel_id.is_(None))
    elif filtro == "concluidas":
        q = q.where(Tarefa.concluida.is_(True))
    itens = db.scalars(q.order_by(Tarefa.vencimento.is_(None), Tarefa.vencimento, Tarefa.id.desc()).limit(500))
    return [s.tarefa(t) for t in itens]


@rotas.post("/tarefas")
def criar_tarefa(d: DadosTarefa, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    if not d.titulo:
        raise HTTPException(400, "Informe o título.")
    t = Tarefa(**d.model_dump(exclude_unset=True, exclude={"concluida"}), criada_por_id=u.id)
    t.responsavel_id = t.responsavel_id or u.id
    db.add(t)
    db.flush()
    at.auditar(db, u, "tarefa_criada", "tarefa", t.id)
    db.commit()
    barramento.publicar("tarefa", {"id": t.id})
    return s.tarefa(t)


@rotas.patch("/tarefas/{tarefa_id}")
def editar_tarefa(tarefa_id: int, d: DadosTarefa, u: Usuario = Depends(usuario_logado),
                  db: Session = Depends(obter_db)):
    t = db.get(Tarefa, tarefa_id) or _404()
    alteracoes = d.model_dump(exclude_unset=True)
    for k, v in alteracoes.items():
        setattr(t, k, v)
    if "concluida" in alteracoes:
        t.concluida_em = agora() if t.concluida else None
        at.auditar(db, u, "tarefa_concluida" if t.concluida else "tarefa_reaberta", "tarefa", t.id)
    db.commit()
    barramento.publicar("tarefa", {"id": t.id})
    return s.tarefa(t)


@rotas.delete("/tarefas/{tarefa_id}")
def excluir_tarefa(tarefa_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    t = db.get(Tarefa, tarefa_id) or _404()
    db.delete(t)
    db.commit()
    barramento.publicar("tarefa", {"id": tarefa_id})
    return {"ok": True}


# ---------------------------------------------------------------- respostas rápidas
class DadosResposta(BaseModel):
    atalho: str = Field(min_length=1, max_length=40, pattern=r"^[\w-]+$")
    texto: str = Field(min_length=1)


@rotas.get("/respostas-rapidas")
def respostas(u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    return [{"id": r.id, "atalho": r.atalho, "texto": r.texto}
            for r in db.scalars(select(RespostaRapida).order_by(RespostaRapida.atalho))]


@rotas.post("/respostas-rapidas")
def criar_resposta(d: DadosResposta, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    r = RespostaRapida(atalho=d.atalho, texto=d.texto)
    db.add(r)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "Atalho já existe.") from e
    return {"id": r.id}


@rotas.delete("/respostas-rapidas/{resposta_id}")
def excluir_resposta(resposta_id: int, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    r = db.get(RespostaRapida, resposta_id)
    if r:
        db.delete(r)
        db.commit()
    return {"ok": True}


def _404():
    raise HTTPException(404, "Não encontrado.")
