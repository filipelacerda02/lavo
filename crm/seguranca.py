"""Senhas (scrypt) e cookie de sessão assinado (HMAC)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from .config import DURACAO_SESSAO_H, SEGREDO

_N, _R, _P = 2**14, 8, 1


def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, n=_N, r=_R, p=_P)
    return f"scrypt${base64.b64encode(sal).decode()}${base64.b64encode(h).decode()}"


def conferir_senha(senha: str, armazenado: str) -> bool:
    try:
        _, sal_b64, h_b64 = armazenado.split("$")
        h = hashlib.scrypt(senha.encode(), salt=base64.b64decode(sal_b64), n=_N, r=_R, p=_P)
        return hmac.compare_digest(h, base64.b64decode(h_b64))
    except (ValueError, TypeError):
        return False


def _assinar(texto: str) -> str:
    return hmac.new(SEGREDO.encode(), texto.encode(), hashlib.sha256).hexdigest()


def criar_token(usuario_id: int, versao: int) -> str:
    expira = int(time.time()) + DURACAO_SESSAO_H * 3600
    corpo = f"{usuario_id}:{versao}:{expira}"
    return f"{corpo}:{_assinar(corpo)}"


def ler_token(token: str | None) -> tuple[int, int] | None:
    """Retorna (usuario_id, versao_sessao) se o token for válido e não expirado."""
    if not token:
        return None
    try:
        usuario_id, versao, expira, assinatura = token.split(":")
    except ValueError:
        return None
    corpo = f"{usuario_id}:{versao}:{expira}"
    if not hmac.compare_digest(assinatura, _assinar(corpo)) or int(expira) < time.time():
        return None
    return int(usuario_id), int(versao)
