"""Orquestração do atendimento: quem responde cada conversa — o agente ou um humano.

Regras:
* Mensagem nova do WhatsApp -> se o agente estiver ligado (programação) e o
  contato não estiver bloqueado para o agente, a conversa fica em modo AGENTE e
  ele responde (esperando alguns segundos para juntar mensagens seguidas).
  Se o agente estiver desligado, a conversa vai para a FILA dos humanos.
* Um colaborador que responde (ou clica em "Assumir") vira o atendente da
  conversa: modo HUMANO, o agente para de responder nela. Cada mensagem guarda
  quem escreveu (agente, ou o usuário logado).
* Mensagem enviada direto pelo celular da empresa também pausa o agente na
  conversa (aparece como "Celular da empresa").
* "Devolver ao agente" ou "Resolver" encerram a vez do humano.
* Quando a programação desliga o agente, as conversas dele vão para a fila;
  quando liga, ele assume a fila que chegou fora do horário.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lavo.agente import SYSTEM, Agente
from lavo.conversa import Conversa as ConversaAgente
from lavo.ferramentas import Loja

from . import whatsapp
from .agenda import estado_do_agente
from .db import sessao
from .eventos import barramento
from .ferramentas_crm import FerramentasCRM
from .modelos import (
    MODO_AGENTE,
    MODO_FILA,
    MODO_HUMANO,
    Auditoria,
    Contato,
    Conversa,
    Mensagem,
    Usuario,
    agora,
)
from .preferencias import ler_config

log = logging.getLogger("crm.atendimento")

MOTIVO_FORA_HORARIO = "Agente desligado"  # prefixo: conversas que o agente pode retomar

SYSTEM_WHATSAPP = SYSTEM + """

Canal: WhatsApp.
- Mensagens curtas, uma ideia por parágrafo. Sem títulos nem tabelas; para destacar, use *negrito* do WhatsApp com moderação.
- Se o cliente ainda não estiver identificado e precisar de dados da conta, peça o e-mail e o CPF cadastrados e use identificar_cliente.
- Se o cliente pedir para falar com uma pessoa, ou se o assunto exigir decisão humana (dano, extravio, cobrança contestada, reclamação séria), use transferir_para_humano e avise em uma frase que um atendente vai continuar.
- Use abrir_chamado para pendências que a equipe resolve depois, sem transferir a conversa.
- Mensagens de mídia chegam como [áudio], [imagem] etc. Você não consegue ver nem ouvir mídia: peça ao cliente para escrever."""

ROTULO_MIDIA = {"audio": "áudio", "imagem": "imagem", "video": "vídeo", "documento": "documento",
                "figurinha": "figurinha", "localizacao": "localização", "contato": "contato"}

_agendamentos: dict[int, asyncio.Task] = {}
_travas: dict[int, asyncio.Lock] = {}
_llm = None
_rag = None


def componentes():
    """LLM e RAG compartilhados (criados uma vez)."""
    global _llm, _rag
    if _llm is None:
        from lavo.llm import LLM
        from lavo.rag import RAG

        _llm, _rag = LLM(), RAG()
        _rag.indexar()
    return _llm, _rag


def definir_componentes(llm: Any, rag: Any) -> None:
    """Para testes: injeta LLM/RAG falsos."""
    global _llm, _rag
    _llm, _rag = llm, rag


# ------------------------------------------------------------------ utilidades
def auditar(db: Session, usuario: Usuario | None, acao: str, entidade: str | None = None,
            entidade_id: int | None = None, **detalhes: Any) -> None:
    db.add(Auditoria(usuario_id=usuario.id if usuario else None, acao=acao, entidade=entidade,
                     entidade_id=entidade_id, detalhes=detalhes or None))


def evento_sistema(db: Session, conv: Conversa, texto: str, usuario: Usuario | None = None) -> Mensagem:
    m = Mensagem(conversa_id=conv.id, direcao="interna", autor_tipo="sistema", origem="sistema",
                 usuario_id=usuario.id if usuario else None, texto=texto, processada_pelo_agente=True)
    db.add(m)
    return m


def publicar_conversa(conv_id: int) -> None:
    barramento.publicar("conversa", {"id": conv_id})


def so_digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


def _vincular_cliente_por_telefone(contato: Contato) -> None:
    """Liga o contato ao cadastro de clientes se o telefone bater (últimos 10 dígitos)."""
    if contato.cliente_externo_id or not contato.telefone:
        return
    alvo = so_digitos(contato.telefone)[-10:]
    for cid, c in Loja().ler()["clientes"].items():
        tel = so_digitos(c.get("telefone"))
        # celular BR: compara sem o 9º dígito também
        if tel and (tel[-10:] == alvo or (len(tel) >= 11 and tel[-11:-9] + tel[-8:] == alvo[-10:-8] + alvo[-8:])):
            contato.cliente_externo_id = cid
            if not contato.nome or contato.nome == contato.telefone:
                contato.nome = c["nome"]
            contato.email = contato.email or c.get("email")
            return


def localizar_ou_criar_contato(db: Session, jid: str, telefone: str | None, nome: str | None) -> Contato:
    contato = db.scalar(select(Contato).where(Contato.whatsapp_jid == jid))
    if not contato and telefone:
        contato = db.scalar(select(Contato).where(Contato.telefone == telefone))
        if contato:
            contato.whatsapp_jid = jid
    if not contato:
        contato = Contato(whatsapp_jid=jid, telefone=telefone, nome=nome or telefone or "", origem="whatsapp")
        db.add(contato)
        _vincular_cliente_por_telefone(contato)
        db.flush()
        auditar(db, None, "contato_criado_whatsapp", "contato", contato.id)
    elif nome and (not contato.nome or contato.nome == contato.telefone):
        contato.nome = nome
    if telefone and not contato.telefone:
        contato.telefone = telefone
    return contato


def conversa_aberta(db: Session, contato_id: int) -> Conversa | None:
    return db.scalar(select(Conversa).where(Conversa.contato_id == contato_id, Conversa.status == "aberta")
                     .order_by(Conversa.id.desc()))


def mudar_modo(db: Session, conv: Conversa, modo: str, atendente: Usuario | None = None,
               motivo: str | None = None) -> None:
    conv.modo, conv.atendente_id, conv.motivo_fila, conv.modo_desde = (
        modo, atendente.id if atendente else None, motivo if modo == MODO_FILA else None, agora())
    if modo != MODO_AGENTE:
        cancelar_agendamento(conv.id)


def marcar_pendentes_processadas(db: Session, conv_id: int) -> None:
    for m in db.scalars(select(Mensagem).where(Mensagem.conversa_id == conv_id, Mensagem.direcao == "entrada",
                                               Mensagem.processada_pelo_agente.is_(False))):
        m.processada_pelo_agente = True


def cancelar_agendamento(conv_id: int) -> None:
    tarefa = _agendamentos.pop(conv_id, None)
    if tarefa and not tarefa.done():
        tarefa.cancel()


# ------------------------------------------------------------------ entrada do WhatsApp
async def receber_do_whatsapp(evento: dict[str, Any]) -> int | None:
    """Processa uma mensagem vinda do gateway. Retorna o id da conversa."""
    jid, wid = evento.get("jid"), evento.get("id")
    if not jid:
        return None
    texto = (evento.get("texto") or "").strip()
    midia = evento.get("midia")
    aviso: tuple[str, str] | None = None
    with sessao() as db:
        if wid and db.scalar(select(Mensagem.id).where(Mensagem.whatsapp_id == wid)):
            return None  # duplicada
        contato = localizar_ou_criar_contato(db, jid, evento.get("telefone"), evento.get("nome"))
        contato.ultima_interacao = agora()
        conv = conversa_aberta(db, contato.id)
        cfg = ler_config(db)

        if evento.get("de_mim"):
            # Alguém respondeu pelo celular da empresa (fora do CRM).
            if not conv:
                conv = Conversa(contato_id=contato.id, modo=MODO_HUMANO)
                db.add(conv)
                db.flush()
            db.add(Mensagem(conversa_id=conv.id, direcao="saida", autor_tipo="humano", origem="celular",
                            texto=texto, midia=midia, whatsapp_id=wid, processada_pelo_agente=True))
            if conv.modo != MODO_HUMANO or conv.atendente_id is not None:
                mudar_modo(db, conv, MODO_HUMANO)
                evento_sistema(db, conv, "📱 Respondido pelo celular da empresa — agente pausado nesta conversa.")
            marcar_pendentes_processadas(db, conv.id)
            conv.ultima_mensagem_em = agora()
            conv.primeira_resposta_em = conv.primeira_resposta_em or agora()
            conv_id = conv.id
        else:
            estado = estado_do_agente(db, calcular_proxima=False)
            agente_pode = estado.ativo and not contato.agente_bloqueado
            motivo_off = ("Contato configurado para atendimento só humano" if contato.agente_bloqueado
                          else f"{MOTIVO_FORA_HORARIO} ({estado.motivo})")
            if not conv:
                conv = Conversa(contato_id=contato.id, modo=MODO_AGENTE if agente_pode else MODO_FILA,
                                motivo_fila=None if agente_pode else motivo_off)
                db.add(conv)
                db.flush()
                evento_sistema(db, conv, "Nova conversa — 🤖 atendida pelo agente." if agente_pode
                               else f"Nova conversa — ⏳ na fila. {motivo_off}.")
            elif conv.modo == MODO_FILA and agente_pode and conv.atendente_id is None \
                    and (conv.motivo_fila or "").startswith(MOTIVO_FORA_HORARIO):
                mudar_modo(db, conv, MODO_AGENTE)
                evento_sistema(db, conv, "🤖 Agente ligado — retomou a conversa.")
            elif conv.modo == MODO_AGENTE and not agente_pode:
                mudar_modo(db, conv, MODO_FILA, motivo=motivo_off)
                evento_sistema(db, conv, f"⏳ Conversa enviada para a fila. {motivo_off}.")

            db.add(Mensagem(conversa_id=conv.id, direcao="entrada", autor_tipo="contato", origem="whatsapp",
                            texto=texto, midia=midia, whatsapp_id=wid))
            conv.nao_lidas += 1
            conv.ultima_mensagem_em = agora()
            conv_id = conv.id
            if (conv.modo == MODO_FILA and (conv.motivo_fila or "").startswith(MOTIVO_FORA_HORARIO)
                    and not conv.aviso_fora_horario_enviado and cfg.get("mensagem_fora_horario")):
                conv.aviso_fora_horario_enviado = True
                aviso = (contato.whatsapp_jid or whatsapp.jid_de_telefone(contato.telefone or ""),
                         cfg["mensagem_fora_horario"])
            modo = conv.modo

    if aviso:
        await _enviar_automatico(conv_id, *aviso)
    publicar_conversa(conv_id)
    barramento.publicar("mensagem", {"conversa_id": conv_id})
    if not evento.get("de_mim") and modo == MODO_AGENTE:
        agendar_agente(conv_id)
    return conv_id


async def _enviar_automatico(conv_id: int, jid: str, texto: str) -> None:
    try:
        wid, erro = await whatsapp.enviar(jid, texto), None
    except whatsapp.ErroWhatsapp as e:
        wid, erro = None, str(e)
    with sessao() as db:
        db.add(Mensagem(conversa_id=conv_id, direcao="saida", autor_tipo="sistema", origem="sistema", texto=texto,
                        whatsapp_id=wid, status_envio="erro" if erro else "enviada", erro=erro,
                        processada_pelo_agente=True))


# ------------------------------------------------------------------ agente
def agendar_agente(conv_id: int, espera: float | None = None) -> None:
    """Espera alguns segundos (junta mensagens seguidas) e chama o agente."""
    if espera is None:
        with sessao() as db:
            espera = float(ler_config(db)["espera_agrupar_s"])
    cancelar_agendamento(conv_id)

    async def _rodar() -> None:
        await asyncio.sleep(espera)
        _agendamentos.pop(conv_id, None)
        await executar_agente(conv_id)

    _agendamentos[conv_id] = asyncio.create_task(_rodar())


def _conteudo(m: Mensagem) -> str:
    if m.midia:
        return f"[{ROTULO_MIDIA.get(m.midia, m.midia)}] {m.texto or ''}".strip()
    return m.texto or ""


def _formatar_ocorrido(msgs: list[Mensagem]) -> str:
    linhas = []
    for m in msgs:
        if m.autor_tipo == "contato":
            quem = "Cliente"
        elif m.autor_tipo == "humano":
            quem = f"Atendente {m.usuario.nome}" if m.usuario else "Atendente (celular da empresa)"
        elif m.autor_tipo == "agente":
            quem = "Você (assistente)"
        else:
            quem = "Sistema"
        linhas.append(f"{quem}: {_conteudo(m)}")
    return "\n".join(linhas)


async def executar_agente(conv_id: int) -> None:
    trava = _travas.setdefault(conv_id, asyncio.Lock())
    async with trava:
        with sessao() as db:
            conv = db.get(Conversa, conv_id)
            if not conv or conv.status != "aberta" or conv.modo != MODO_AGENTE:
                return
            pendentes = list(db.scalars(select(Mensagem).where(
                Mensagem.conversa_id == conv_id, Mensagem.direcao == "entrada",
                Mensagem.processada_pelo_agente.is_(False)).order_by(Mensagem.id)))
            if not pendentes:
                return
            estado = conv.historico_agente or {}
            ultimo_visto = estado.get("ultimo_msg_id", 0)
            ids_pendentes = {m.id for m in pendentes}
            ocorrido = [m for m in db.scalars(select(Mensagem).where(
                Mensagem.conversa_id == conv_id, Mensagem.id > ultimo_visto,
                Mensagem.direcao.in_(["entrada", "saida"])).order_by(Mensagem.id)) if m.id not in ids_pendentes]
            # Só faz sentido contar o que os humanos falaram se o agente já participou antes.
            contexto_extra = _formatar_ocorrido(ocorrido) if ocorrido and estado else None
            pergunta = "\n".join(_conteudo(m) for m in pendentes)
            contato = conv.contato
            dados = dict(jid=contato.whatsapp_jid or whatsapp.jid_de_telefone(contato.telefone or ""),
                         cliente_id=contato.cliente_externo_id, contato_id=contato.id,
                         nome=contato.nome or None, telefone=contato.telefone)
            cfg = ler_config(db)
            ultimo_pendente = pendentes[-1].id

        await whatsapp.digitando(dados["jid"], True)
        try:
            resposta, historico, ferramentas = await asyncio.to_thread(
                _rodar_agente, conv_id, estado.get("conversa"), dados, pergunta, contexto_extra)
            erro = None
        except Exception as e:  # noqa: BLE001 - qualquer falha manda para humanos
            log.exception("agente falhou na conversa %s", conv_id)
            resposta = historico = ferramentas = None
            erro = f"{type(e).__name__}: {e}"
        await whatsapp.digitando(dados["jid"], False)

        with sessao() as db:
            conv = db.get(Conversa, conv_id)
            if erro:
                mudar_modo(db, conv, MODO_FILA, motivo="Falha do agente")
                evento_sistema(db, conv, f"⚠️ O agente falhou e a conversa foi para a fila. ({erro[:200]})")
                publicar_conversa(conv_id)
                return
            if conv.modo == MODO_HUMANO or conv.status != "aberta":
                quem = conv.atendente.nome if conv.atendente else "um humano"
                evento_sistema(db, conv, f"Resposta do agente descartada: {quem} assumiu a conversa antes.")
                for m in db.scalars(select(Mensagem).where(Mensagem.id <= ultimo_pendente,
                                                           Mensagem.conversa_id == conv_id)):
                    m.processada_pelo_agente = True
                publicar_conversa(conv_id)
                return
            texto = resposta.texto.strip()
            msg = None
            if texto:
                try:
                    wid, erro_envio = await whatsapp.enviar(dados["jid"], texto), None
                except whatsapp.ErroWhatsapp as e:
                    wid, erro_envio = None, str(e)
                msg = Mensagem(conversa_id=conv_id, direcao="saida", autor_tipo="agente", origem="agente",
                               texto=texto, whatsapp_id=wid, status_envio="erro" if erro_envio else "enviada",
                               erro=erro_envio, trace_id=resposta.trace_id, custo_usd=resposta.custo_usd,
                               processada_pelo_agente=True)
                db.add(msg)
                conv.primeira_resposta_em = conv.primeira_resposta_em or agora()
                conv.ultima_mensagem_em = agora()
            if resposta.bloqueado_por_guardrail:
                evento_sistema(db, conv, f"🛡️ Guardrail bloqueou a mensagem: {', '.join(resposta.motivos_guardrail)}")
            for m in db.scalars(select(Mensagem).where(Mensagem.id <= ultimo_pendente, Mensagem.conversa_id == conv_id,
                                                       Mensagem.direcao == "entrada")):
                m.processada_pelo_agente = True
            db.flush()
            conv.historico_agente = {"conversa": historico, "ultimo_msg_id": msg.id if msg else ultimo_pendente}
            if ferramentas and ferramentas.cliente_id and not conv.contato.cliente_externo_id:
                conv.contato.cliente_externo_id = ferramentas.cliente_id
            transferiu = bool(ferramentas and ferramentas.transferiu)
            extra = cfg.get("mensagem_transferencia") if transferiu else None

        if extra:
            await _enviar_automatico(conv_id, dados["jid"], extra)
        publicar_conversa(conv_id)
        barramento.publicar("mensagem", {"conversa_id": conv_id})

        # Chegou mensagem enquanto o agente pensava? Responde de novo.
        with sessao() as db:
            conv = db.get(Conversa, conv_id)
            ainda = db.scalar(select(Mensagem.id).where(Mensagem.conversa_id == conv_id, Mensagem.direcao == "entrada",
                                                        Mensagem.processada_pelo_agente.is_(False)))
            if ainda and conv.modo == MODO_AGENTE and conv.status == "aberta":
                agendar_agente(conv_id, espera=0.5)


def _rodar_agente(conv_id: int, historico: dict | None, dados: dict, pergunta: str, contexto_extra: str | None):
    """Roda o agente (bloqueante, numa thread)."""
    llm, rag = componentes()
    conversa = ConversaAgente(**historico) if historico else ConversaAgente(
        cliente_id=dados["cliente_id"] or f"contato-{dados['contato_id']}")
    cliente_id = dados["cliente_id"] if dados["cliente_id"] in Loja().ler()["clientes"] else None
    ferramentas = FerramentasCRM(cliente_id, conversa_id=conv_id, contato_id=dados["contato_id"], rag=rag)
    agente = Agente(cliente_id, llm=llm, rag=rag, ferramentas=ferramentas, conversa=conversa,
                    system=SYSTEM_WHATSAPP, nome_contato=dados["nome"],
                    dados_permitidos=[dados["telefone"]] if dados["telefone"] else [])
    resposta = agente.responder(pergunta, contexto_extra=contexto_extra)
    return resposta, dict(conversa.__dict__), ferramentas


# ------------------------------------------------------------------ ações dos colaboradores
class ErroAtendimento(Exception):
    def __init__(self, mensagem: str, status: int = 400) -> None:
        super().__init__(mensagem)
        self.status = status


def assumir(db: Session, conv: Conversa, usuario: Usuario, automatico: bool = False) -> None:
    if conv.status != "aberta":
        reabrir(db, conv, usuario)
    if conv.modo == MODO_HUMANO and conv.atendente_id == usuario.id:
        return
    anterior = conv.atendente.nome if conv.atendente else {"agente": "o agente", "fila": "a fila"}.get(conv.modo, "o celular")
    mudar_modo(db, conv, MODO_HUMANO, atendente=usuario)
    marcar_pendentes_processadas(db, conv.id)
    evento_sistema(db, conv, f"👤 {usuario.nome} assumiu o atendimento (antes: {anterior}).", usuario)
    auditar(db, usuario, "conversa_assumida", "conversa", conv.id, automatico=automatico)


async def enviar_humano(db: Session, conv: Conversa, usuario: Usuario, texto: str) -> Mensagem:
    texto = texto.strip()
    if not texto:
        raise ErroAtendimento("Mensagem vazia.")
    if conv.modo != MODO_HUMANO or conv.atendente_id != usuario.id or conv.status != "aberta":
        assumir(db, conv, usuario, automatico=True)
    contato = conv.contato
    jid = contato.whatsapp_jid or (whatsapp.jid_de_telefone(contato.telefone) if contato.telefone else None)
    if not jid:
        raise ErroAtendimento("Contato sem WhatsApp/telefone.")
    try:
        wid, erro = await whatsapp.enviar(jid, texto), None
    except whatsapp.ErroWhatsapp as e:
        wid, erro = None, str(e)
    m = Mensagem(conversa_id=conv.id, direcao="saida", autor_tipo="humano", usuario_id=usuario.id, origem="crm",
                 texto=texto, whatsapp_id=wid, status_envio="erro" if erro else "enviada", erro=erro,
                 processada_pelo_agente=True)
    db.add(m)
    conv.ultima_mensagem_em = agora()
    conv.nao_lidas = 0
    conv.primeira_resposta_em = conv.primeira_resposta_em or agora()
    contato.ultima_interacao = agora()
    db.commit()
    publicar_conversa(conv.id)
    barramento.publicar("mensagem", {"conversa_id": conv.id})
    return m


def nota_interna(db: Session, conv: Conversa, usuario: Usuario, texto: str) -> Mensagem:
    m = Mensagem(conversa_id=conv.id, direcao="interna", autor_tipo="humano", usuario_id=usuario.id, origem="crm",
                 texto=texto.strip(), processada_pelo_agente=True)
    db.add(m)
    db.commit()
    barramento.publicar("mensagem", {"conversa_id": conv.id})
    return m


def devolver_ao_agente(db: Session, conv: Conversa, usuario: Usuario | None, forcar: bool = False) -> None:
    if conv.contato.agente_bloqueado:
        raise ErroAtendimento("Este contato está configurado para atendimento só humano.", 409)
    estado = estado_do_agente(db, calcular_proxima=False)
    if not estado.ativo and not forcar:
        raise ErroAtendimento(f"O agente está desligado agora ({estado.motivo}).", 409)
    if conv.status != "aberta":
        reabrir(db, conv, usuario)
    nome = usuario.nome if usuario else "Sistema"
    mudar_modo(db, conv, MODO_AGENTE)
    marcar_pendentes_processadas(db, conv.id)  # o que o humano já tratou não é pergunta nova
    evento_sistema(db, conv, f"🤖 {nome} devolveu a conversa ao agente.", usuario)
    auditar(db, usuario, "conversa_devolvida_ao_agente", "conversa", conv.id)


def transferir(db: Session, conv: Conversa, usuario: Usuario, destino: Usuario) -> None:
    if not destino.ativo:
        raise ErroAtendimento("Colaborador inativo.")
    if conv.status != "aberta":
        reabrir(db, conv, usuario)
    mudar_modo(db, conv, MODO_HUMANO, atendente=destino)
    marcar_pendentes_processadas(db, conv.id)
    evento_sistema(db, conv, f"↪️ {usuario.nome} transferiu o atendimento para {destino.nome}.", usuario)
    auditar(db, usuario, "conversa_transferida", "conversa", conv.id, para=destino.id)


def enviar_para_fila(db: Session, conv: Conversa, usuario: Usuario, motivo: str = "Devolvida à fila") -> None:
    mudar_modo(db, conv, MODO_FILA, motivo=motivo)
    evento_sistema(db, conv, f"⏳ {usuario.nome} devolveu a conversa para a fila.", usuario)
    auditar(db, usuario, "conversa_para_fila", "conversa", conv.id)


def resolver(db: Session, conv: Conversa, usuario: Usuario) -> None:
    conv.status, conv.resolvida_em, conv.resolvida_por_id, conv.nao_lidas = "resolvida", agora(), usuario.id, 0
    cancelar_agendamento(conv.id)
    evento_sistema(db, conv, f"✅ Conversa resolvida por {usuario.nome}.", usuario)
    auditar(db, usuario, "conversa_resolvida", "conversa", conv.id)


def reabrir(db: Session, conv: Conversa, usuario: Usuario | None) -> None:
    aberta = conversa_aberta(db, conv.contato_id)
    if aberta and aberta.id != conv.id:
        raise ErroAtendimento("Este contato já tem outra conversa aberta.", 409)
    conv.status, conv.resolvida_em, conv.resolvida_por_id = "aberta", None, None
    evento_sistema(db, conv, f"🔄 Conversa reaberta por {usuario.nome if usuario else 'Sistema'}.", usuario)


async def iniciar_conversa(db: Session, contato: Contato, usuario: Usuario, texto: str) -> Conversa:
    conv = conversa_aberta(db, contato.id)
    if not conv:
        conv = Conversa(contato_id=contato.id, modo=MODO_HUMANO, atendente_id=usuario.id)
        db.add(conv)
        db.flush()
        evento_sistema(db, conv, f"Conversa iniciada por {usuario.nome}.", usuario)
    await enviar_humano(db, conv, usuario, texto)
    return conv


# ------------------------------------------------------------------ rotina de fundo
_ultimo_estado_agente: bool | None = None


async def rotina_periodica() -> None:
    """Liga/desliga o agente conforme a programação e devolve conversas paradas."""
    global _ultimo_estado_agente
    with sessao() as db:
        estado = estado_do_agente(db, calcular_proxima=False)
        cfg = ler_config(db)
        mudou = _ultimo_estado_agente is not None and estado.ativo != _ultimo_estado_agente
        retomar: list[int] = []
        if mudou:
            auditar(db, None, "agente_ligado" if estado.ativo else "agente_desligado", detalhes=estado.motivo)
            if estado.ativo:
                # assume a fila que chegou com o agente desligado (e que nenhum humano pegou)
                for conv in db.scalars(select(Conversa).where(Conversa.status == "aberta", Conversa.modo == MODO_FILA,
                                                              Conversa.atendente_id.is_(None))):
                    if (conv.motivo_fila or "").startswith(MOTIVO_FORA_HORARIO) and not conv.contato.agente_bloqueado:
                        mudar_modo(db, conv, MODO_AGENTE)
                        evento_sistema(db, conv, "🤖 Agente ligado pela programação — assumiu a conversa.")
                        retomar.append(conv.id)
            else:
                for conv in db.scalars(select(Conversa).where(Conversa.status == "aberta",
                                                              Conversa.modo == MODO_AGENTE)):
                    mudar_modo(db, conv, MODO_FILA, motivo=f"{MOTIVO_FORA_HORARIO} ({estado.motivo})")
                    evento_sistema(db, conv, "⏳ Agente desligado pela programação — conversa enviada para a fila.")
                    retomar.append(conv.id)
        _ultimo_estado_agente = estado.ativo

        minutos = int(cfg.get("devolver_ao_agente_min") or 0)
        if minutos > 0 and estado.ativo:
            limite = agora() - timedelta(minutes=minutos)
            for conv in db.scalars(select(Conversa).where(Conversa.status == "aberta", Conversa.modo == MODO_HUMANO,
                                                          Conversa.ultima_mensagem_em < limite)):
                if conv.contato.agente_bloqueado:
                    continue
                mudar_modo(db, conv, MODO_AGENTE)
                marcar_pendentes_processadas(db, conv.id)
                evento_sistema(db, conv, f"🤖 Sem interação humana há {minutos} min — conversa devolvida ao agente.")
                retomar.append(conv.id)
    if mudou:
        barramento.publicar("agente_status", {"ativo": estado.ativo, "motivo": estado.motivo})
    for cid in retomar:
        publicar_conversa(cid)
        with sessao() as db:
            conv = db.get(Conversa, cid)
            pendente = db.scalar(select(Mensagem.id).where(Mensagem.conversa_id == cid, Mensagem.direcao == "entrada",
                                                           Mensagem.processada_pelo_agente.is_(False)))
            if conv.modo == MODO_AGENTE and pendente:
                agendar_agente(cid, espera=1)
