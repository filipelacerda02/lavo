"""Modelos (templates), campanhas, consentimento e recibos — regras da API oficial.

* Modelo: única forma de falar com o cliente fora da janela de 24h. Precisa estar APROVADO
  pela Meta. Variáveis posicionais {{1}}, {{2}}… no corpo (e opcionalmente no cabeçalho).
* Campanha: um modelo enviado para contatos com OPT-IN, filtrados por etiqueta, num ritmo
  controlado (mensagens por minuto), com métricas de enviada/entregue/lida/respondida.
* Opt-out: o cliente responde SAIR/PARAR (ou toca no botão de descadastro) e deixa de
  receber campanhas; VOLTAR reativa.
* Recibos: os webhooks de status atualizam cada mensagem (✓ enviada, ✓✓ entregue, ✓✓ lida).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import whatsapp
from .db import sessao
from .eventos import barramento
from .modelos import (
    MODO_HUMANO,
    Campanha,
    CampanhaEnvio,
    Contato,
    Conversa,
    Mensagem,
    ModeloMensagem,
    Usuario,
    agora,
    contato_etiquetas,
)

log = logging.getLogger("crm.campanhas")

PALAVRAS_SAIR = {"sair", "parar", "stop", "descadastrar", "cancelar inscricao", "nao quero mais receber",
                 "parar promocoes", "nao quero receber"}
PALAVRAS_VOLTAR = {"voltar", "quero receber", "start"}
ORDEM_STATUS = ["pendente", "enviada", "entregue", "lida", "respondida"]


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", "", texto).strip()


def intencao_consentimento(texto: str, botao: str | None = None) -> str | None:
    """'sair' | 'voltar' | None. Só a mensagem inteira conta (evita 'quero sair de casa às 8h')."""
    t = _norm(texto)
    if t in PALAVRAS_SAIR or (botao and _norm(botao) in PALAVRAS_SAIR):
        return "sair"
    if t in PALAVRAS_VOLTAR:
        return "voltar"
    return None


# ------------------------------------------------------------------ modelos
def componente(modelo: ModeloMensagem, tipo: str) -> dict[str, Any] | None:
    return next((c for c in modelo.componentes or [] if c.get("type", "").upper() == tipo), None)


def qtd_variaveis(texto: str | None) -> int:
    nums = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", texto or "")]
    return max(nums) if nums else 0


def variaveis_do_modelo(modelo: ModeloMensagem) -> dict[str, int]:
    cab = componente(modelo, "HEADER")
    return {"corpo": qtd_variaveis((componente(modelo, "BODY") or {}).get("text")),
            "cabecalho": qtd_variaveis(cab.get("text")) if cab and cab.get("format", "TEXT") == "TEXT" else 0}


def renderizar(modelo: ModeloMensagem, corpo: list[str], cabecalho: list[str] | None = None) -> str:
    """Texto do modelo com as variáveis preenchidas (para mostrar no histórico)."""
    def sub(texto: str, valores: list[str]) -> str:
        return re.sub(r"\{\{(\d+)\}\}", lambda m: valores[int(m.group(1)) - 1] if int(m.group(1)) <= len(valores)
                      else m.group(0), texto or "")

    partes = []
    cab = componente(modelo, "HEADER")
    if cab and cab.get("text"):
        partes.append(f"*{sub(cab['text'], cabecalho or [])}*")
    partes.append(sub((componente(modelo, "BODY") or {}).get("text", ""), corpo))
    rodape = componente(modelo, "FOOTER")
    if rodape and rodape.get("text"):
        partes.append(f"_{rodape['text']}_")
    botoes = componente(modelo, "BUTTONS")
    if botoes:
        partes.append(" ".join(f"[{b.get('text')}]" for b in botoes.get("buttons", [])))
    return "\n".join(partes)


def validar_parametros(modelo: ModeloMensagem, corpo: list[str], cabecalho: list[str] | None) -> None:
    if modelo.status != "APPROVED":
        raise ValueError(f"O modelo '{modelo.nome}' não está aprovado pela Meta (status {modelo.status}).")
    n = variaveis_do_modelo(modelo)
    if len(corpo) != n["corpo"] or len(cabecalho or []) != n["cabecalho"]:
        raise ValueError(f"O modelo espera {n['corpo']} variável(is) no corpo e {n['cabecalho']} no cabeçalho.")
    if any(not str(v).strip() for v in [*corpo, *(cabecalho or [])]):
        raise ValueError("Preencha todas as variáveis do modelo.")


def valor_do_campo(contato: Contato, campo: str) -> str:
    if campo == "nome":
        return (contato.nome or "").split(" ")[0] or "cliente"
    if campo == "nome_completo":
        return contato.nome or "cliente"
    if campo in ("email", "empresa", "telefone"):
        return getattr(contato, campo) or ""
    return str((contato.campos_extras or {}).get(campo, "") or "")


def sincronizar_modelos(db: Session, remotos: list[dict[str, Any]]) -> int:
    vistos = set()
    for r in remotos:
        m = db.scalar(select(ModeloMensagem).where(ModeloMensagem.nome == r["name"],
                                                   ModeloMensagem.idioma == r["language"]))
        if not m:
            m = ModeloMensagem(nome=r["name"], idioma=r["language"])
            db.add(m)
        m.meta_id, m.status, m.categoria = r.get("id"), r.get("status", "PENDING"), r.get("category", "UTILITY")
        m.componentes, m.motivo_rejeicao = r.get("components", []), r.get("rejected_reason")
        vistos.add((m.nome, m.idioma))
    return len(vistos)


# ------------------------------------------------------------------ envio de modelo para um contato
async def enviar_modelo_para_contato(db: Session, contato: Contato, modelo: ModeloMensagem, corpo: list[str],
                                     cabecalho: list[str] | None = None, usuario: Usuario | None = None,
                                     campanha: Campanha | None = None) -> Mensagem:
    """Envia o modelo e registra no histórico. Humano: abre/assume a conversa. Campanha: só registra."""
    from .atendimento import conversa_aberta, evento_sistema, mudar_modo

    validar_parametros(modelo, corpo, cabecalho)
    destino = contato.whatsapp_jid or contato.telefone
    if not destino:
        raise ValueError("Contato sem telefone de WhatsApp.")
    if contato.opt_out_em and modelo.categoria == "MARKETING":
        raise ValueError("O contato pediu para não receber mensagens de marketing.")
    conv = conversa_aberta(db, contato.id)
    if conv is None:
        ultima = db.scalar(select(Conversa).where(Conversa.contato_id == contato.id).order_by(Conversa.id.desc()))
        if campanha and ultima:
            conv = ultima  # campanha não abre conversa: a resposta do cliente é que abre
        else:
            conv = Conversa(contato_id=contato.id, modo=MODO_HUMANO if usuario else "agente",
                            atendente_id=usuario.id if usuario else None,
                            status="aberta" if usuario else "resolvida", resolvida_em=None if usuario else agora())
            db.add(conv)
            db.flush()
            if usuario:
                evento_sistema(db, conv, f"Conversa iniciada por {usuario.nome} com o modelo '{modelo.nome}'.", usuario)
    elif usuario and (conv.modo != MODO_HUMANO or conv.atendente_id != usuario.id):
        mudar_modo(db, conv, MODO_HUMANO, atendente=usuario)
        evento_sistema(db, conv, f"👤 {usuario.nome} assumiu o atendimento.", usuario)
    try:
        wid, erro = await whatsapp.enviar_modelo(destino, modelo.nome, modelo.idioma, corpo, cabecalho), None
    except whatsapp.ErroWhatsapp as e:
        wid, erro = None, str(e)
    m = Mensagem(conversa_id=conv.id, direcao="saida", autor_tipo="humano" if usuario else "sistema",
                 usuario_id=usuario.id if usuario else None, origem="campanha" if campanha else "modelo",
                 texto=renderizar(modelo, corpo, cabecalho), whatsapp_id=wid, status_envio="erro" if erro else "enviada",
                 erro=erro, processada_pelo_agente=True, modelo_nome=modelo.nome,
                 campanha_id=campanha.id if campanha else None)
    db.add(m)
    if usuario:
        conv.ultima_mensagem_em = agora()
    db.flush()
    barramento.publicar("mensagem", {"conversa_id": conv.id})
    barramento.publicar("conversa", {"id": conv.id})
    if erro and not campanha:
        raise whatsapp.ErroWhatsapp(erro)
    return m


# ------------------------------------------------------------------ recibos (webhook de status)
def atualizar_status(st: dict[str, Any]) -> None:
    if not st.get("id"):
        return
    with sessao() as db:
        m = db.scalar(select(Mensagem).where(Mensagem.whatsapp_id == st["id"]))
        if m:
            momento = agora()
            if st["status"] == "delivered":
                m.entregue_em = m.entregue_em or momento
            elif st["status"] == "read":
                m.entregue_em = m.entregue_em or momento
                m.lida_em = m.lida_em or momento
            elif st["status"] == "failed":
                m.status_envio, m.erro = "erro", (st.get("erro") or "Falha na entrega")[:300]
            if st.get("categoria"):
                m.cobranca = st["categoria"]
            conv_id = m.conversa_id
        envio = db.scalar(select(CampanhaEnvio).where(CampanhaEnvio.whatsapp_id == st["id"]))
        if envio:
            novo = {"sent": "enviada", "delivered": "entregue", "read": "lida", "failed": "erro"}.get(st["status"])
            if novo == "erro":
                envio.status, envio.erro = "erro", (st.get("erro") or "")[:300]
            elif novo and envio.status in ORDEM_STATUS and ORDEM_STATUS.index(novo) > ORDEM_STATUS.index(envio.status):
                envio.status = novo
    if m:
        barramento.publicar("recibo", {"conversa_id": conv_id, "mensagem_id": m.id})


def registrar_resposta_campanha(db: Session, contato_id: int) -> None:
    limite = agora() - timedelta(hours=72)
    for envio in db.scalars(select(CampanhaEnvio).where(CampanhaEnvio.contato_id == contato_id,
                                                        CampanhaEnvio.enviada_em >= limite,
                                                        CampanhaEnvio.status.in_(["enviada", "entregue", "lida"]))):
        envio.status = "respondida"


# ------------------------------------------------------------------ campanhas
def publico(db: Session, campanha: Campanha) -> list[Contato]:
    """Contatos com opt-in, sem opt-out, com telefone; filtrados pelas etiquetas (qualquer uma)."""
    q = select(Contato).where(Contato.opt_in.is_(True), Contato.opt_out_em.is_(None), Contato.telefone.is_not(None))
    if campanha.etiqueta_ids:
        q = q.join(contato_etiquetas).where(contato_etiquetas.c.etiqueta_id.in_(campanha.etiqueta_ids))
    return list(db.scalars(q).unique())


def parametros_para(campanha: Campanha, contato: Contato) -> list[str]:
    return [valor_do_campo(contato, v["valor"]) if v.get("tipo") == "campo" else str(v.get("valor", ""))
            for v in campanha.variaveis or []]


async def processar_campanhas() -> int:
    """Chamado pela rotina: inicia campanhas agendadas e envia o próximo lote respeitando o ritmo."""
    enviados = 0
    with sessao() as db:
        for c in db.scalars(select(Campanha).where(Campanha.status == "agendada",
                                                   Campanha.agendada_para <= agora())):
            c.status = "enviando"
            for contato in publico(db, c):
                db.add(CampanhaEnvio(campanha_id=c.id, contato_id=contato.id))
            barramento.publicar("campanha", {"id": c.id})
        ativas = [c.id for c in db.scalars(select(Campanha).where(Campanha.status == "enviando"))]
    for campanha_id in ativas:
        with sessao() as db:
            c = db.get(Campanha, campanha_id)
            lote = max(1, (c.por_minuto or 60) // 2)  # a rotina roda a cada ~30 s
            pendentes = list(db.scalars(select(CampanhaEnvio).where(CampanhaEnvio.campanha_id == c.id,
                                                                    CampanhaEnvio.status == "pendente").limit(lote)))
            for envio in pendentes:
                contato = envio.contato
                if not contato.opt_in or contato.opt_out_em:  # mudou de ideia depois do agendamento
                    envio.status = "ignorado"
                    continue
                try:
                    m = await enviar_modelo_para_contato(db, contato, c.modelo, parametros_para(c, contato), campanha=c)
                    envio.whatsapp_id, envio.enviada_em = m.whatsapp_id, agora()
                    envio.status, envio.erro = ("erro", m.erro) if m.status_envio == "erro" else ("enviada", None)
                    enviados += 1
                except ValueError as e:
                    envio.status, envio.erro = "erro", str(e)[:300]
            restantes = db.scalar(select(CampanhaEnvio.id).where(CampanhaEnvio.campanha_id == c.id,
                                                                 CampanhaEnvio.status == "pendente"))
            if not restantes:
                c.status, c.concluida_em = "concluida", agora()
        barramento.publicar("campanha", {"id": campanha_id})
    return enviados


def metricas(db: Session, campanha_id: int) -> dict[str, int]:
    contagem = {s: 0 for s in ["pendente", "enviada", "entregue", "lida", "respondida", "erro", "ignorado"]}
    for (status,) in db.execute(select(CampanhaEnvio.status).where(CampanhaEnvio.campanha_id == campanha_id)):
        contagem[status] = contagem.get(status, 0) + 1
    total = sum(contagem.values())
    # funil acumulado: lida conta como entregue, respondida conta como lida etc.
    acum = {"enviadas": contagem["enviada"] + contagem["entregue"] + contagem["lida"] + contagem["respondida"]}
    acum["entregues"] = acum["enviadas"] - contagem["enviada"]
    acum["lidas"] = contagem["lida"] + contagem["respondida"]
    acum["respondidas"] = contagem["respondida"]
    return {"total": total, **contagem, **acum}
