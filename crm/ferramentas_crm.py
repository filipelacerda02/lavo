"""Ferramentas extras do agente quando ele atende pelo CRM/WhatsApp.

Além das ferramentas da Lavo (pedidos, assinatura...), o agente pode:
* identificar_cliente — vincular o número do WhatsApp ao cadastro (e-mail + CPF);
* transferir_para_humano — mandar a conversa para a fila da equipe;
* abrir_chamado — vira uma TAREFA no CRM, para a equipe resolver.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from lavo.ferramentas import DEFINICOES, ErroDeFerramenta, Ferramentas, _schema

from .db import sessao
from .eventos import barramento
from .modelos import MODO_FILA, Contato, Conversa, Mensagem, Tarefa, agora

DEFINICOES_CRM: list[dict[str, Any]] = [
    *[d for d in DEFINICOES if d["name"] != "abrir_chamado"],
    {
        "name": "abrir_chamado",
        "description": "Cria uma tarefa para a equipe humana resolver depois (danos, extravios, cobranças, pedidos especiais). Não transfere a conversa.",
        "input_schema": _schema({
            "assunto": {"type": "string"},
            "descricao": {"type": "string"},
            "prioridade": {"type": "string", "enum": ["baixa", "media", "alta"]},
        }),
        "strict": True,
    },
    {
        "name": "identificar_cliente",
        "description": "Vincula este número de WhatsApp ao cadastro do cliente. Use quando o cliente ainda não estiver identificado e precisar de dados da conta. Peça o e-mail e o CPF cadastrados; os dois precisam conferir.",
        "input_schema": _schema({"email": {"type": "string"}, "cpf": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "transferir_para_humano",
        "description": "Passa a conversa para a fila da equipe humana e para de responder nela. Use quando o cliente pedir para falar com uma pessoa, quando o assunto exigir decisão humana (dano, extravio, cobrança contestada, reclamação séria) ou quando você não conseguir resolver. Depois de transferir, avise o cliente em uma frase.",
        "input_schema": _schema({
            "motivo": {"type": "string", "description": "Por que precisa de um humano"},
            "resumo_para_atendente": {"type": "string", "description": "O que o cliente quer e o que já foi feito"},
        }),
        "strict": True,
    },
]


class FerramentasCRM(Ferramentas):
    definicoes = DEFINICOES_CRM

    def __init__(self, cliente_id: str | None, conversa_id: int, contato_id: int, **kw: Any) -> None:
        super().__init__(cliente_id, **kw)
        self.conversa_id = conversa_id
        self.contato_id = contato_id
        self.transferiu = False

    def _t_identificar_cliente(self, email: str, cpf: str) -> Any:
        digitos = re.sub(r"\D", "", cpf)
        for cid, c in self.loja.ler()["clientes"].items():
            if c["email"].lower() == email.strip().lower() and re.sub(r"\D", "", c["cpf"]) == digitos:
                self.cliente_id = cid
                with sessao() as db:
                    contato = db.get(Contato, self.contato_id)
                    contato.cliente_externo_id = cid
                    contato.email = contato.email or c["email"]
                    if not contato.nome or contato.nome == contato.telefone:
                        contato.nome = c["nome"]
                barramento.publicar("contato", {"id": self.contato_id})
                return {"identificado": True, "nome": c["nome"]}
        raise ErroDeFerramenta("Os dados não conferem com nenhum cadastro. Não revele detalhes; peça para conferir.")

    def _t_transferir_para_humano(self, motivo: str, resumo_para_atendente: str) -> Any:
        with sessao() as db:
            conv = db.get(Conversa, self.conversa_id)
            conv.modo, conv.motivo_fila, conv.atendente_id, conv.modo_desde = MODO_FILA, motivo, None, agora()
            db.add(Mensagem(conversa_id=conv.id, direcao="interna", autor_tipo="sistema", origem="agente",
                            texto=f"🤖 → 👤 Agente transferiu para a equipe. Motivo: {motivo}\nResumo: {resumo_para_atendente}"))
        self.transferiu = True
        barramento.publicar("conversa", {"id": self.conversa_id})
        return {"transferido": True, "instrucao": "Avise o cliente que um atendente vai continuar o atendimento."}

    def _t_abrir_chamado(self, assunto: str, descricao: str, prioridade: str) -> Any:
        with sessao() as db:
            t = Tarefa(titulo=f"[Agente] {assunto}", descricao=descricao, prioridade=prioridade,
                       contato_id=self.contato_id, conversa_id=self.conversa_id, origem="agente",
                       vencimento=agora() + timedelta(hours=4 if prioridade == "alta" else 24))
            db.add(t)
            db.flush()
            tid = t.id
        barramento.publicar("tarefa", {"id": tid})
        return {"chamado_id": f"T-{tid}", "prazo_resposta": "até 2 dias úteis (seg-sex, 9h-18h)"}
