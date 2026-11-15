"""Peça 5 — TOOL CALLING (chamada de funções).

"O usuário pede 'cancela meu pedido', e o modelo só sabe escrever texto. Então
você descreve funções que o modelo pode pedir pro seu código rodar."

O modelo NÃO executa nada: ele pede (bloco ``tool_use``), o seu código valida e
executa, e devolve o resultado (``tool_result``).

Regras de segurança aplicadas aqui (parte dos guardrails):
* O ``cliente_id`` vem da sessão autenticada, nunca de um argumento do modelo.
* Toda ferramenta só enxerga dados do próprio cliente.
* Ações irreversíveis (encerrar assinatura) exigem ``confirmado_pelo_cliente``.
* Os argumentos são validados de novo antes de executar.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from .config import config
from .guardrails import verificar_documento
from .observabilidade import span

PLANOS = {"Essencial": 149.90, "Família": 289.90, "Premium": 449.90}
PERIODOS = ["manha", "tarde", "noite"]
SERVICOS = ["lavar e dobrar", "lavar e passar", "lavagem a seco", "edredom", "tenis"]


def _schema(propriedades: dict[str, Any], obrigatorios: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": propriedades,
        "required": obrigatorios if obrigatorios is not None else list(propriedades),
        "additionalProperties": False,
    }


# Ordem fixa e determinística: mudar a lista invalida o cache de prompt.
DEFINICOES: list[dict[str, Any]] = [
    {
        "name": "buscar_na_base_de_conhecimento",
        "description": "Busca trechos nos documentos oficiais da Lavo (planos, preços, prazos, políticas de encerramento, reembolso, danos). Use sempre que precisar de uma regra ou valor que não esteja nos documentos já fornecidos.",
        "input_schema": _schema({"consulta": {"type": "string", "description": "O que procurar, em linguagem natural"}}),
    },
    {
        "name": "consultar_assinatura",
        "description": "Mostra o plano, o status, o valor e a data de renovação da assinatura do cliente logado, e quantas peças restam no mês.",
        "input_schema": _schema({}),
    },
    {
        "name": "listar_pedidos",
        "description": "Lista os pedidos do cliente logado, do mais recente para o mais antigo.",
        "input_schema": _schema({}),
    },
    {
        "name": "consultar_pedido",
        "description": "Detalhes de um pedido do cliente logado: status, serviço, peças, previsão de entrega.",
        "input_schema": _schema({"pedido_id": {"type": "string", "description": "Ex.: PED-1042"}}),
    },
    {
        "name": "cancelar_pedido",
        "description": "Desmarca um pedido do cliente logado. Só é possível enquanto o status for 'aguardando_coleta'.",
        "input_schema": _schema({
            "pedido_id": {"type": "string"},
            "motivo": {"type": "string", "description": "Motivo informado pelo cliente"},
        }),
    },
    {
        "name": "agendar_coleta",
        "description": "Cria um pedido novo com coleta agendada para o cliente logado.",
        "input_schema": _schema({
            "data": {"type": "string", "format": "date", "description": "AAAA-MM-DD, de segunda a sábado"},
            "periodo": {"type": "string", "enum": PERIODOS},
            "servico": {"type": "string", "enum": SERVICOS},
            "pecas_estimadas": {"type": "integer"},
        }),
    },
    {
        "name": "alterar_plano",
        "description": "Troca o plano da assinatura do cliente logado. Confirme o novo plano e o valor com o cliente antes.",
        "input_schema": _schema({
            "novo_plano": {"type": "string", "enum": list(PLANOS)},
            "confirmado_pelo_cliente": {"type": "boolean"},
        }),
    },
    {
        "name": "encerrar_assinatura",
        "description": "Encerra a assinatura do cliente logado ao fim do ciclo pago. Ação irreversível: só chame com confirmado_pelo_cliente=true depois que o cliente confirmou explicitamente nesta conversa.",
        "input_schema": _schema({
            "motivo": {"type": "string"},
            "confirmado_pelo_cliente": {"type": "boolean"},
        }),
    },
    {
        "name": "abrir_chamado",
        "description": "Abre um chamado para o atendimento humano (danos, extravios, cobranças, reclamações ou quando você não conseguir resolver).",
        "input_schema": _schema({
            "assunto": {"type": "string"},
            "descricao": {"type": "string"},
            "prioridade": {"type": "string", "enum": ["baixa", "media", "alta"]},
        }),
    },
]

for _d in DEFINICOES:
    _d["strict"] = True  # argumentos sempre no schema


class ErroDeFerramenta(Exception):
    """Erro esperado: vira tool_result com is_error=True para o modelo se corrigir."""


class Loja:
    """'Banco de dados' de exemplo em JSON. Troque pela sua API/banco real."""

    _trava = threading.Lock()

    def __init__(self, caminho: Path | None = None) -> None:
        self.caminho = caminho or config.dados_clientes

    def ler(self) -> dict[str, Any]:
        return json.loads(self.caminho.read_text(encoding="utf-8"))

    def alterar(self, funcao: Callable[[dict[str, Any]], Any]) -> Any:
        with self._trava:
            dados = self.ler()
            resultado = funcao(dados)
            self.caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
            return resultado


class Ferramentas:
    def __init__(self, cliente_id: str | None, loja: Loja | None = None, rag: Any | None = None) -> None:
        # cliente_id=None: contato ainda não identificado (ex.: número novo no WhatsApp).
        self.cliente_id = cliente_id
        self.loja = loja or Loja()
        self.rag = rag
        if cliente_id is not None and cliente_id not in self.loja.ler()["clientes"]:
            raise ValueError(f"cliente desconhecido: {cliente_id}")

    definicoes = DEFINICOES

    # ---------------------------------------------------------------- dados do cliente
    @property
    def cliente(self) -> dict[str, Any]:
        if self.cliente_id is None:
            raise ErroDeFerramenta(
                "Cliente não identificado. Peça os dados de identificação ou transfira para um atendente."
            )
        return self.loja.ler()["clientes"][self.cliente_id]

    def nome_cliente(self, padrao: str = "não identificado") -> str:
        return self.cliente["nome"] if self.cliente_id else padrao

    def dados_pessoais_permitidos(self) -> list[str]:
        if self.cliente_id is None:
            return []
        c = self.cliente
        return [c["email"], c["cpf"], c["telefone"]]

    def _pedido_do_cliente(self, dados: dict[str, Any], pedido_id: str) -> dict[str, Any]:
        pedido = dados["pedidos"].get(pedido_id.strip().upper())
        self.cliente  # exige cliente identificado
        # Mesmo erro para "não existe" e "é de outro cliente": não revela nada.
        if not pedido or pedido["cliente_id"] != self.cliente_id:
            raise ErroDeFerramenta(f"Pedido {pedido_id} não encontrado para este cliente.")
        return pedido

    # ---------------------------------------------------------------- execução
    def executar(self, nome: str, entrada: dict[str, Any]) -> tuple[str, bool]:
        """Retorna (conteúdo, é_erro). Nunca levanta exceção para o loop do agente."""
        with span(f"tool.{nome}", "ferramenta", entrada=entrada) as s:
            funcao = getattr(self, f"_t_{nome}", None)
            if funcao is None or not isinstance(entrada, dict):
                resultado, erro = f"Ferramenta inválida: {nome}", True
            else:
                try:
                    resultado, erro = json.dumps(funcao(**entrada), ensure_ascii=False, default=str), False
                except ErroDeFerramenta as e:
                    resultado, erro = str(e), True
                except TypeError as e:  # argumentos fora do schema
                    resultado, erro = f"Argumentos inválidos: {e}", True
            # Resultado de ferramenta também é dado não confiável (injeção indireta).
            if not erro and verificar_documento(resultado).bloqueado:
                resultado, erro = "Resultado descartado pelo guardrail (conteúdo suspeito).", True
            s.registrar(resultado=resultado, erro=erro)
            return resultado, erro

    # ---------------------------------------------------------------- ferramentas
    def _t_buscar_na_base_de_conhecimento(self, consulta: str) -> Any:
        if self.rag is None:
            raise ErroDeFerramenta("Base de conhecimento indisponível.")
        from .rag import formatar_contexto

        return formatar_contexto(self.rag.buscar(consulta))

    def _t_consultar_assinatura(self) -> Any:
        c = self.cliente
        return {"nome": c["nome"], **c["assinatura"]}

    def _t_listar_pedidos(self) -> Any:
        self.cliente  # exige cliente identificado
        pedidos = [
            {"pedido_id": pid, **{k: v for k, v in p.items() if k != "cliente_id"}}
            for pid, p in self.loja.ler()["pedidos"].items()
            if p["cliente_id"] == self.cliente_id
        ]
        return sorted(pedidos, key=lambda p: p["criado_em"], reverse=True)

    def _t_consultar_pedido(self, pedido_id: str) -> Any:
        p = self._pedido_do_cliente(self.loja.ler(), pedido_id)
        return {"pedido_id": pedido_id.upper(), **{k: v for k, v in p.items() if k != "cliente_id"}}

    def _t_cancelar_pedido(self, pedido_id: str, motivo: str) -> Any:
        def alterar(dados: dict[str, Any]) -> Any:
            p = self._pedido_do_cliente(dados, pedido_id)
            if p["status"] != "aguardando_coleta":
                raise ErroDeFerramenta(
                    f"O pedido {pedido_id} está com status '{p['status']}' e não pode mais ser desmarcado. "
                    "Ofereça abrir um chamado para o atendimento humano."
                )
            p["status"] = "cancelado"
            p["motivo_cancelamento"] = motivo
            return {"pedido_id": pedido_id.upper(), "status": "cancelado"}

        return self.loja.alterar(alterar)

    def _t_agendar_coleta(self, data: str, periodo: str, servico: str, pecas_estimadas: int) -> Any:
        self.cliente  # exige cliente identificado
        try:
            dia = date.fromisoformat(data)
        except ValueError as e:
            raise ErroDeFerramenta("Data inválida, use AAAA-MM-DD.") from e
        if dia <= date.today():
            raise ErroDeFerramenta("A coleta precisa ser a partir de amanhã.")
        if dia.weekday() == 6:
            raise ErroDeFerramenta("Não há coletas aos domingos.")
        if periodo not in PERIODOS or servico not in SERVICOS:
            raise ErroDeFerramenta("Período ou serviço inválido.")
        if not 1 <= pecas_estimadas <= 200:
            raise ErroDeFerramenta("Quantidade de peças deve ficar entre 1 e 200.")

        def alterar(dados: dict[str, Any]) -> Any:
            pid = f"PED-{uuid.uuid4().hex[:4].upper()}"
            dados["pedidos"][pid] = {
                "cliente_id": self.cliente_id, "status": "aguardando_coleta", "servico": servico,
                "pecas": pecas_estimadas, "criado_em": date.today().isoformat(),
                "coleta": {"data": data, "periodo": periodo}, "previsao_entrega": None, "valor": None,
            }
            return {"pedido_id": pid, "coleta": f"{data} ({periodo})", "servico": servico}

        return self.loja.alterar(alterar)

    def _t_alterar_plano(self, novo_plano: str, confirmado_pelo_cliente: bool) -> Any:
        self.cliente  # exige cliente identificado
        if novo_plano not in PLANOS:
            raise ErroDeFerramenta(f"Plano inexistente. Opções: {', '.join(PLANOS)}.")
        if not confirmado_pelo_cliente:
            raise ErroDeFerramenta("Confirme com o cliente o novo plano e o valor antes de alterar.")

        def alterar(dados: dict[str, Any]) -> Any:
            a = dados["clientes"][self.cliente_id]["assinatura"]
            anterior = a["plano"]
            if anterior == novo_plano:
                raise ErroDeFerramenta(f"O cliente já está no plano {novo_plano}.")
            subindo = PLANOS[novo_plano] > PLANOS.get(anterior, 0)
            a.update(plano=novo_plano, valor_mensal=PLANOS[novo_plano], status="ativa")
            return {"plano_anterior": anterior, "novo_plano": novo_plano, "valor_mensal": PLANOS[novo_plano],
                    "vale_a_partir_de": "agora (cobrança proporcional)" if subindo else "próximo ciclo"}

        return self.loja.alterar(alterar)

    def _t_encerrar_assinatura(self, motivo: str, confirmado_pelo_cliente: bool) -> Any:
        self.cliente  # exige cliente identificado
        if not confirmado_pelo_cliente:
            raise ErroDeFerramenta(
                "Ação irreversível: pergunte ao cliente se ele confirma o encerramento antes de chamar de novo."
            )

        def alterar(dados: dict[str, Any]) -> Any:
            a = dados["clientes"][self.cliente_id]["assinatura"]
            if a["status"] != "ativa":
                raise ErroDeFerramenta(f"Não há assinatura ativa (status atual: {a['status']}).")
            a["status"] = "encerramento_agendado"
            a["motivo_encerramento"] = motivo
            return {"status": "encerramento_agendado", "valida_ate": a["renova_em"],
                    "observacao": "Sem novas cobranças; peças restantes podem ser usadas até essa data."}

        return self.loja.alterar(alterar)

    def _t_abrir_chamado(self, assunto: str, descricao: str, prioridade: str) -> Any:
        def alterar(dados: dict[str, Any]) -> Any:
            cid = f"CH-{uuid.uuid4().hex[:6].upper()}"
            dados["chamados"].append({
                "id": cid, "cliente_id": self.cliente_id, "assunto": assunto, "descricao": descricao,
                "prioridade": prioridade, "aberto_em": datetime.now().isoformat(timespec="seconds"),
            })
            return {"chamado_id": cid, "prazo_resposta": "até 2 dias úteis (seg-sex, 9h-18h)"}

        return self.loja.alterar(alterar)
