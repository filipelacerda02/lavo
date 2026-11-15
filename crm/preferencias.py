"""Configurações chave/valor com padrões."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .modelos import Configuracao

PADROES: dict[str, Any] = {
    "agente_modo": "automatico",          # automatico | ligado | desligado
    "fuso_horario": "America/Sao_Paulo",
    "agente_nome": "Assistente Lavo",
    "espera_agrupar_s": 4,                # junta mensagens enviadas em sequência antes de responder
    "devolver_ao_agente_min": 0,          # 0 = nunca; senão, conversa humana parada volta ao agente
    "mensagem_fora_horario": (
        "Olá! Recebemos sua mensagem. Nosso time responde de segunda a sexta, das 9h às 18h, "
        "e vai falar com você assim que possível."
    ),
    "mensagem_transferencia": "",         # opcional: texto extra quando o agente transfere
    # ----- atendimento humano
    "distribuicao_automatica": True,      # fila -> colaborador online com menos conversas (rodízio)
    "sla": {                              # prazos por prioridade: espera na fila (min) e resolução (h)
        "urgente": {"fila_min": 5, "resolucao_h": 4},
        "alta": {"fila_min": 15, "resolucao_h": 8},
        "media": {"fila_min": 30, "resolucao_h": 24},
        "baixa": {"fila_min": 120, "resolucao_h": 72},
    },
    "resolver_inativas_h": 12,            # resolve conversas em que o cliente não responde há N h (0 = nunca)
                                          # (menos de 24 h: a pesquisa de satisfação ainda cabe na janela)
    # ----- pesquisa de satisfação (CSAT)
    "csat_ativo": True,
    "csat_conversas_agente": True,        # também pergunta quando só o agente atendeu
    "csat_mensagem": "Antes de ir: de 1 a 5, que nota você dá para o nosso atendimento? Responda só com o número. 🙂",
    "csat_agradecimento": "Obrigado pela avaliação! 💙",
    # ----- IA e funil
    "triagem_ia": True,                   # classifica prioridade/assunto das conversas novas
    "criar_negocio_novo_contato": False,  # contato novo do WhatsApp vira negócio na 1ª etapa do funil
}

PRIORIDADES = ("baixa", "media", "alta", "urgente")


def ler_config(db: Session) -> dict[str, Any]:
    valores = dict(PADROES)
    for c in db.query(Configuracao).all():
        valores[c.chave] = c.valor
    return valores


def salvar_config(db: Session, alteracoes: dict[str, Any]) -> dict[str, Any]:
    for chave, valor in alteracoes.items():
        if chave not in PADROES:
            raise KeyError(chave)
        item = db.get(Configuracao, chave)
        if item:
            item.valor = valor
        else:
            db.add(Configuracao(chave=chave, valor=valor))
    db.commit()
    return ler_config(db)
