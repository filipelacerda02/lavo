"""Conversão dos modelos para JSON das telas."""

from __future__ import annotations

from typing import Any

from datetime import timedelta

from .modelos import Contato, Conversa, Mensagem, MensagemAgendada, Negocio, Tarefa, Usuario, agora


def iso(d: Any) -> str | None:
    return d.isoformat() if d else None


def usuario(u: Usuario | None) -> dict[str, Any] | None:
    if not u:
        return None
    conectado = bool(u.ultimo_sinal and agora() - u.ultimo_sinal < timedelta(minutes=2))
    return {"id": u.id, "nome": u.nome, "email": u.email, "papel": u.papel, "ativo": u.ativo, "cor": u.cor,
            "ultimo_acesso": iso(u.ultimo_acesso), "status": u.status or "offline", "conectado": conectado,
            "disponivel": conectado and u.status == "online", "max_conversas": u.max_conversas,
            "equipes": [{"id": e.id, "nome": e.nome, "cor": e.cor} for e in u.equipes]}


def contato(c: Contato) -> dict[str, Any]:
    return {
        "id": c.id, "nome": c.nome or c.telefone or "Sem nome", "telefone": c.telefone, "email": c.email,
        "empresa": c.empresa, "origem": c.origem, "observacoes": c.observacoes,
        "cliente_externo_id": c.cliente_externo_id, "agente_bloqueado": c.agente_bloqueado,
        "responsavel": usuario(c.responsavel), "responsavel_id": c.responsavel_id,
        "etiquetas": [{"id": e.id, "nome": e.nome, "cor": e.cor} for e in c.etiquetas],
        "criado_em": iso(c.criado_em), "ultima_interacao": iso(c.ultima_interacao),
        "tem_whatsapp": bool(c.whatsapp_jid or c.telefone),
        "campos_extras": c.campos_extras or {},
    }


def autor(m: Mensagem, nome_agente: str, c: Contato | None) -> dict[str, Any]:
    """Quem escreveu: o ponto central de 'agente x humano (e qual humano)'."""
    if m.autor_tipo == "contato":
        return {"tipo": "contato", "nome": (c.nome or c.telefone) if c else "Contato"}
    if m.autor_tipo == "agente":
        return {"tipo": "agente", "nome": nome_agente}
    if m.autor_tipo == "humano":
        if m.usuario:
            return {"tipo": "humano", "nome": m.usuario.nome, "usuario_id": m.usuario.id, "cor": m.usuario.cor,
                    "papel": m.usuario.papel}
        return {"tipo": "humano", "nome": "Celular da empresa", "usuario_id": None, "cor": "#52514e"}
    return {"tipo": "sistema", "nome": "Sistema"}


def mensagem(m: Mensagem, nome_agente: str, c: Contato | None = None) -> dict[str, Any]:
    return {
        "id": m.id, "conversa_id": m.conversa_id, "direcao": m.direcao, "origem": m.origem, "texto": m.texto,
        "midia": m.midia, "status_envio": m.status_envio, "erro": m.erro, "criada_em": iso(m.criada_em),
        "autor": autor(m, nome_agente, c), "trace_id": m.trace_id, "custo_usd": round(m.custo_usd or 0, 6),
    }


def conversa(cv: Conversa, ultima: Mensagem | None = None, nome_agente: str = "Agente",
             cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    if cv.status == "resolvida":
        responsavel = {"tipo": "resolvida", "nome": "Resolvida"}
    elif cv.modo == "agente":
        responsavel = {"tipo": "agente", "nome": nome_agente}
    elif cv.modo == "humano":
        responsavel = ({"tipo": "humano", "nome": cv.atendente.nome, "usuario_id": cv.atendente.id, "cor": cv.atendente.cor}
                       if cv.atendente else {"tipo": "humano", "nome": "Celular da empresa", "usuario_id": None})
    else:
        responsavel = {"tipo": "fila", "nome": "Aguardando atendente"}
    return {
        "id": cv.id, "status": cv.status, "modo": cv.modo, "motivo_fila": cv.motivo_fila,
        "atendente_id": cv.atendente_id, "responsavel": responsavel, "nao_lidas": cv.nao_lidas,
        "contato": contato(cv.contato), "criada_em": iso(cv.criada_em), "ultima_mensagem_em": iso(cv.ultima_mensagem_em),
        "modo_desde": iso(cv.modo_desde),
        "ultima_mensagem": mensagem(ultima, nome_agente, cv.contato) if ultima else None,
        "prioridade": cv.prioridade or "media", "categoria": cv.categoria, "resumo_ia": cv.resumo_ia,
        "equipe": {"id": cv.equipe.id, "nome": cv.equipe.nome, "cor": cv.equipe.cor} if cv.equipe else None,
        "csat": {"status": cv.csat_status, "nota": cv.csat_nota, "comentario": cv.csat_comentario} if cv.csat_status else None,
        "sla": _sla(cv, cfg) if cfg else None,
    }


def _sla(cv: Conversa, cfg: dict[str, Any]) -> dict[str, Any]:
    from .recursos import sla_da_conversa

    return sla_da_conversa(cv, cfg)


def agendada(a: MensagemAgendada) -> dict[str, Any]:
    return {"id": a.id, "conversa_id": a.conversa_id, "texto": a.texto, "enviar_em": iso(a.enviar_em),
            "status": a.status, "erro": a.erro, "criada_por": a.criada_por.nome if a.criada_por else None}


def negocio(n: Negocio) -> dict[str, Any]:
    return {"id": n.id, "titulo": n.titulo, "contato_id": n.contato_id,
            "contato_nome": (n.contato.nome or n.contato.telefone) if n.contato else None,
            "etapa_id": n.etapa_id, "valor": n.valor, "responsavel": usuario(n.responsavel),
            "responsavel_id": n.responsavel_id, "status": n.status, "previsao_fechamento": n.previsao_fechamento,
            "observacoes": n.observacoes, "ordem": n.ordem, "atualizado_em": iso(n.atualizado_em),
            "motivo_perda": n.motivo_perda, "etapa_desde": iso(n.etapa_desde)}


def tarefa(t: Tarefa) -> dict[str, Any]:
    return {"id": t.id, "titulo": t.titulo, "descricao": t.descricao, "contato_id": t.contato_id,
            "contato_nome": (t.contato.nome or t.contato.telefone) if t.contato else None,
            "conversa_id": t.conversa_id, "responsavel": usuario(t.responsavel), "responsavel_id": t.responsavel_id,
            "prioridade": t.prioridade, "vencimento": iso(t.vencimento), "concluida": t.concluida,
            "concluida_em": iso(t.concluida_em), "origem": t.origem, "criada_em": iso(t.criada_em)}
