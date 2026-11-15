"""WhatsApp (Cloud API oficial): webhook, status do número, modelos, campanhas, mídia e anexos."""

from __future__ import annotations

import hmac
import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import atendimento as at
from .. import campanhas as cp
from .. import serializar as s
from .. import whatsapp
from ..config import PASTA_DADOS
from ..db import obter_db
from ..eventos import barramento
from ..modelos import Campanha, CampanhaEnvio, Contato, Conversa, Mensagem, ModeloMensagem, Usuario, agora
from ..preferencias import ler_config
from .base import gestor, usuario_logado

rotas = APIRouter(prefix="/api", tags=["whatsapp"])
PASTA_MIDIA = PASTA_DADOS / "midia"


# ---------------------------------------------------------------- webhook da Meta
@rotas.get("/whatsapp/webhook", include_in_schema=False)
def verificar_webhook(modo: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
                      desafio: str = Query("", alias="hub.challenge")):
    """Handshake feito pela Meta ao cadastrar a URL do webhook."""
    if modo == "subscribe" and whatsapp.VERIFY_TOKEN and hmac.compare_digest(token, whatsapp.VERIFY_TOKEN):
        return PlainTextResponse(desafio)
    raise HTTPException(403, "verify_token inválido")


@rotas.post("/whatsapp/webhook", include_in_schema=False)
async def receber_webhook(request: Request):
    corpo = await request.body()
    if not whatsapp.APP_SECRET:
        raise HTTPException(503, "Defina WHATSAPP_APP_SECRET para receber webhooks.")
    if not whatsapp.assinatura_valida(corpo, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "assinatura inválida")
    mensagens, status_lista, modelos = whatsapp.interpretar_webhook(await request.json())
    for st in status_lista:
        cp.atualizar_status(st)
    for evento in sorted(mensagens, key=lambda e: e.get("timestamp") or 0):
        await at.receber_do_whatsapp(evento)
    if modelos:
        from ..db import sessao

        with sessao() as db:
            for mo in modelos:
                m = db.scalar(select(ModeloMensagem).where(ModeloMensagem.meta_id == mo["id"])) or db.scalar(
                    select(ModeloMensagem).where(ModeloMensagem.nome == mo["nome"], ModeloMensagem.idioma == mo["idioma"]))
                if m and mo.get("status"):
                    m.status, m.motivo_rejeicao = mo["status"], mo.get("motivo") if mo.get("motivo") != "NONE" else None
        barramento.publicar("modelo", {})
    return {"ok": True}  # responder rápido: a Meta reenvia se demorar


# ---------------------------------------------------------------- conexão
@rotas.get("/whatsapp/status")
async def wpp_status(request: Request, u: Usuario = Depends(usuario_logado)):
    st = await whatsapp.status()
    base = str(request.base_url).rstrip("/")
    st["webhook_url"] = f"{base}/api/whatsapp/webhook"
    st["verify_token_definido"] = bool(whatsapp.VERIFY_TOKEN)
    st["versao"] = whatsapp.VERSAO
    return st


class Simulacao(BaseModel):
    telefone: str = Field(min_length=8, max_length=20)
    nome: str | None = None
    texto: str = Field(min_length=1, max_length=4000)


@rotas.post("/whatsapp/simular")
async def wpp_simular(d: Simulacao, u: Usuario = Depends(gestor)):
    """Só no modo simulado: finge que um contato mandou uma mensagem."""
    if not whatsapp.SIMULADO:
        raise HTTPException(409, "Simulador disponível só no modo simulado.")
    tel = whatsapp.wa_id(d.telefone)
    conv_id = await at.receber_do_whatsapp({"tipo": "mensagem", "id": f"wamid.simin{uuid.uuid4().hex[:16]}",
                                            "jid": tel, "telefone": tel, "nome": d.nome, "de_mim": False,
                                            "texto": d.texto, "midia": None})
    return {"conversa_id": conv_id}


# ---------------------------------------------------------------- modelos (templates)
class Botao(BaseModel):
    tipo: str = Field(pattern="^(QUICK_REPLY|URL|PHONE_NUMBER)$")
    texto: str = Field(min_length=1, max_length=25)
    url: str | None = None
    telefone: str | None = None


class NovoModelo(BaseModel):
    nome: str = Field(min_length=1, max_length=512, pattern=r"^[a-z0-9_]+$")
    idioma: str = "pt_BR"
    categoria: str = Field(pattern="^(MARKETING|UTILITY|AUTHENTICATION)$")
    cabecalho: str | None = Field(None, max_length=60)
    corpo: str = Field(min_length=1, max_length=1024)
    rodape: str | None = Field(None, max_length=60)
    exemplos_corpo: list[str] = []
    exemplos_cabecalho: list[str] = []
    botoes: list[Botao] = []


def _modelo_json(m: ModeloMensagem) -> dict:
    return {"id": m.id, "meta_id": m.meta_id, "nome": m.nome, "idioma": m.idioma, "categoria": m.categoria,
            "status": m.status, "motivo_rejeicao": m.motivo_rejeicao, "componentes": m.componentes,
            "variaveis": cp.variaveis_do_modelo(m), "previa": cp.renderizar(m, [], []),
            "atualizado_em": s.iso(m.atualizado_em)}


@rotas.get("/modelos")
def listar_modelos(u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    return [_modelo_json(m) for m in db.scalars(select(ModeloMensagem).order_by(ModeloMensagem.nome))]


@rotas.post("/modelos/sincronizar")
async def sincronizar(u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    try:
        remotos = await whatsapp.listar_modelos()
    except whatsapp.ErroWhatsapp as e:
        raise HTTPException(502, str(e)) from e
    total = cp.sincronizar_modelos(db, remotos)
    at.auditar(db, u, "modelos_sincronizados", total=total)
    db.commit()
    return {"sincronizados": total}


@rotas.post("/modelos")
async def criar_modelo(d: NovoModelo, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    n_corpo, n_cab = cp.qtd_variaveis(d.corpo), cp.qtd_variaveis(d.cabecalho)
    if len(d.exemplos_corpo) != n_corpo or len(d.exemplos_cabecalho) != n_cab:
        raise HTTPException(400, f"Informe um exemplo para cada variável ({n_corpo} no corpo, {n_cab} no cabeçalho). "
                                 "A Meta exige exemplos para aprovar.")
    if re.search(r"^\s*\{\{\d+\}\}|\{\{\d+\}\}\s*$", d.corpo):
        raise HTTPException(400, "O corpo não pode começar nem terminar com uma variável (regra da Meta).")
    componentes: list[dict] = []
    if d.cabecalho:
        cab: dict = {"type": "HEADER", "format": "TEXT", "text": d.cabecalho}
        if n_cab:
            cab["example"] = {"header_text": d.exemplos_cabecalho}
        componentes.append(cab)
    corpo: dict = {"type": "BODY", "text": d.corpo}
    if n_corpo:
        corpo["example"] = {"body_text": [d.exemplos_corpo]}
    componentes.append(corpo)
    if d.rodape:
        componentes.append({"type": "FOOTER", "text": d.rodape})
    if d.botoes:
        botoes = []
        for b in d.botoes:
            item = {"type": b.tipo, "text": b.texto}
            if b.tipo == "URL":
                item["url"] = b.url
            if b.tipo == "PHONE_NUMBER":
                item["phone_number"] = b.telefone
            botoes.append(item)
        componentes.append({"type": "BUTTONS", "buttons": botoes})
    if db.scalar(select(ModeloMensagem).where(ModeloMensagem.nome == d.nome, ModeloMensagem.idioma == d.idioma)):
        raise HTTPException(409, "Já existe um modelo com este nome e idioma.")
    try:
        r = await whatsapp.criar_modelo({"name": d.nome, "language": d.idioma, "category": d.categoria,
                                         "components": componentes})
    except whatsapp.ErroWhatsapp as e:
        raise HTTPException(502, f"A Meta recusou o modelo: {e}") from e
    m = ModeloMensagem(meta_id=r.get("id"), nome=d.nome, idioma=d.idioma, categoria=r.get("category", d.categoria),
                       status=r.get("status", "PENDING"), componentes=componentes)
    db.add(m)
    db.flush()
    at.auditar(db, u, "modelo_criado", "modelo", m.id, nome=d.nome, categoria=d.categoria)
    db.commit()
    return _modelo_json(m)


@rotas.delete("/modelos/{modelo_id}")
async def excluir_modelo(modelo_id: int, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    m = db.get(ModeloMensagem, modelo_id) or _404()
    if db.scalar(select(Campanha.id).where(Campanha.modelo_id == m.id, Campanha.status.in_(["agendada", "enviando"]))):
        raise HTTPException(409, "Há campanhas agendadas ou em envio usando este modelo.")
    try:
        await whatsapp.excluir_modelo(m.nome)
    except whatsapp.ErroWhatsapp as e:
        raise HTTPException(502, str(e)) from e
    at.auditar(db, u, "modelo_excluido", "modelo", m.id, nome=m.nome)
    db.delete(m)
    db.commit()
    return {"ok": True}


class EnvioModelo(BaseModel):
    modelo_id: int
    variaveis: list[str] = []
    variaveis_cabecalho: list[str] = []


@rotas.post("/conversas/{conversa_id}/modelo")
async def enviar_modelo_conversa(conversa_id: int, d: EnvioModelo, u: Usuario = Depends(usuario_logado),
                                 db: Session = Depends(obter_db)):
    conv = db.get(Conversa, conversa_id) or _404()
    return await _enviar_modelo(db, conv.contato, d, u)


@rotas.post("/contatos/{contato_id}/modelo")
async def enviar_modelo_contato(contato_id: int, d: EnvioModelo, u: Usuario = Depends(usuario_logado),
                                db: Session = Depends(obter_db)):
    contato = db.get(Contato, contato_id) or _404()
    return await _enviar_modelo(db, contato, d, u)


async def _enviar_modelo(db: Session, contato: Contato, d: EnvioModelo, u: Usuario) -> dict:
    modelo = db.get(ModeloMensagem, d.modelo_id) or _404()
    if modelo.categoria == "MARKETING" and not contato.opt_in:
        raise HTTPException(409, "Modelos de marketing só podem ir para contatos com opt-in.")
    try:
        m = await cp.enviar_modelo_para_contato(db, contato, modelo, d.variaveis, d.variaveis_cabecalho or None,
                                                usuario=db.merge(u))
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e
    except whatsapp.ErroWhatsapp as e:
        db.commit()  # guarda a tentativa com o erro
        raise HTTPException(502, str(e)) from e
    at.auditar(db, u, "modelo_enviado", "contato", contato.id, modelo=modelo.nome)
    db.commit()
    return {"conversa_id": m.conversa_id, "mensagem_id": m.id}


# ---------------------------------------------------------------- campanhas
class DadosCampanha(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    modelo_id: int
    variaveis: list[dict] = []
    etiqueta_ids: list[int] = []
    agendada_para: datetime | None = None
    por_minuto: int = Field(60, ge=1, le=1000)


def _campanha_json(db: Session, c: Campanha) -> dict:
    return {"id": c.id, "nome": c.nome, "modelo": {"id": c.modelo.id, "nome": c.modelo.nome,
                                                    "categoria": c.modelo.categoria},
            "variaveis": c.variaveis, "etiqueta_ids": c.etiqueta_ids, "agendada_para": s.iso(c.agendada_para),
            "status": c.status, "por_minuto": c.por_minuto, "criada_por": c.criada_por.nome if c.criada_por else None,
            "criada_em": s.iso(c.criada_em), "concluida_em": s.iso(c.concluida_em), "metricas": cp.metricas(db, c.id)}


@rotas.get("/campanhas")
def listar_campanhas(u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    return [_campanha_json(db, c) for c in db.scalars(select(Campanha).order_by(Campanha.id.desc()))]


@rotas.post("/campanhas/previa")
def previa_campanha(d: DadosCampanha, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    """Quantos contatos recebem e como fica a mensagem para o primeiro deles."""
    modelo = db.get(ModeloMensagem, d.modelo_id) or _404()
    tmp = Campanha(nome=d.nome, modelo_id=modelo.id, variaveis=d.variaveis, etiqueta_ids=d.etiqueta_ids)
    alvo = cp.publico(db, tmp)
    sem_opt = db.scalar(select(func.count(Contato.id)).where(Contato.telefone.is_not(None))) - len(alvo)
    exemplo = cp.renderizar(modelo, cp.parametros_para(tmp, alvo[0])) if alvo else None
    return {"destinatarios": len(alvo), "excluidos_sem_opt_in_ou_filtro": max(sem_opt, 0), "exemplo": exemplo,
            "categoria": modelo.categoria}


@rotas.post("/campanhas")
def criar_campanha(d: DadosCampanha, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    modelo = db.get(ModeloMensagem, d.modelo_id) or _404()
    if modelo.status != "APPROVED":
        raise HTTPException(400, "Escolha um modelo aprovado pela Meta.")
    if len(d.variaveis) != cp.variaveis_do_modelo(modelo)["corpo"]:
        raise HTTPException(400, "Defina todas as variáveis do modelo.")
    quando = d.agendada_para
    if quando and not quando.tzinfo:
        quando = quando.replace(tzinfo=ZoneInfo(ler_config(db)["fuso_horario"]))
    c = Campanha(nome=d.nome, modelo_id=modelo.id, variaveis=d.variaveis, etiqueta_ids=d.etiqueta_ids,
                 agendada_para=quando, por_minuto=d.por_minuto, criada_por_id=u.id, status="rascunho")
    db.add(c)
    db.flush()
    at.auditar(db, u, "campanha_criada", "campanha", c.id, nome=c.nome)
    db.commit()
    return _campanha_json(db, c)


@rotas.post("/campanhas/{campanha_id}/iniciar")
def iniciar_campanha(campanha_id: int, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    c = db.get(Campanha, campanha_id) or _404()
    if c.status not in ("rascunho", "cancelada"):
        raise HTTPException(409, f"Campanha já está {c.status}.")
    c.status = "agendada"
    c.agendada_para = c.agendada_para if c.agendada_para and c.agendada_para > agora() else agora()
    at.auditar(db, u, "campanha_iniciada", "campanha", c.id, agendada_para=s.iso(c.agendada_para))
    db.commit()
    barramento.publicar("campanha", {"id": c.id})
    return _campanha_json(db, c)


@rotas.post("/campanhas/{campanha_id}/cancelar")
def cancelar_campanha(campanha_id: int, u: Usuario = Depends(gestor), db: Session = Depends(obter_db)):
    c = db.get(Campanha, campanha_id) or _404()
    if c.status in ("concluida", "cancelada"):
        raise HTTPException(409, f"Campanha já está {c.status}.")
    c.status = "cancelada"
    for envio in db.scalars(select(CampanhaEnvio).where(CampanhaEnvio.campanha_id == c.id,
                                                        CampanhaEnvio.status == "pendente")):
        envio.status = "ignorado"
    at.auditar(db, u, "campanha_cancelada", "campanha", c.id)
    db.commit()
    barramento.publicar("campanha", {"id": c.id})
    return _campanha_json(db, c)


@rotas.get("/campanhas/{campanha_id}/envios")
def envios_campanha(campanha_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    return [{"contato": e.contato.nome or e.contato.telefone, "contato_id": e.contato_id, "status": e.status,
             "erro": e.erro, "enviada_em": s.iso(e.enviada_em)}
            for e in db.scalars(select(CampanhaEnvio).where(CampanhaEnvio.campanha_id == campanha_id)
                                .order_by(CampanhaEnvio.id).limit(2000))]


# ---------------------------------------------------------------- mídia
@rotas.get("/midia/{mensagem_id}")
def midia(mensagem_id: int, u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    m = db.get(Mensagem, mensagem_id)
    if not m or not m.midia_arquivo:
        raise HTTPException(404, "Mídia não disponível.")
    caminho = (PASTA_MIDIA / Path(m.midia_arquivo).name).resolve()
    if not caminho.is_relative_to(PASTA_MIDIA.resolve()) or not caminho.exists():
        raise HTTPException(404, "Arquivo não encontrado.")
    return FileResponse(caminho, media_type=m.midia_mime or "application/octet-stream",
                        filename=m.midia_nome or caminho.name, content_disposition_type="inline")


@rotas.post("/conversas/{conversa_id}/anexo")
async def enviar_anexo(conversa_id: int, arquivo: UploadFile = File(...), legenda: str = Form(""),
                       u: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    conv = db.get(Conversa, conversa_id) or _404()
    contato = conv.contato
    if not whatsapp.janela_aberta(contato.ultima_entrada_em):
        raise HTTPException(409, "Janela de 24h fechada: envie um modelo antes de mandar anexos.")
    conteudo = await arquivo.read()
    mime = (arquivo.content_type or "application/octet-stream").split(";")[0]
    tipo = whatsapp.tipo_por_mime(mime)
    limite = whatsapp.LIMITES_MIDIA[tipo]
    if len(conteudo) > limite * 1024 * 1024:
        raise HTTPException(413, f"Arquivo grande demais para {tipo} (máx. {limite} MB).")
    nome = Path(arquivo.filename or "arquivo").name[:150]
    u = db.merge(u)
    if conv.modo != "humano" or conv.atendente_id != u.id or conv.status != "aberta":
        at.assumir(db, conv, u, automatico=True)
    try:
        media_id = await whatsapp.subir_midia(conteudo, mime, nome)
        wid, erro = await whatsapp.enviar_midia(contato.whatsapp_jid or contato.telefone, tipo, media_id,
                                                legenda or None, nome), None
    except whatsapp.ErroWhatsapp as e:
        media_id, wid, erro = None, None, str(e)
    PASTA_MIDIA.mkdir(parents=True, exist_ok=True)
    rotulo = {"image": "imagem", "video": "video", "audio": "audio", "document": "documento"}[tipo]
    m = Mensagem(conversa_id=conv.id, direcao="saida", autor_tipo="humano", usuario_id=u.id, origem="crm",
                 texto=legenda, midia=rotulo, midia_id=media_id, midia_mime=mime, midia_nome=nome, whatsapp_id=wid,
                 status_envio="erro" if erro else "enviada", erro=erro, processada_pelo_agente=True)
    db.add(m)
    db.flush()
    arquivo_local = f"{m.id}-envio{whatsapp.extensao(mime)}"
    (PASTA_MIDIA / arquivo_local).write_bytes(conteudo)
    m.midia_arquivo = arquivo_local
    conv.ultima_mensagem_em = agora()
    db.commit()
    at.publicar_conversa(conv.id)
    barramento.publicar("mensagem", {"conversa_id": conv.id})
    if erro:
        raise HTTPException(502, erro)
    return {"mensagem_id": m.id}


def _404():
    raise HTTPException(404, "Não encontrado.")


__all__ = ["rotas", "IntegrityError"]
