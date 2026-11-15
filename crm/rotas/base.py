"""Dependências comuns: usuário logado, papéis e proteção CSRF."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import obter_db
from ..modelos import Usuario
from ..seguranca import ler_token

COOKIE = "lavo_sessao"


def usuario_opcional(request: Request, db: Session = Depends(obter_db)) -> Usuario | None:
    dados = ler_token(request.cookies.get(COOKIE))
    if not dados:
        return None
    u = db.get(Usuario, dados[0])
    if not u or not u.ativo or u.versao_sessao != dados[1]:
        return None
    return u


def usuario_logado(request: Request, u: Usuario | None = Depends(usuario_opcional)) -> Usuario:
    if u is None:
        raise HTTPException(401, "Faça login.")
    # CSRF: requisições que alteram dados precisam deste cabeçalho (navegadores
    # não o enviam em formulários de outros sites).
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-requested-with") != "lavo":
        raise HTTPException(403, "Requisição sem cabeçalho de segurança.")
    return u


def exigir_papel(*papeis: str):
    def _dep(u: Usuario = Depends(usuario_logado)) -> Usuario:
        if u.papel not in papeis:
            raise HTTPException(403, "Sem permissão para esta ação.")
        return u
    return _dep


gestor = exigir_papel("admin", "supervisor")
admin = exigir_papel("admin")
