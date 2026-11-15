"""Cliente do gateway WhatsApp (whatsapp-gateway/, Node + Baileys).

Sem ``WHATSAPP_GATEWAY_URL`` o CRM roda em MODO SIMULADO: nada sai para o
WhatsApp, e a tela do WhatsApp ganha um simulador para "receber" mensagens.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from .config import GATEWAY_TOKEN, GATEWAY_URL, WHATSAPP_SIMULADO

ESTADO_SIMULADO = {"estado": "conectado", "qr": None, "numero": "5511900000000",
                   "nome": "Lavo (simulado)", "erro": None, "simulado": True}

# Último status recebido do gateway (atualizado pelo webhook).
ultimo_status: dict[str, Any] = dict(ESTADO_SIMULADO) if WHATSAPP_SIMULADO else {
    "estado": "desconhecido", "qr": None, "numero": None, "nome": None, "erro": None, "simulado": False}


class ErroWhatsapp(RuntimeError):
    pass


async def _chamar(metodo: str, rota: str, corpo: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            r = await cliente.request(metodo, f"{GATEWAY_URL}{rota}", json=corpo,
                                      headers={"X-Gateway-Token": GATEWAY_TOKEN})
    except httpx.HTTPError as e:
        raise ErroWhatsapp(f"gateway do WhatsApp inacessível: {e}") from e
    dados = r.json() if r.content else {}
    if r.status_code >= 400:
        raise ErroWhatsapp(dados.get("erro") or f"gateway respondeu {r.status_code}")
    return dados


async def status() -> dict[str, Any]:
    if WHATSAPP_SIMULADO:
        return dict(ESTADO_SIMULADO)
    try:
        ultimo_status.update(await _chamar("GET", "/status"), simulado=False)
    except ErroWhatsapp as e:
        ultimo_status.update(estado="gateway_offline", qr=None, erro=str(e))
    return dict(ultimo_status)


async def conectar() -> dict[str, Any]:
    return dict(ESTADO_SIMULADO) if WHATSAPP_SIMULADO else await _chamar("POST", "/conectar")


async def desconectar() -> dict[str, Any]:
    return dict(ESTADO_SIMULADO) if WHATSAPP_SIMULADO else await _chamar("POST", "/desconectar")


async def enviar(jid: str, texto: str) -> str | None:
    """Envia texto e devolve o id da mensagem no WhatsApp."""
    if WHATSAPP_SIMULADO:
        return f"sim-{uuid.uuid4().hex[:16]}"
    return (await _chamar("POST", "/enviar", {"jid": jid, "texto": texto})).get("id")


async def digitando(jid: str, ativo: bool = True) -> None:
    if WHATSAPP_SIMULADO:
        return
    try:
        await _chamar("POST", "/digitando", {"jid": jid, "ativo": ativo})
    except ErroWhatsapp:
        pass  # indicador de digitação é cosmético


def jid_de_telefone(telefone: str) -> str:
    return f"{''.join(c for c in telefone if c.isdigit())}@s.whatsapp.net"
