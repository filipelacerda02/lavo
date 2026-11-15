"""Aplicação web do CRM.

    uvicorn crm.main:app --reload        # http://localhost:8000
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from . import atendimento
from .config import WHATSAPP_SIMULADO
from .db import Base, motor, sessao
from .eventos import barramento
from .modelos import EtapaFunil, Etiqueta, HorarioAgente, RespostaRapida, Usuario
from .rotas import administracao, auth, contatos, conversas, gestao
from .rotas.base import usuario_opcional

log = logging.getLogger("crm")
PASTA = Path(__file__).parent


def inicializar_banco() -> None:
    Base.metadata.create_all(motor)
    with sessao() as db:
        if not db.scalar(select(func.count(EtapaFunil.id))):
            for i, (nome, cor) in enumerate([("Novo lead", "#2a78d6"), ("Qualificado", "#1baf7a"),
                                             ("Proposta", "#eda100"), ("Negociação", "#eb6834"),
                                             ("Fechado", "#008300")]):
                db.add(EtapaFunil(nome=nome, cor=cor, ordem=i))
        if not db.scalar(select(func.count(HorarioAgente.id))):
            # padrão: agente ligado o tempo todo (ajuste em Configurações > Agente)
            for dia in range(7):
                db.add(HorarioAgente(dia_semana=dia, inicio="00:00", fim="23:59"))
        if not db.scalar(select(func.count(Etiqueta.id))):
            for nome, cor in [("VIP", "#6250d6"), ("Reclamação", "#e34948"), ("Novo cliente", "#1baf7a"),
                              ("Empresa", "#2a78d6")]:
                db.add(Etiqueta(nome=nome, cor=cor))
        if not db.scalar(select(func.count(RespostaRapida.id))):
            db.add(RespostaRapida(atalho="ola", texto="Olá! Aqui é da Lavo. Como posso ajudar?"))
            db.add(RespostaRapida(atalho="prazo", texto="Lavar e dobrar: 2 dias úteis. Lavar e passar: 3 dias úteis. "
                                                        "Lavagem a seco: 5 dias úteis."))
            db.add(RespostaRapida(atalho="obrigado", texto="Obrigado pelo contato! Qualquer coisa, é só chamar. 💙"))


async def _rotina() -> None:
    while True:
        try:
            await atendimento.rotina_periodica()
        except Exception:  # noqa: BLE001
            log.exception("falha na rotina periódica")
        await asyncio.sleep(30)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    inicializar_banco()
    barramento.vincular_loop(asyncio.get_running_loop())
    tarefa = asyncio.create_task(_rotina())
    # aquece o agente (indexa documentos) sem travar a subida do servidor
    if os.getenv("CRM_AQUECER_AGENTE", "1") == "1":
        asyncio.get_running_loop().run_in_executor(None, _aquecer)
    yield
    tarefa.cancel()


def _aquecer() -> None:
    try:
        atendimento.componentes()
    except Exception:  # noqa: BLE001
        log.exception("não foi possível preparar o agente (confira ANTHROPIC_API_KEY e embeddings)")


app = FastAPI(title="Lavo CRM", lifespan=ciclo_de_vida)
app.mount("/static", StaticFiles(directory=PASTA / "static"), name="static")
templates = Jinja2Templates(directory=PASTA / "templates")
for modulo in (auth, conversas, contatos, gestao, administracao):
    app.include_router(modulo.rotas)


@app.get("/api/eventos")
async def eventos(request: Request, u: Usuario | None = Depends(usuario_opcional)):
    if u is None:
        return HTMLResponse(status_code=401)
    fila = barramento.assinar()

    async def fluxo():
        try:
            yield "event: pronto\ndata: {}\n\n"
            while not await request.is_disconnected():
                try:
                    yield await asyncio.wait_for(fila.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # mantém a conexão viva
        finally:
            barramento.cancelar(fila)

    return StreamingResponse(fluxo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


PAGINAS = {
    "": ("painel.html", "Painel"),
    "conversas": ("conversas.html", "Conversas"),
    "contatos": ("contatos.html", "Contatos"),
    "funil": ("funil.html", "Funil"),
    "tarefas": ("tarefas.html", "Tarefas"),
    "relatorios": ("relatorios.html", "Relatórios"),
    "whatsapp": ("whatsapp.html", "WhatsApp"),
    "configuracoes": ("configuracoes.html", "Configurações"),
    "auditoria": ("auditoria.html", "Auditoria"),
}


def _sem_usuarios() -> bool:
    with sessao() as db:
        return db.scalar(select(func.count(Usuario.id))) == 0


@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request):
    if _sem_usuarios():
        return RedirectResponse("/setup")
    return templates.TemplateResponse(request, "login.html", {"modo": "login"})


@app.get("/setup", response_class=HTMLResponse)
def pagina_setup(request: Request):
    if not _sem_usuarios():
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "login.html", {"modo": "setup"})


@app.get("/{pagina}", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def pagina(request: Request, pagina: str = "", u: Usuario | None = Depends(usuario_opcional)):
    if pagina not in PAGINAS:
        return HTMLResponse("Página não encontrada", status_code=404)
    if u is None:
        return RedirectResponse("/setup" if _sem_usuarios() else "/login")
    if pagina in ("configuracoes", "auditoria") and u.papel == "atendente":
        return RedirectResponse("/")
    arquivo, titulo = PAGINAS[pagina]
    return templates.TemplateResponse(request, arquivo, {
        "usuario": u, "titulo": titulo, "pagina": pagina, "simulado": WHATSAPP_SIMULADO})
