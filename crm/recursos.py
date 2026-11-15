"""Recursos de CRM de mercado em volta do atendimento.

* Distribuição automática da fila (rodízio entre colaboradores online, por equipe,
  respeitando o limite de conversas simultâneas) — como Digisac/Chatwoot.
* SLA por prioridade: espera na fila e prazo de resolução — como Chatwoot/HubSpot.
* Pesquisa de satisfação (CSAT 1–5) ao resolver — como Digisac/Chatwoot.
* Mensagens agendadas (follow-up) e encerramento de conversas inativas.
* Triagem automática por IA (prioridade e assunto) — como o Captain do Chatwoot.
* Funil: negócio automático para contato novo, tarefa automática por etapa — como
  Kommo/RD Station; negócio parado ("rotting") — como Pipedrive.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import whatsapp
from .db import sessao
from .eventos import barramento
from .modelos import (
    MODO_FILA,
    MODO_HUMANO,
    Contato,
    Conversa,
    EtapaFunil,
    Mensagem,
    MensagemAgendada,
    Negocio,
    Tarefa,
    Usuario,
    agora,
)
from .preferencias import PRIORIDADES, ler_config

log = logging.getLogger("crm.recursos")
PRESENCA_MAX = timedelta(minutes=2)  # sem tela aberta há mais que isso = indisponível


def notificar(tipo: str, texto: str, conversa_id: int | None = None, usuario_id: int | None = None) -> None:
    """Notificação para o navegador (usuario_id=None: todos)."""
    barramento.publicar("notificacao", {"tipo": tipo, "texto": texto, "conversa_id": conversa_id,
                                        "usuario_id": usuario_id})


# ------------------------------------------------------------------ SLA
def sla_da_conversa(conv: Conversa, cfg: dict[str, Any], momento: datetime | None = None) -> dict[str, Any]:
    momento = momento or agora()
    prazos = cfg["sla"].get(conv.prioridade or "media", cfg["sla"]["media"])
    info: dict[str, Any] = {"prioridade": conv.prioridade or "media"}
    if conv.status == "aberta" and conv.modo == MODO_FILA:
        vence = conv.modo_desde + timedelta(minutes=prazos["fila_min"])
        info["fila"] = {"vence_em": vence.isoformat(), "estourado": momento > vence}
    if conv.status == "aberta":
        vence = conv.criada_em + timedelta(hours=prazos["resolucao_h"])
        info["resolucao"] = {"vence_em": vence.isoformat(), "estourado": momento > vence}
    elif conv.resolvida_em:
        info["resolvida_no_prazo"] = conv.resolvida_em <= conv.criada_em + timedelta(hours=prazos["resolucao_h"])
    return info


# ------------------------------------------------------------------ distribuição
def disponiveis(db: Session, equipe_id: int | None) -> list[tuple[Usuario, int]]:
    """Colaboradores online, com a tela aberta e abaixo do limite, por carga (menor primeiro)."""
    limite_sinal = agora() - PRESENCA_MAX
    carga = dict(db.execute(select(Conversa.atendente_id, func.count()).where(
        Conversa.status == "aberta", Conversa.modo == MODO_HUMANO).group_by(Conversa.atendente_id)).all())
    candidatos = []
    for u in db.scalars(select(Usuario).where(Usuario.ativo.is_(True), Usuario.status == "online")):
        if not u.ultimo_sinal or u.ultimo_sinal < limite_sinal:
            continue
        if equipe_id and equipe_id not in {e.id for e in u.equipes}:
            continue
        atual = carga.get(u.id, 0)
        if atual < (u.max_conversas or 1):
            candidatos.append((u, atual))
    # menor carga; empate: quem recebeu há mais tempo (rodízio)
    candidatos.sort(key=lambda par: (par[1], par[0].ultima_atribuicao or datetime.min.replace(tzinfo=agora().tzinfo)))
    return candidatos


def distribuir_fila(evitar: dict[int, int] | None = None) -> list[int]:
    """Atribui conversas da fila (prioridade mais alta e mais antigas primeiro).

    ``evitar``: {conversa_id: usuario_id} — não devolve a conversa a quem acabou de soltá-la.
    """
    from .atendimento import evento_sistema, marcar_pendentes_processadas, mudar_modo

    atribuidas: list[tuple[int, int, str]] = []
    with sessao() as db:
        if not ler_config(db)["distribuicao_automatica"]:
            return []
        fila = list(db.scalars(select(Conversa).where(Conversa.status == "aberta", Conversa.modo == MODO_FILA)))
        fila.sort(key=lambda c: (-PRIORIDADES.index(c.prioridade or "media"), c.modo_desde))
        for conv in fila:
            opcoes = [par for par in disponiveis(db, conv.equipe_id) if (evitar or {}).get(conv.id) != par[0].id]
            if not opcoes:
                continue
            usuario = opcoes[0][0]
            mudar_modo(db, conv, MODO_HUMANO, atendente=usuario)
            marcar_pendentes_processadas(db, conv.id)
            usuario.ultima_atribuicao = agora()
            evento_sistema(db, conv, f"📥 Distribuída automaticamente para {usuario.nome}"
                           + (f" (equipe {conv.equipe.nome})" if conv.equipe else "") + ".")
            db.flush()
            atribuidas.append((conv.id, usuario.id, conv.contato.nome or conv.contato.telefone or "contato"))
    for conv_id, usuario_id, nome in atribuidas:
        barramento.publicar("conversa", {"id": conv_id})
        notificar("atribuida", f"Nova conversa para você: {nome}", conv_id, usuario_id)
    return [c for c, _, _ in atribuidas]


# ------------------------------------------------------------------ CSAT
RE_NOTA = re.compile(r"^\s*(?:nota\s*)?([1-5])(?:\s*(?:/\s*5|estrelas?|⭐+))?\s*[.!,;:-]?\s*(.*)$", re.I | re.S)


async def solicitar_csat(conv_id: int) -> None:
    with sessao() as db:
        cfg = ler_config(db)
        conv = db.get(Conversa, conv_id)
        if not cfg["csat_ativo"] or not conv or conv.csat_status:
            return
        teve_humano = db.scalar(select(Mensagem.id).where(Mensagem.conversa_id == conv_id,
                                                          Mensagem.autor_tipo == "humano", Mensagem.direcao == "saida"))
        teve_resposta = db.scalar(select(Mensagem.id).where(Mensagem.conversa_id == conv_id, Mensagem.direcao == "saida",
                                                            Mensagem.autor_tipo.in_(["humano", "agente"])))
        if not teve_resposta or (not teve_humano and not cfg["csat_conversas_agente"]):
            return
        contato = conv.contato
        jid = contato.whatsapp_jid or (whatsapp.jid_de_telefone(contato.telefone) if contato.telefone else None)
        if not jid or not whatsapp.janela_aberta(contato.ultima_entrada_em):
            return  # fora da janela de 24h a pesquisa exigiria um modelo pago: não envia
        conv.csat_status, conv.csat_solicitado_em = "aguardando", agora()
        texto = cfg["csat_mensagem"]
    from .atendimento import _enviar_automatico

    await _enviar_automatico(conv_id, jid, texto)
    barramento.publicar("mensagem", {"conversa_id": conv_id})


async def tratar_resposta_csat(contato_id: int, texto: str) -> int | None:
    """Se o contato respondeu a pesquisa, registra a nota e retorna o id da conversa."""
    with sessao() as db:
        conv = db.scalar(select(Conversa).where(Conversa.contato_id == contato_id, Conversa.csat_status == "aguardando")
                         .order_by(Conversa.id.desc()))
        if not conv:
            return None
        aberta = db.scalar(select(Conversa.id).where(Conversa.contato_id == contato_id, Conversa.status == "aberta"))
        if aberta:
            return None  # "5" pode ser resposta a outra pergunta da conversa em andamento
        if agora() - (conv.csat_solicitado_em or agora()) > timedelta(hours=24):
            conv.csat_status = "expirada"
            return None
        m = RE_NOTA.match(texto or "")
        if not m:
            conv.csat_status = "expirada"  # respondeu outra coisa: segue como conversa nova
            return None
        conv.csat_status, conv.csat_nota = "respondida", int(m.group(1))
        conv.csat_comentario = (m.group(2) or "").strip() or None
        db.add(Mensagem(conversa_id=conv.id, direcao="entrada", autor_tipo="contato", origem="whatsapp",
                        texto=texto, processada_pelo_agente=True))
        cfg = ler_config(db)
        contato = conv.contato
        jid = contato.whatsapp_jid or whatsapp.jid_de_telefone(contato.telefone or "")
        conv_id, nota = conv.id, conv.csat_nota
    from .atendimento import _enviar_automatico

    if cfg.get("csat_agradecimento"):
        await _enviar_automatico(conv_id, jid, cfg["csat_agradecimento"])
    barramento.publicar("conversa", {"id": conv_id})
    barramento.publicar("mensagem", {"conversa_id": conv_id})
    if nota <= 2:
        notificar("csat_baixo", f"Avaliação {nota}/5 de {contato.nome or contato.telefone}", conv_id)
    return conv_id


# ------------------------------------------------------------------ triagem por IA
def triagem_ia(conv_id: int, texto: str) -> None:
    """Roda em thread: classifica prioridade/assunto da conversa nova (não bloqueia nada)."""
    from .atendimento import componentes, evento_sistema
    from lavo.saida_estruturada import triar

    try:
        llm, _ = componentes()
        t = triar(texto, llm)
    except Exception:  # noqa: BLE001 - triagem é opcional
        log.warning("triagem falhou para a conversa %s", conv_id, exc_info=True)
        return
    with sessao() as db:
        conv = db.get(Conversa, conv_id)
        if not conv:
            return
        conv.categoria = t.categoria
        nova = {"alta": "alta", "media": "media", "baixa": "baixa"}[t.urgencia]
        if t.urgencia == "alta" and t.sentimento == "negativo" and t.precisa_humano:
            nova = "urgente"
        if PRIORIDADES.index(nova) > PRIORIDADES.index(conv.prioridade or "media"):
            conv.prioridade = nova  # só aumenta; nunca desfaz uma escolha humana
        evento_sistema(db, conv, f"✨ Triagem IA: {t.categoria.replace('_', ' ')} · urgência {t.urgencia} · {t.resumo}")
    barramento.publicar("conversa", {"id": conv_id})


# ------------------------------------------------------------------ funil
def criar_negocio_lead(db: Session, contato: Contato) -> Negocio | None:
    etapa = db.scalar(select(EtapaFunil).order_by(EtapaFunil.ordem, EtapaFunil.id).limit(1))
    if not etapa:
        return None
    n = Negocio(titulo=f"Lead WhatsApp — {contato.nome or contato.telefone}", contato_id=contato.id,
                etapa_id=etapa.id, etapa_desde=agora())
    db.add(n)
    db.flush()
    aplicar_regra_etapa(db, n, etapa)
    barramento.publicar("funil", {"id": n.id})
    return n


def aplicar_regra_etapa(db: Session, negocio: Negocio, etapa: EtapaFunil) -> None:
    """Tarefa automática ao entrar na etapa (sequência de follow-up do funil)."""
    if etapa.tarefa_automatica:
        db.add(Tarefa(titulo=f"{etapa.tarefa_automatica} — {negocio.titulo}", contato_id=negocio.contato_id,
                      responsavel_id=negocio.responsavel_id, origem="funil",
                      vencimento=agora() + timedelta(days=etapa.tarefa_prazo_dias or 1)))
        barramento.publicar("tarefa", {})


def negocio_parado(n: Negocio, etapa: EtapaFunil | None, momento: datetime | None = None) -> int | None:
    """Dias parado na etapa, se passou do limite da etapa."""
    if not etapa or not etapa.dias_parado or n.status != "aberto":
        return None
    desde = n.etapa_desde or n.criado_em  # tempo parado na etapa atual
    dias = ((momento or agora()) - desde).days
    return dias if dias >= etapa.dias_parado else None


# ------------------------------------------------------------------ rotinas
async def enviar_agendadas() -> int:
    from .atendimento import ErroAtendimento, iniciar_conversa

    enviadas = 0
    with sessao() as db:
        ids = list(db.scalars(select(MensagemAgendada.id).where(MensagemAgendada.status == "pendente",
                                                                MensagemAgendada.enviar_em <= agora())))
    for ag_id in ids:
        with sessao() as db:
            ag = db.get(MensagemAgendada, ag_id)
            if not ag or ag.status != "pendente":
                continue
            conv = db.get(Conversa, ag.conversa_id)
            try:
                if whatsapp.janela_aberta(conv.contato.ultima_entrada_em):
                    await iniciar_conversa(db, conv.contato, ag.criada_por, ag.texto)
                elif ag.modelo_id:
                    from .campanhas import enviar_modelo_para_contato
                    from .modelos import ModeloMensagem

                    await enviar_modelo_para_contato(db, conv.contato, db.get(ModeloMensagem, ag.modelo_id),
                                                     list(ag.parametros or []), usuario=ag.criada_por)
                else:
                    raise ErroAtendimento("Janela de 24h fechada no horário do envio e o agendamento não tem modelo.")
                ag.status = "enviada"
                enviadas += 1
            except (ErroAtendimento, whatsapp.ErroWhatsapp, ValueError) as e:
                db.rollback()
                ag = db.get(MensagemAgendada, ag_id)
                ag.status, ag.erro = "erro", str(e)[:300]
    return enviadas


async def resolver_inativas() -> list[int]:
    """Resolve conversas em que respondemos e o cliente sumiu há N horas."""
    from .atendimento import resolver

    resolvidas: list[int] = []
    with sessao() as db:
        horas = int(ler_config(db)["resolver_inativas_h"] or 0)
        if horas <= 0:
            return []
        limite = agora() - timedelta(hours=horas)
        for conv in db.scalars(select(Conversa).where(Conversa.status == "aberta", Conversa.modo != MODO_FILA,
                                                      Conversa.ultima_mensagem_em < limite)):
            ultima = db.scalar(select(Mensagem).where(Mensagem.conversa_id == conv.id, Mensagem.direcao != "interna")
                               .order_by(Mensagem.id.desc()).limit(1))
            if ultima and ultima.direcao == "saida":
                resolver(db, conv, None, motivo=f"sem resposta do cliente há {horas} h")
                resolvidas.append(conv.id)
    for cid in resolvidas:
        barramento.publicar("conversa", {"id": cid})
        await solicitar_csat(cid)
    return resolvidas


async def rotina() -> None:
    from .campanhas import processar_campanhas

    await enviar_agendadas()
    await processar_campanhas()
    await resolver_inativas()
    await asyncio.to_thread(distribuir_fila)
