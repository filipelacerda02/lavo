"""Contatos, etiquetas, importação/exportação CSV."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import atendimento as at
from .. import serializar as s
from ..db import obter_db
from ..modelos import Contato, Conversa, Etiqueta, Negocio, Tarefa, Usuario, contato_etiquetas
from .base import admin, gestor, usuario_logado

rotas = APIRouter(prefix="/api", tags=["contatos"])


class DadosContato(BaseModel):
    nome: str | None = Field(None, max_length=160)
    telefone: str | None = None
    email: str | None = None
    empresa: str | None = None
    origem: str | None = None
    observacoes: str | None = None
    cliente_externo_id: str | None = None
    agente_bloqueado: bool | None = None
    responsavel_id: int | None = None
    etiqueta_ids: list[int] | None = None


class DadosEtiqueta(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    cor: str = "#6250d6"


class Mensagem(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)


def _telefone(valor: str | None) -> str | None:
    digitos = at.so_digitos(valor)
    if not digitos:
        return None
    if len(digitos) in (10, 11):  # número brasileiro sem DDI
        digitos = "55" + digitos
    return digitos


def _aplicar(db: Session, c: Contato, dados: DadosContato) -> None:
    campos = dados.model_dump(exclude_unset=True)
    if "telefone" in campos:
        c.telefone = _telefone(campos.pop("telefone"))  # o jid real chega na primeira mensagem
    ids = campos.pop("etiqueta_ids", None)
    if ids is not None:
        c.etiquetas = list(db.scalars(select(Etiqueta).where(Etiqueta.id.in_(ids))))
    for k, v in campos.items():
        setattr(c, k, v.strip() if isinstance(v, str) else v)


def _contato(db: Session, contato_id: int) -> Contato:
    c = db.get(Contato, contato_id)
    if not c:
        raise HTTPException(404, "Contato não encontrado.")
    return c


@rotas.get("/contatos")
def listar(busca: str = "", etiqueta_id: int | None = None, pagina: int = 1, por_pagina: int = 50,
           u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    q = select(Contato)
    if busca:
        t = f"%{busca.strip()}%"
        q = q.where(or_(Contato.nome.ilike(t), Contato.telefone.ilike(t), Contato.email.ilike(t),
                        Contato.empresa.ilike(t)))
    if etiqueta_id:
        q = q.join(contato_etiquetas).where(contato_etiquetas.c.etiqueta_id == etiqueta_id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    por_pagina = min(max(por_pagina, 1), 200)
    itens = db.scalars(q.order_by(Contato.ultima_interacao.desc().nullslast(), Contato.id.desc())
                       .offset((max(pagina, 1) - 1) * por_pagina).limit(por_pagina)).unique()
    return {"total": total, "contatos": [s.contato(c) for c in itens]}


@rotas.post("/contatos")
def criar(dados: DadosContato, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    c = Contato(origem="manual")
    _aplicar(db, c, dados)
    if not (c.nome or c.telefone):
        raise HTTPException(400, "Informe nome ou telefone.")
    db.add(c)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "Já existe um contato com este telefone.") from e
    at.auditar(db, u, "contato_criado", "contato", c.id)
    db.commit()
    return s.contato(c)


@rotas.get("/contatos/exportar.csv")
def exportar(u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    saida = io.StringIO()
    w = csv.writer(saida)
    w.writerow(["nome", "telefone", "email", "empresa", "origem", "etiquetas", "observacoes", "criado_em"])
    for c in db.scalars(select(Contato).order_by(Contato.id)).unique():
        w.writerow([c.nome, c.telefone or "", c.email or "", c.empresa or "", c.origem,
                    ";".join(e.nome for e in c.etiquetas), c.observacoes, s.iso(c.criado_em)])
    at.auditar(db, u, "contatos_exportados")
    db.commit()
    return StreamingResponse(iter([saida.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=contatos.csv"})


@rotas.post("/contatos/importar")
async def importar(arquivo: UploadFile = File(...), u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    """CSV com cabeçalho: nome, telefone, email, empresa, etiquetas (separadas por ;), observacoes."""
    conteudo = (await arquivo.read()).decode("utf-8-sig", errors="replace")
    criados = atualizados = ignorados = 0
    etiquetas = {e.nome.lower(): e for e in db.scalars(select(Etiqueta))}
    for linha in csv.DictReader(io.StringIO(conteudo)):
        linha = {(k or "").strip().lower(): (v or "").strip() for k, v in linha.items()}
        tel = _telefone(linha.get("telefone"))
        if not (tel or linha.get("nome")):
            ignorados += 1
            continue
        c = db.scalar(select(Contato).where(Contato.telefone == tel)) if tel else None
        if c:
            atualizados += 1
        else:
            c = Contato(telefone=tel, origem="importacao")
            db.add(c)
            criados += 1
        for campo in ("nome", "email", "empresa", "observacoes"):
            if linha.get(campo):
                setattr(c, campo, linha[campo])
        for nome in filter(None, (linha.get("etiquetas") or "").split(";")):
            e = etiquetas.get(nome.strip().lower())
            if not e:
                e = etiquetas[nome.strip().lower()] = Etiqueta(nome=nome.strip())
                db.add(e)
            if e not in c.etiquetas:
                c.etiquetas.append(e)
        db.flush()
    at.auditar(db, u, "contatos_importados", criados=criados, atualizados=atualizados)
    db.commit()
    return {"criados": criados, "atualizados": atualizados, "ignorados": ignorados}


@rotas.get("/contatos/{contato_id}")
def detalhe(contato_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    c = _contato(db, contato_id)
    conversas = db.scalars(select(Conversa).where(Conversa.contato_id == c.id).order_by(Conversa.id.desc()).limit(20))
    negocios = db.scalars(select(Negocio).where(Negocio.contato_id == c.id).order_by(Negocio.id.desc()))
    tarefas = db.scalars(select(Tarefa).where(Tarefa.contato_id == c.id).order_by(Tarefa.concluida, Tarefa.vencimento))
    return {"contato": s.contato(c),
            "conversas": [{"id": cv.id, "status": cv.status, "modo": cv.modo, "criada_em": s.iso(cv.criada_em)}
                          for cv in conversas],
            "negocios": [s.negocio(n) for n in negocios], "tarefas": [s.tarefa(t) for t in tarefas]}


@rotas.patch("/contatos/{contato_id}")
def editar(contato_id: int, dados: DadosContato, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    c = _contato(db, contato_id)
    _aplicar(db, c, dados)
    try:
        at.auditar(db, u, "contato_editado", "contato", c.id, campos=list(dados.model_dump(exclude_unset=True)))
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "Já existe um contato com este telefone.") from e
    at.barramento.publicar("contato", {"id": c.id})
    return s.contato(c)


@rotas.delete("/contatos/{contato_id}")
def excluir(contato_id: int, u: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    c = _contato(db, contato_id)
    at.auditar(db, u, "contato_excluido", "contato", c.id, nome=c.nome, telefone=c.telefone)
    db.delete(c)
    db.commit()
    return {"ok": True}


@rotas.post("/contatos/{contato_id}/conversa")
async def iniciar(contato_id: int, dados: Mensagem, u: Usuario = Depends(usuario_logado),
                  db: Session = Depends(obter_db)):
    c = _contato(db, contato_id)
    try:
        conv = await at.iniciar_conversa(db, c, db.merge(u), dados.texto)
    except at.ErroAtendimento as e:
        db.rollback()
        raise HTTPException(e.status, str(e)) from e
    return {"conversa_id": conv.id}


# ---------------------------------------------------------------- etiquetas
@rotas.get("/etiquetas")
def etiquetas(u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    return [{"id": e.id, "nome": e.nome, "cor": e.cor} for e in db.scalars(select(Etiqueta).order_by(Etiqueta.nome))]


@rotas.post("/etiquetas")
def criar_etiqueta(dados: DadosEtiqueta, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    e = Etiqueta(nome=dados.nome.strip(), cor=dados.cor)
    db.add(e)
    try:
        db.commit()
    except IntegrityError as erro:
        db.rollback()
        raise HTTPException(409, "Etiqueta já existe.") from erro
    return {"id": e.id, "nome": e.nome, "cor": e.cor}


@rotas.delete("/etiquetas/{etiqueta_id}")
def excluir_etiqueta(etiqueta_id: int, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    e = db.get(Etiqueta, etiqueta_id)
    if e:
        db.delete(e)
        db.commit()
    return {"ok": True}
