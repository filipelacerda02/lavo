"""Chat no terminal com streaming.

    python -m lavo.cli --cliente cli_ana

Comandos: /sair, /nova (zera a conversa), /trace (mostra o último trace)
"""

from __future__ import annotations

import argparse

from .agente import Agente
from .conversa import Conversa
from .observabilidade import _main as mostrar_trace


def main() -> None:
    ap = argparse.ArgumentParser(description="Converse com o agente da Lavo")
    ap.add_argument("--cliente", default="cli_ana", help="id do cliente logado (veja dados/clientes.json)")
    args = ap.parse_args()

    agente = Agente(args.cliente)
    print("Indexando documentos...", end=" ", flush=True)
    print(agente.rag.indexar())
    print(f"Olá, {agente.ferramentas.cliente['nome']}! (/sair, /nova, /trace)\n")

    ultimo = None
    while True:
        try:
            pergunta = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not pergunta:
            continue
        if pergunta == "/sair":
            break
        if pergunta == "/nova":
            agente.conversa = Conversa(cliente_id=args.cliente)
            print("(conversa nova)\n")
            continue
        if pergunta == "/trace":
            if ultimo:
                mostrar_trace([ultimo])
            continue
        print("lavo> ", end="", flush=True)
        r = agente.responder(pergunta, ao_receber_texto=lambda t: print(t, end="", flush=True))
        ultimo = r.trace_id
        extras = f"modelo={r.modelo} passos={r.passos} custo=${r.custo_usd:.5f} trace={r.trace_id}"
        if r.ferramentas_usadas:
            extras += f" ferramentas={','.join(r.ferramentas_usadas)}"
        if r.motivos_guardrail:
            extras += f" guardrail={r.motivos_guardrail}"
        print(f"\n\033[2m[{extras}]\033[0m\n")


if __name__ == "__main__":
    main()
