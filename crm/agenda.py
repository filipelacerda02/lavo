"""Ativação programada do agente.

Modos (configuração ``agente_modo``):
* ``ligado``     — o agente responde sempre;
* ``desligado``  — só humanos respondem;
* ``automatico`` — segue a grade semanal (HorarioAgente). Exceções pontuais
  (ExcecaoAgente: feriados, campanhas) vencem a grade enquanto estiverem valendo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .modelos import ExcecaoAgente, HorarioAgente, agora
from .preferencias import ler_config

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


@dataclass
class EstadoAgente:
    ativo: bool
    motivo: str
    modo: str
    proxima_mudanca: datetime | None = None


def _hm(texto: str) -> time:
    h, m = texto.split(":")
    return time(int(h), int(m))


def _na_grade(local: datetime, horarios: list[HorarioAgente]) -> bool:
    dia, hora = local.weekday(), local.time().replace(second=0, microsecond=0)
    ontem = (dia - 1) % 7
    for h in horarios:
        ini, fim = _hm(h.inicio), _hm(h.fim)
        if ini <= fim:  # mesma data (fim inclusivo no minuto: 08:00-18:00 vale até 18:00)
            if h.dia_semana == dia and ini <= hora <= fim:
                return True
        else:  # vira a meia-noite: 22:00-06:00
            if h.dia_semana == dia and hora >= ini:
                return True
            if h.dia_semana == ontem and hora <= fim:
                return True
    return False


def _avaliar(momento: datetime, modo: str, fuso: ZoneInfo, horarios: list[HorarioAgente],
             excecoes: list[ExcecaoAgente]) -> tuple[bool, str]:
    if modo == "ligado":
        return True, "ligado manualmente"
    if modo == "desligado":
        return False, "desligado manualmente"
    for e in excecoes:
        if e.inicio <= momento < e.fim:
            return e.agente_ativo, f"exceção: {e.descricao}"
    local = momento.astimezone(fuso)
    if _na_grade(local, horarios):
        return True, "dentro do horário programado"
    return False, "fora do horário programado"


def estado_do_agente(db: Session, momento: datetime | None = None, calcular_proxima: bool = True) -> EstadoAgente:
    momento = momento or agora()
    cfg = ler_config(db)
    modo, fuso = cfg["agente_modo"], ZoneInfo(cfg["fuso_horario"])
    horarios = db.query(HorarioAgente).all()
    excecoes = db.query(ExcecaoAgente).filter(ExcecaoAgente.fim > momento).all()
    ativo, motivo = _avaliar(momento, modo, fuso, horarios, excecoes)
    proxima = None
    if calcular_proxima and modo == "automatico":
        # procura a próxima virada nos próximos 8 dias (passo de 1 minuto)
        t = momento.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limite = momento + timedelta(days=8)
        while t < limite:
            if _avaliar(t, modo, fuso, horarios, excecoes)[0] != ativo:
                proxima = t
                break
            t += timedelta(minutes=1)
    return EstadoAgente(ativo=ativo, motivo=motivo, modo=modo, proxima_mudanca=proxima)
