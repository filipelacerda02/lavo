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
}


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
