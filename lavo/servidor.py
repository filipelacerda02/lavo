"""API HTTP com streaming (Server-Sent Events) + uma página de chat simples.

    uvicorn lavo.servidor:app --reload      # e abra http://localhost:8000

Endpoints:
  POST /chat      {"mensagem": "...", "conversa_id": null}   -> SSE (texto em pedaços + evento final)
  POST /triagem   {"mensagem": "..."}                         -> JSON validado (structured output)

AVISO: o cliente logado vem do header ``X-Cliente-Id`` só para demonstração.
Em produção, tire o id do token de autenticação da sessão.
"""

from __future__ import annotations

import json
import queue
import re
import threading
from dataclasses import asdict
from typing import Iterator

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from .agente import Agente
from .config import RAIZ
from .conversa import Conversa
from .ferramentas import Loja
from .llm import LLM
from .observabilidade import novo_trace
from .rag import RAG
from .saida_estruturada import Triagem, triar

PASTA_CONVERSAS = RAIZ / ".conversas"
app = FastAPI(title="Lavo — agente de IA")
_llm = LLM()
_rag = RAG()
_rag.indexar()


class PedidoChat(BaseModel):
    mensagem: str
    conversa_id: str | None = None


class PedidoTriagem(BaseModel):
    mensagem: str


def _cliente(x_cliente_id: str | None) -> str:
    if not x_cliente_id or x_cliente_id not in Loja().ler()["clientes"]:
        raise HTTPException(401, "cliente não autenticado")
    return x_cliente_id


def _sse(evento: str, dados: object) -> str:
    return f"event: {evento}\ndata: {json.dumps(dados, ensure_ascii=False)}\n\n"


@app.post("/chat")
def chat(p: PedidoChat, x_cliente_id: str | None = Header(default=None)) -> StreamingResponse:
    cliente_id = _cliente(x_cliente_id)
    conversa = None
    if p.conversa_id:
        if not re.fullmatch(r"[0-9a-f]{12}", p.conversa_id):
            raise HTTPException(400, "conversa_id inválido")
        conversa = Conversa.carregar(PASTA_CONVERSAS, p.conversa_id)
        if conversa and conversa.cliente_id != cliente_id:
            raise HTTPException(404, "conversa não encontrada")
    conversa = conversa or Conversa(cliente_id=cliente_id)
    agente = Agente(cliente_id, llm=_llm, rag=_rag, conversa=conversa)

    fila: queue.Queue[tuple[str, object] | None] = queue.Queue()

    def trabalhar() -> None:
        try:
            r = agente.responder(p.mensagem, ao_receber_texto=lambda t: fila.put(("texto", t)))
            conversa.salvar(PASTA_CONVERSAS)
            fila.put(("fim", {**asdict(r), "conversa_id": conversa.id}))
        except Exception as e:  # noqa: BLE001
            fila.put(("erro", {"mensagem": "Não foi possível responder agora.", "detalhe": type(e).__name__}))
        finally:
            fila.put(None)

    threading.Thread(target=trabalhar, daemon=True).start()

    def eventos() -> Iterator[str]:
        while (item := fila.get()) is not None:
            yield _sse(*item)

    return StreamingResponse(eventos(), media_type="text/event-stream")


@app.post("/triagem", response_model=Triagem)
def endpoint_triagem(p: PedidoTriagem) -> Triagem:
    with novo_trace("triagem", pergunta=p.mensagem):
        return triar(p.mensagem, _llm)


PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Lavo</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:720px;margin:0 auto;padding:16px;background:#f6f7f9;color:#1d2330}
 #log{display:flex;flex-direction:column;gap:10px;margin:16px 0}
 .m{padding:10px 14px;border-radius:12px;white-space:pre-wrap;line-height:1.45}
 .u{align-self:flex-end;background:#2453d6;color:#fff}.a{align-self:flex-start;background:#fff;border:1px solid #dde1e8}
 .meta{font-size:12px;color:#6b7383;margin-top:4px}
 form{display:flex;gap:8px}input,select,button{font:inherit;padding:10px;border-radius:10px;border:1px solid #c9ced8}
 input{flex:1;min-width:0}button{background:#2453d6;color:#fff;border:0}
</style></head><body>
<h2>Lavo — assistente</h2>
<label>Cliente: <select id="cli"><option>cli_ana</option><option>cli_bruno</option><option>cli_carla</option></select></label>
<div id="log"></div>
<form id="f"><input id="q" placeholder="Pergunte algo..." autocomplete="off"><button>Enviar</button></form>
<script>
let conversa=null;const log=document.getElementById('log');
document.getElementById('cli').onchange=()=>{conversa=null;log.innerHTML=''};
function bolha(c,t){const d=document.createElement('div');d.className='m '+c;d.textContent=t;log.appendChild(d);return d}
document.getElementById('f').onsubmit=async e=>{
 e.preventDefault();const q=document.getElementById('q');const msg=q.value.trim();if(!msg)return;q.value='';
 bolha('u',msg);const a=bolha('a','');
 const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json','X-Cliente-Id':document.getElementById('cli').value},
   body:JSON.stringify({mensagem:msg,conversa_id:conversa})});
 const rd=r.body.getReader();const dec=new TextDecoder();let buf='';
 while(true){const {value,done}=await rd.read();if(done)break;buf+=dec.decode(value,{stream:true});
  let i;while((i=buf.indexOf('\\n\\n'))>=0){const bloco=buf.slice(0,i);buf=buf.slice(i+2);
   const ev=(bloco.match(/^event: (.*)$/m)||[])[1];const dado=JSON.parse((bloco.match(/^data: (.*)$/m)||[])[1]||'null');
   if(ev==='texto')a.textContent+=dado;
   if(ev==='erro')a.textContent=dado.mensagem;
   if(ev==='fim'){conversa=dado.conversa_id;const m=document.createElement('div');m.className='meta';
     m.textContent=`${dado.modelo||''} · ${dado.passos} passo(s) · $${dado.custo_usd.toFixed(5)} · trace ${dado.trace_id}`+
       (dado.ferramentas_usadas.length?` · ferramentas: ${dado.ferramentas_usadas.join(', ')}`:'');a.appendChild(m)}
  }}
};
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def pagina() -> str:
    return PAGINA
