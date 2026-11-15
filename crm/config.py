"""Configuração do CRM (variáveis de ambiente; veja .env.example)."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from lavo.config import RAIZ  # também carrega o .env

PASTA_DADOS = Path(os.getenv("CRM_DADOS", str(RAIZ / ".crm")))
PASTA_DADOS.mkdir(parents=True, exist_ok=True)

URL_BANCO = os.getenv("CRM_BANCO", f"sqlite:///{PASTA_DADOS / 'crm.db'}")

# WhatsApp: Cloud API oficial (veja crm/whatsapp.py). Sem WHATSAPP_TOKEN => modo simulado.
from .whatsapp import SIMULADO as WHATSAPP_SIMULADO  # noqa: E402

# Cookies de sessão: segredo persistente gerado no primeiro uso.
_arquivo_segredo = PASTA_DADOS / "segredo"
if os.getenv("CRM_SEGREDO"):
    SEGREDO = os.environ["CRM_SEGREDO"]
else:
    if not _arquivo_segredo.exists():
        _arquivo_segredo.write_text(secrets.token_hex(32))
        _arquivo_segredo.chmod(0o600)
    SEGREDO = _arquivo_segredo.read_text().strip()

COOKIE_SEGURO = os.getenv("CRM_COOKIE_SEGURO", "0") == "1"  # ligue em produção (HTTPS)
DURACAO_SESSAO_H = int(os.getenv("CRM_DURACAO_SESSAO_H", "12"))
