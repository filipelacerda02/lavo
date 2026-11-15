"""Eventos em tempo real (Server-Sent Events) para todas as telas abertas.

Pode ser chamado de qualquer thread (o agente roda em threads).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class Barramento:
    def __init__(self) -> None:
        self._filas: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def vincular_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def assinar(self) -> asyncio.Queue[str]:
        fila: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
        self._filas.add(fila)
        return fila

    def cancelar(self, fila: asyncio.Queue[str]) -> None:
        self._filas.discard(fila)

    def _entregar(self, mensagem: str) -> None:
        for fila in list(self._filas):
            try:
                fila.put_nowait(mensagem)
            except asyncio.QueueFull:  # tela travada: descarta para não segurar as outras
                self._filas.discard(fila)

    def publicar(self, tipo: str, dados: Any = None) -> None:
        mensagem = f"event: {tipo}\ndata: {json.dumps(dados, ensure_ascii=False, default=str)}\n\n"
        if self._loop is None:
            return
        try:
            em_loop = asyncio.get_running_loop() is self._loop
        except RuntimeError:
            em_loop = False
        if em_loop:
            self._entregar(mensagem)
        else:
            self._loop.call_soon_threadsafe(self._entregar, mensagem)


barramento = Barramento()
