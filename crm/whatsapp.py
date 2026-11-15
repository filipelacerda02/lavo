"""WhatsApp Business Platform — Cloud API oficial da Meta.

Configuração (.env):
    WHATSAPP_PROVEDOR=cloud            # "simulado" (padrão sem token) para testar sem a Meta
    WHATSAPP_TOKEN=...                 # token de usuário do sistema (System User) com whatsapp_business_messaging
                                       # e whatsapp_business_management
    WHATSAPP_PHONE_NUMBER_ID=...       # id do número (não é o telefone)
    WHATSAPP_WABA_ID=...               # id da conta WhatsApp Business (modelos de mensagem)
    WHATSAPP_APP_SECRET=...            # segredo do app: valida a assinatura X-Hub-Signature-256 do webhook
    WHATSAPP_VERIFY_TOKEN=...          # texto livre: o mesmo informado no painel da Meta ao cadastrar o webhook
    WHATSAPP_GRAPH_VERSION=v26.0

Regras da plataforma que este módulo respeita:
* Mensagem livre só dentro da JANELA DE 24 HORAS desde a última mensagem do cliente.
  Fora dela, apenas MODELOS (templates) aprovados pela Meta.
* O destinatário é o wa_id (telefone só com dígitos, com DDI).
"""

from __future__ import annotations

import hashlib
import hmac
import mimetypes
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from lavo import config as _config  # noqa: F401 - carrega o .env antes de ler as variáveis

PROVEDOR = os.getenv("WHATSAPP_PROVEDOR", "cloud" if os.getenv("WHATSAPP_TOKEN") else "simulado")
TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WABA_ID = os.getenv("WHATSAPP_WABA_ID", "")
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
VERSAO = os.getenv("WHATSAPP_GRAPH_VERSION", "v26.0")
GRAPH = f"https://graph.facebook.com/{VERSAO}"

SIMULADO = PROVEDOR != "cloud"
JANELA = timedelta(hours=24)

# Para testes: injete um httpx.MockTransport aqui.
transporte: httpx.AsyncBaseTransport | None = None

# Erros comuns da Cloud API, traduzidos para a equipe.
ERROS = {
    131047: "Janela de 24h fechada: o cliente não fala com você há mais de 24 horas. Envie um modelo aprovado.",
    131026: "Mensagem não entregue (número sem WhatsApp, versão antiga do app ou não aceitou os termos).",
    131049: "A Meta limitou o envio de marketing para este cliente (excesso de mensagens recebidas).",
    131050: "O cliente optou por não receber mensagens de marketing.",
    131051: "Tipo de mensagem não suportado.",
    131056: "Muitas mensagens para o mesmo número em pouco tempo. Aguarde.",
    130429: "Limite de envio por segundo atingido. Tente de novo em instantes.",
    131048: "Envio limitado por denúncias de spam. Revise o conteúdo das mensagens.",
    132000: "Número de variáveis do modelo não confere.",
    132001: "Modelo não existe ou não está aprovado neste idioma.",
    132015: "Modelo pausado pela Meta por baixa qualidade.",
    132016: "Modelo desativado pela Meta.",
    190: "Token da Meta expirado ou inválido. Atualize WHATSAPP_TOKEN.",
    80007: "Limite de requisições da conta atingido. Tente mais tarde.",
}

ESTADO_SIMULADO = {"estado": "conectado", "simulado": True, "provedor": "simulado",
                   "numero": "+55 11 90000-0000", "nome": "Lavo (simulado)", "qualidade": "GREEN",
                   "limite": "TIER_1K", "erro": None}

ultimo_status: dict[str, Any] = dict(ESTADO_SIMULADO) if SIMULADO else {
    "estado": "desconhecido", "simulado": False, "provedor": "cloud", "erro": None}


class ErroWhatsapp(RuntimeError):
    def __init__(self, mensagem: str, codigo: int | None = None) -> None:
        super().__init__(mensagem)
        self.codigo = codigo


def traduzir_erro(codigo: int | None, mensagem: str = "") -> str:
    return ERROS.get(codigo or 0, mensagem or f"Erro {codigo} da Cloud API")


# ------------------------------------------------------------------ HTTP
async def _graph(metodo: str, caminho: str, *, json: dict | None = None, params: dict | None = None,
                 files: dict | None = None, data: dict | None = None) -> dict[str, Any]:
    if not TOKEN:
        raise ErroWhatsapp("WHATSAPP_TOKEN não configurado.")
    try:
        async with httpx.AsyncClient(timeout=30, transport=transporte) as cliente:
            r = await cliente.request(metodo, f"{GRAPH}/{caminho.lstrip('/')}", json=json, params=params,
                                      files=files, data=data, headers={"Authorization": f"Bearer {TOKEN}"})
    except httpx.HTTPError as e:
        raise ErroWhatsapp(f"Cloud API inacessível: {e}") from e
    try:
        corpo = r.json()
    except ValueError:
        corpo = {}
    if r.status_code >= 400 or "error" in corpo:
        erro = corpo.get("error", {})
        codigo = erro.get("code")
        detalhe = (erro.get("error_data") or {}).get("details") or erro.get("message") or f"HTTP {r.status_code}"
        raise ErroWhatsapp(traduzir_erro(codigo, detalhe), codigo)
    return corpo


def _id_simulado() -> str:
    return f"wamid.sim{uuid.uuid4().hex[:20]}"


async def _enviar(corpo: dict[str, Any]) -> str:
    if SIMULADO:
        return _id_simulado()
    r = await _graph("POST", f"{PHONE_NUMBER_ID}/messages", json={"messaging_product": "whatsapp", **corpo})
    return r["messages"][0]["id"]


# ------------------------------------------------------------------ envio
def wa_id(telefone_ou_id: str) -> str:
    return "".join(c for c in (telefone_ou_id or "") if c.isdigit())


jid_de_telefone = wa_id  # compatibilidade com o restante do CRM


async def enviar(destino: str, texto: str, responder_a: str | None = None) -> str:
    """Texto livre (só dentro da janela de 24h). Devolve o wamid."""
    corpo: dict[str, Any] = {"recipient_type": "individual", "to": wa_id(destino), "type": "text",
                             "text": {"body": texto, "preview_url": True}}
    if responder_a:
        corpo["context"] = {"message_id": responder_a}
    return await _enviar(corpo)


async def enviar_modelo(destino: str, nome: str, idioma: str, parametros_corpo: list[str] | None = None,
                        parametros_cabecalho: list[str] | None = None) -> str:
    """Modelo aprovado (funciona fora da janela de 24h)."""
    componentes = []
    if parametros_cabecalho:
        componentes.append({"type": "header", "parameters": [{"type": "text", "text": p} for p in parametros_cabecalho]})
    if parametros_corpo:
        componentes.append({"type": "body", "parameters": [{"type": "text", "text": p} for p in parametros_corpo]})
    modelo: dict[str, Any] = {"name": nome, "language": {"code": idioma}}
    if componentes:
        modelo["components"] = componentes
    return await _enviar({"to": wa_id(destino), "type": "template", "template": modelo})


async def enviar_midia(destino: str, tipo: str, media_id: str, legenda: str | None = None,
                       nome_arquivo: str | None = None) -> str:
    conteudo: dict[str, Any] = {"id": media_id}
    if legenda and tipo in ("image", "video", "document"):
        conteudo["caption"] = legenda
    if nome_arquivo and tipo == "document":
        conteudo["filename"] = nome_arquivo
    return await _enviar({"to": wa_id(destino), "type": tipo, tipo: conteudo})


async def marcar_lida(message_id: str | None, digitando: bool = False) -> None:
    """Confirma leitura (✓✓ azul para o cliente) e, opcionalmente, mostra 'digitando…'."""
    if SIMULADO or not message_id or message_id.startswith("sim"):
        return
    corpo: dict[str, Any] = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
    if digitando:
        corpo["typing_indicator"] = {"type": "text"}
    try:
        await _graph("POST", f"{PHONE_NUMBER_ID}/messages", json=corpo)
    except ErroWhatsapp:
        pass  # cosmético: nunca derruba o atendimento


async def digitando(destino: str, ativo: bool = True, message_id: str | None = None) -> None:
    if ativo:
        await marcar_lida(message_id, digitando=True)


# ------------------------------------------------------------------ mídia
LIMITES_MIDIA = {"image": 5, "video": 16, "audio": 16, "document": 100, "sticker": 0.5}  # MB


def tipo_por_mime(mime: str) -> str:
    if mime.startswith("image/") and mime in ("image/jpeg", "image/png"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "document"


async def subir_midia(conteudo: bytes, mime: str, nome: str) -> str:
    if SIMULADO:
        return f"sim-midia-{uuid.uuid4().hex[:12]}"
    r = await _graph("POST", f"{PHONE_NUMBER_ID}/media", data={"messaging_product": "whatsapp", "type": mime},
                     files={"file": (nome, conteudo, mime)})
    return r["id"]


async def baixar_midia(media_id: str) -> tuple[bytes, str]:
    """Baixa a mídia recebida (a URL da Meta expira em minutos e exige o token)."""
    if SIMULADO:
        raise ErroWhatsapp("Mídia indisponível no modo simulado.")
    info = await _graph("GET", media_id)
    try:
        async with httpx.AsyncClient(timeout=60, transport=transporte) as cliente:
            r = await cliente.get(info["url"], headers={"Authorization": f"Bearer {TOKEN}"})
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise ErroWhatsapp(f"Falha ao baixar mídia: {e}") from e
    return r.content, info.get("mime_type") or r.headers.get("content-type", "application/octet-stream")


def extensao(mime: str) -> str:
    return {"audio/ogg": ".ogg", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(
        mime.split(";")[0], mimetypes.guess_extension(mime.split(";")[0]) or ".bin")


# ------------------------------------------------------------------ modelos (templates)
async def listar_modelos() -> list[dict[str, Any]]:
    if SIMULADO:
        return []
    modelos, params = [], {"fields": "id,name,language,status,category,components,rejected_reason", "limit": 100}
    caminho = f"{WABA_ID}/message_templates"
    while True:
        r = await _graph("GET", caminho, params=params)
        modelos += r.get("data", [])
        depois = (r.get("paging") or {}).get("cursors", {}).get("after")
        if not depois or not (r.get("paging") or {}).get("next"):
            return modelos
        params = {**params, "after": depois}


async def criar_modelo(corpo: dict[str, Any]) -> dict[str, Any]:
    if SIMULADO:
        return {"id": f"sim-{uuid.uuid4().hex[:10]}", "status": "APPROVED", "category": corpo["category"]}
    return await _graph("POST", f"{WABA_ID}/message_templates", json=corpo)


async def excluir_modelo(nome: str) -> None:
    if not SIMULADO:
        await _graph("DELETE", f"{WABA_ID}/message_templates", params={"name": nome})


# ------------------------------------------------------------------ conta / número
async def status() -> dict[str, Any]:
    if SIMULADO:
        return dict(ESTADO_SIMULADO)
    faltando = [n for n, v in (("WHATSAPP_TOKEN", TOKEN), ("WHATSAPP_PHONE_NUMBER_ID", PHONE_NUMBER_ID),
                               ("WHATSAPP_WABA_ID", WABA_ID), ("WHATSAPP_APP_SECRET", APP_SECRET),
                               ("WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN)) if not v]
    if faltando:
        ultimo_status.update(estado="nao_configurado", erro="Faltam variáveis: " + ", ".join(faltando))
        return dict(ultimo_status)
    try:
        r = await _graph("GET", PHONE_NUMBER_ID,
                         params={"fields": "display_phone_number,verified_name,quality_rating,name_status"})
        ultimo_status.update(estado="conectado", erro=None, numero=r.get("display_phone_number"),
                             nome=r.get("verified_name"), qualidade=r.get("quality_rating"),
                             nome_status=r.get("name_status"))
        try:  # o campo de limite mudou de nome entre versões; é opcional
            extra = await _graph("GET", PHONE_NUMBER_ID, params={"fields": "messaging_limit_tier"})
            ultimo_status["limite"] = extra.get("messaging_limit_tier")
        except ErroWhatsapp:
            pass
    except ErroWhatsapp as e:
        ultimo_status.update(estado="erro", erro=str(e))
    return dict(ultimo_status)


# ------------------------------------------------------------------ webhook
def assinatura_valida(corpo: bytes, cabecalho: str | None) -> bool:
    if not APP_SECRET or not cabecalho or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(APP_SECRET.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho.removeprefix("sha256="))


def _texto_e_midia(m: dict[str, Any]) -> dict[str, Any]:
    tipo = m.get("type")
    if tipo == "text":
        return {"texto": m["text"].get("body", "")}
    if tipo in ("image", "video", "audio", "document", "sticker"):
        d = m.get(tipo, {})
        rotulo = {"image": "imagem", "video": "video", "audio": "audio", "document": "documento",
                  "sticker": "figurinha"}[tipo]
        return {"texto": d.get("caption") or (d.get("filename") if tipo == "document" else "") or "",
                "midia": rotulo, "midia_id": d.get("id"), "midia_mime": d.get("mime_type"),
                "midia_nome": d.get("filename")}
    if tipo == "interactive":
        i = m.get("interactive", {})
        resposta = i.get("button_reply") or i.get("list_reply") or {}
        return {"texto": resposta.get("title", ""), "botao": resposta.get("id")}
    if tipo == "button":  # resposta rápida de um modelo
        return {"texto": m["button"].get("text", ""), "botao": m["button"].get("payload")}
    if tipo == "location":
        loc = m.get("location", {})
        partes = [loc.get("name"), loc.get("address"), f"{loc.get('latitude')},{loc.get('longitude')}"]
        return {"texto": " · ".join(p for p in partes if p), "midia": "localizacao"}
    if tipo == "contacts":
        nomes = [c.get("name", {}).get("formatted_name", "") for c in m.get("contacts", [])]
        return {"texto": ", ".join(n for n in nomes if n), "midia": "contato"}
    if tipo == "reaction":
        return {"texto": m["reaction"].get("emoji") or "", "midia": "reacao",
                "reacao_a": m["reaction"].get("message_id")}
    return {"texto": "", "midia": "nao_suportado"}


def interpretar_webhook(payload: dict[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    """Converte o payload da Meta em (mensagens, status de entrega, eventos de modelo)."""
    mensagens, status_lista, modelos = [], [], []
    for entrada in payload.get("entry", []):
        for mudanca in entrada.get("changes", []):
            campo, v = mudanca.get("field"), mudanca.get("value", {})
            if campo == "message_template_status_update":
                modelos.append({"id": str(v.get("message_template_id", "")), "nome": v.get("message_template_name"),
                                "idioma": v.get("message_template_language"), "status": v.get("event"),
                                "motivo": v.get("reason")})
                continue
            nomes = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in v.get("contacts", [])}
            for m in v.get("messages", []):
                if m.get("type") == "system":
                    continue
                mensagens.append({
                    "tipo": "mensagem", "id": m.get("id"), "jid": m.get("from"), "telefone": m.get("from"),
                    "nome": nomes.get(m.get("from")), "de_mim": False,
                    "timestamp": int(m.get("timestamp") or 0), "responde_a": (m.get("context") or {}).get("id"),
                    **_texto_e_midia(m)})
            # Coexistência (número também no app WhatsApp Business): ecos do que a empresa enviou pelo celular
            for m in v.get("message_echoes", []):
                mensagens.append({
                    "tipo": "mensagem", "id": m.get("id"), "jid": m.get("to"), "telefone": m.get("to"), "nome": None,
                    "de_mim": True, "timestamp": int(m.get("timestamp") or 0), **_texto_e_midia(m)})
            for s in v.get("statuses", []):
                erro = (s.get("errors") or [{}])[0]
                status_lista.append({
                    "id": s.get("id"), "status": s.get("status"), "destino": s.get("recipient_id"),
                    "timestamp": int(s.get("timestamp") or 0),
                    "categoria": (s.get("pricing") or {}).get("category"),
                    "erro": traduzir_erro(erro.get("code"), (erro.get("error_data") or {}).get("details")
                                          or erro.get("title", "")) if erro else None,
                    "erro_codigo": erro.get("code")})
    return mensagens, status_lista, modelos


def janela_aberta(ultima_entrada: datetime | None, momento: datetime | None = None) -> bool:
    if ultima_entrada is None:
        return False
    momento = momento or datetime.now(timezone.utc)
    return momento - ultima_entrada < JANELA


def janela_fecha_em(ultima_entrada: datetime | None) -> datetime | None:
    return ultima_entrada + JANELA if ultima_entrada else None
