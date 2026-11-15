"""Login, logout, primeiro acesso e conta do usuário."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import serializar as s
from ..atendimento import auditar
from ..config import COOKIE_SEGURO, DURACAO_SESSAO_H
from ..db import obter_db
from ..modelos import Usuario, agora
from ..seguranca import conferir_senha, criar_token, gerar_hash
from .base import COOKIE, usuario_logado

rotas = APIRouter(prefix="/api", tags=["autenticação"])
_tentativas: dict[str, list[float]] = {}


class Login(BaseModel):
    email: str
    senha: str


class Setup(BaseModel):
    nome: str = Field(min_length=2)
    email: str = Field(pattern=EMAIL)
    senha: str = Field(min_length=8)


class TrocaSenha(BaseModel):
    senha_atual: str
    nova_senha: str = Field(min_length=8)


def _definir_cookie(resp: Response, u: Usuario) -> None:
    resp.set_cookie(COOKIE, criar_token(u.id, u.versao_sessao), httponly=True, samesite="lax",
                    secure=COOKIE_SEGURO, max_age=DURACAO_SESSAO_H * 3600)


def _limitar(chave: str) -> None:
    import time

    agora_s = time.time()
    lista = [t for t in _tentativas.get(chave, []) if agora_s - t < 300]
    if len(lista) >= 10:
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    lista.append(agora_s)
    _tentativas[chave] = lista


@rotas.post("/login")
def login(dados: Login, request: Request, resp: Response, db: Session = Depends(obter_db)):
    _limitar(f"{request.client.host if request.client else '?'}:{dados.email.lower()}")
    u = db.scalar(select(Usuario).where(func.lower(Usuario.email) == dados.email.strip().lower()))
    if not u or not u.ativo or not conferir_senha(dados.senha, u.senha_hash):
        raise HTTPException(401, "E-mail ou senha inválidos.")
    u.ultimo_acesso = u.ultimo_sinal = agora()
    u.status = "online"  # entra disponível para a distribuição
    auditar(db, u, "login")
    db.commit()
    _definir_cookie(resp, u)
    return s.usuario(u)


@rotas.post("/logout")
def logout(resp: Response, request: Request, db: Session = Depends(obter_db)):
    from .base import usuario_opcional

    u = usuario_opcional(request, db)
    if u:
        u.status = "offline"
        auditar(db, u, "logout")
        db.commit()
    resp.delete_cookie(COOKIE)
    return {"ok": True}


@rotas.get("/setup")
def precisa_setup(db: Session = Depends(obter_db)):
    return {"precisa_setup": db.scalar(select(func.count(Usuario.id))) == 0}


@rotas.post("/setup")
def setup(dados: Setup, resp: Response, db: Session = Depends(obter_db)):
    """Cria o primeiro administrador (só funciona com o banco vazio)."""
    if db.scalar(select(func.count(Usuario.id))):
        raise HTTPException(409, "O sistema já foi configurado.")
    u = Usuario(nome=dados.nome.strip(), email=dados.email.lower(), senha_hash=gerar_hash(dados.senha), papel="admin")
    db.add(u)
    db.flush()
    auditar(db, u, "setup_admin_criado", "usuario", u.id)
    db.commit()
    _definir_cookie(resp, u)
    return s.usuario(u)


@rotas.get("/eu")
def eu(u: Usuario = Depends(usuario_logado)):
    return s.usuario(u)


@rotas.post("/eu/senha")
def trocar_senha(dados: TrocaSenha, resp: Response, u: Usuario = Depends(usuario_logado),
                 db: Session = Depends(obter_db)):
    u = db.merge(u)
    if not conferir_senha(dados.senha_atual, u.senha_hash):
        raise HTTPException(400, "Senha atual incorreta.")
    u.senha_hash, u.versao_sessao = gerar_hash(dados.nova_senha), u.versao_sessao + 1
    auditar(db, u, "senha_alterada", "usuario", u.id)
    db.commit()
    _definir_cookie(resp, u)
    return {"ok": True}
