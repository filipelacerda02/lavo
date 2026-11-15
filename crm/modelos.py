"""Tabelas do CRM."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def agora() -> datetime:
    return datetime.now(timezone.utc)


class DataHora(TypeDecorator):
    """DateTime sempre com fuso: grava em UTC e devolve com tzinfo (SQLite não guarda fuso)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, valor: Any, dialect) -> Any:  # noqa: ANN001
        if isinstance(valor, datetime):
            if valor.tzinfo is None:
                valor = valor.replace(tzinfo=timezone.utc)
            return valor.astimezone(timezone.utc).replace(tzinfo=None)
        return valor

    def process_result_value(self, valor: Any, dialect) -> Any:  # noqa: ANN001
        if isinstance(valor, datetime) and valor.tzinfo is None:
            return valor.replace(tzinfo=timezone.utc)
        return valor


# Papéis: admin (tudo), supervisor (atendimento + configuração do agente), atendente.
PAPEIS = ("admin", "supervisor", "atendente")


class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(300))
    papel: Mapped[str] = mapped_column(String(20), default="atendente")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    cor: Mapped[str] = mapped_column(String(9), default="#2a78d6")
    criado_em: Mapped[datetime] = mapped_column(DataHora(), default=agora)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    versao_sessao: Mapped[int] = mapped_column(Integer, default=1)  # muda => derruba sessões
    # Presença: online (recebe distribuição automática) | ausente | offline
    status: Mapped[str] = mapped_column(String(10), default="offline", server_default="offline")
    ultimo_sinal: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)  # tela aberta
    max_conversas: Mapped[int] = mapped_column(Integer, default=6, server_default="6")
    ultima_atribuicao: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)  # rodízio

    equipes: Mapped[list["Equipe"]] = relationship(secondary="usuario_equipes", lazy="selectin",
                                                   back_populates="membros")


usuario_equipes = Table(
    "usuario_equipes",
    Base.metadata,
    Column("usuario_id", ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
    Column("equipe_id", ForeignKey("equipes.id", ondelete="CASCADE"), primary_key=True),
)


class Equipe(Base):
    """Departamento/fila (ex.: Comercial, Suporte, Financeiro)."""

    __tablename__ = "equipes"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(60), unique=True)
    cor: Mapped[str] = mapped_column(String(9), default="#1baf7a")
    membros: Mapped[list[Usuario]] = relationship(secondary=usuario_equipes, lazy="selectin",
                                                  back_populates="equipes")


class CampoPersonalizado(Base):
    """Campo extra de contato definido pela empresa (ex.: Bairro, Plano de interesse)."""

    __tablename__ = "campos_personalizados"
    id: Mapped[int] = mapped_column(primary_key=True)
    chave: Mapped[str] = mapped_column(String(40), unique=True)
    rotulo: Mapped[str] = mapped_column(String(80))
    tipo: Mapped[str] = mapped_column(String(10), default="texto")  # texto | numero | data | opcao
    opcoes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0)


contato_etiquetas = Table(
    "contato_etiquetas",
    Base.metadata,
    Column("contato_id", ForeignKey("contatos.id", ondelete="CASCADE"), primary_key=True),
    Column("etiqueta_id", ForeignKey("etiquetas.id", ondelete="CASCADE"), primary_key=True),
)


class Etiqueta(Base):
    __tablename__ = "etiquetas"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(60), unique=True)
    cor: Mapped[str] = mapped_column(String(9), default="#6250d6")


class Contato(Base):
    __tablename__ = "contatos"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), default="")
    telefone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    whatsapp_jid: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    empresa: Mapped[str | None] = mapped_column(String(160), nullable=True)
    origem: Mapped[str] = mapped_column(String(40), default="whatsapp")
    observacoes: Mapped[str] = mapped_column(Text, default="")
    # Vínculo com o cadastro de clientes que as ferramentas do agente consultam
    cliente_externo_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    agente_bloqueado: Mapped[bool] = mapped_column(Boolean, default=False)  # só humanos atendem
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    campos_extras: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # valores dos CampoPersonalizado
    # Janela de 24h da Cloud API: conta a partir da última mensagem RECEBIDA do cliente
    ultima_entrada_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    # Consentimento para mensagens iniciadas pela empresa (exigido pela Meta e pela LGPD)
    opt_in: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    opt_in_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    opt_in_origem: Mapped[str | None] = mapped_column(String(80), nullable=True)
    opt_out_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DataHora(), default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DataHora(), default=agora, onupdate=agora)
    ultima_interacao: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)

    etiquetas: Mapped[list[Etiqueta]] = relationship(secondary=contato_etiquetas, lazy="selectin")
    responsavel: Mapped[Usuario | None] = relationship(lazy="joined")


# Modo da conversa = quem está respondendo agora.
MODO_AGENTE = "agente"   # o agente de IA responde
MODO_HUMANO = "humano"   # um colaborador assumiu (atendente_id) ou respondeu pelo celular
MODO_FILA = "fila"       # aguardando um humano (agente desligado, transferência, erro)


class Conversa(Base):
    __tablename__ = "conversas"
    id: Mapped[int] = mapped_column(primary_key=True)
    contato_id: Mapped[int] = mapped_column(ForeignKey("contatos.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="aberta", index=True)  # aberta | resolvida
    modo: Mapped[str] = mapped_column(String(20), default=MODO_AGENTE, index=True)
    motivo_fila: Mapped[str | None] = mapped_column(String(300), nullable=True)
    atendente_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    modo_desde: Mapped[datetime] = mapped_column(DataHora(), default=agora)
    historico_agente: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # estado lavo.Conversa
    nao_lidas: Mapped[int] = mapped_column(Integer, default=0)
    aviso_fora_horario_enviado: Mapped[bool] = mapped_column(Boolean, default=False)
    criada_em: Mapped[datetime] = mapped_column(DataHora(), default=agora)
    ultima_mensagem_em: Mapped[datetime] = mapped_column(DataHora(), default=agora, index=True)
    primeira_resposta_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    resolvida_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    resolvida_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    # baixa | media | alta | urgente — define os prazos de SLA
    prioridade: Mapped[str] = mapped_column(String(10), default="media", server_default="media")
    equipe_id: Mapped[int | None] = mapped_column(ForeignKey("equipes.id", ondelete="SET NULL"), nullable=True)
    categoria: Mapped[str | None] = mapped_column(String(30), nullable=True)  # triagem por IA
    resumo_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Pesquisa de satisfação: None | aguardando | respondida | expirada
    csat_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    csat_nota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    csat_comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    csat_solicitado_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)

    contato: Mapped[Contato] = relationship(lazy="joined")
    atendente: Mapped[Usuario | None] = relationship(foreign_keys=[atendente_id], lazy="joined")
    equipe: Mapped[Equipe | None] = relationship(lazy="joined")


class Mensagem(Base):
    __tablename__ = "mensagens"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversa_id: Mapped[int] = mapped_column(ForeignKey("conversas.id", ondelete="CASCADE"), index=True)
    # entrada (do contato) | saida (para o contato) | interna (nota ou evento, não enviada)
    direcao: Mapped[str] = mapped_column(String(10))
    # contato | agente | humano | sistema
    autor_tipo: Mapped[str] = mapped_column(String(10), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True, index=True)
    # whatsapp | crm | celular | agente | sistema
    origem: Mapped[str] = mapped_column(String(10), default="crm")
    texto: Mapped[str] = mapped_column(Text, default="")
    midia: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp_id: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    status_envio: Mapped[str] = mapped_column(String(10), default="enviada")  # pendente|enviada|erro
    erro: Mapped[str | None] = mapped_column(String(300), nullable=True)
    processada_pelo_agente: Mapped[bool] = mapped_column(Boolean, default=False)
    trace_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    custo_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # Cloud API: mídia, recibos e cobrança
    midia_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    midia_arquivo: Mapped[str | None] = mapped_column(String(200), nullable=True)  # nome do arquivo salvo
    midia_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    midia_nome: Mapped[str | None] = mapped_column(String(200), nullable=True)
    entregue_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    lida_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    cobranca: Mapped[str | None] = mapped_column(String(20), nullable=True)  # marketing | utility | service...
    modelo_nome: Mapped[str | None] = mapped_column(String(120), nullable=True)
    campanha_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    criada_em: Mapped[datetime] = mapped_column(DataHora(), default=agora, index=True)

    usuario: Mapped[Usuario | None] = relationship(lazy="joined")


class EtapaFunil(Base):
    __tablename__ = "etapas_funil"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(60))
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    cor: Mapped[str] = mapped_column(String(9), default="#2a78d6")
    dias_parado: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 0 = não alerta
    tarefa_automatica: Mapped[str | None] = mapped_column(String(200), nullable=True)  # criada ao entrar
    tarefa_prazo_dias: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class Negocio(Base):
    __tablename__ = "negocios"
    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(160))
    contato_id: Mapped[int | None] = mapped_column(ForeignKey("contatos.id", ondelete="SET NULL"), nullable=True)
    etapa_id: Mapped[int] = mapped_column(ForeignKey("etapas_funil.id"))
    valor: Mapped[float] = mapped_column(Float, default=0.0)
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="aberto")  # aberto | ganho | perdido
    previsao_fechamento: Mapped[str | None] = mapped_column(String(10), nullable=True)  # AAAA-MM-DD
    observacoes: Mapped[str] = mapped_column(Text, default="")
    motivo_perda: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    etapa_desde: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DataHora(), default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DataHora(), default=agora, onupdate=agora)

    contato: Mapped[Contato | None] = relationship(lazy="joined")
    responsavel: Mapped[Usuario | None] = relationship(lazy="joined")


class Tarefa(Base):
    __tablename__ = "tarefas"
    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(200))
    descricao: Mapped[str] = mapped_column(Text, default="")
    contato_id: Mapped[int | None] = mapped_column(ForeignKey("contatos.id", ondelete="CASCADE"), nullable=True)
    conversa_id: Mapped[int | None] = mapped_column(ForeignKey("conversas.id", ondelete="SET NULL"), nullable=True)
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    prioridade: Mapped[str] = mapped_column(String(10), default="media")
    vencimento: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    concluida: Mapped[bool] = mapped_column(Boolean, default=False)
    concluida_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    criada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    origem: Mapped[str] = mapped_column(String(10), default="manual")  # manual | agente
    criada_em: Mapped[datetime] = mapped_column(DataHora(), default=agora)

    contato: Mapped[Contato | None] = relationship(lazy="joined")
    responsavel: Mapped[Usuario | None] = relationship(foreign_keys=[responsavel_id], lazy="joined")


class MensagemAgendada(Base):
    """Follow-up que um colaborador programa para sair numa data/hora."""

    __tablename__ = "mensagens_agendadas"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversa_id: Mapped[int] = mapped_column(ForeignKey("conversas.id", ondelete="CASCADE"), index=True)
    texto: Mapped[str] = mapped_column(Text)
    enviar_em: Mapped[datetime] = mapped_column(DataHora(), index=True)
    criada_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    status: Mapped[str] = mapped_column(String(10), default="pendente")  # pendente|enviada|cancelada|erro
    erro: Mapped[str | None] = mapped_column(String(300), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DataHora(), default=agora)
    # Fora da janela de 24h só sai modelo: se preenchido, envia o modelo em vez do texto
    modelo_id: Mapped[int | None] = mapped_column(ForeignKey("modelos_mensagem.id", ondelete="SET NULL"), nullable=True)
    parametros: Mapped[list | None] = mapped_column(JSON, nullable=True)

    criada_por: Mapped[Usuario] = relationship(lazy="joined")


class ModeloMensagem(Base):
    """Modelo (template) do WhatsApp: cópia local do que está na conta da Meta."""

    __tablename__ = "modelos_mensagem"
    __table_args__ = (UniqueConstraint("nome", "idioma"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    meta_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    nome: Mapped[str] = mapped_column(String(120))
    idioma: Mapped[str] = mapped_column(String(10), default="pt_BR")
    categoria: Mapped[str] = mapped_column(String(20), default="UTILITY")  # MARKETING | UTILITY | AUTHENTICATION
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # APPROVED | PENDING | REJECTED | PAUSED...
    componentes: Mapped[list] = mapped_column(JSON, default=list)
    motivo_rejeicao: Mapped[str | None] = mapped_column(String(300), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DataHora(), default=agora, onupdate=agora)


class Campanha(Base):
    """Disparo de um modelo para contatos com opt-in (filtrados por etiqueta)."""

    __tablename__ = "campanhas"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    modelo_id: Mapped[int] = mapped_column(ForeignKey("modelos_mensagem.id"))
    # variáveis do corpo, em ordem: {"tipo": "campo", "valor": "nome"} ou {"tipo": "texto", "valor": "..."}
    variaveis: Mapped[list] = mapped_column(JSON, default=list)
    etiqueta_ids: Mapped[list] = mapped_column(JSON, default=list)  # vazio = todos com opt-in
    agendada_para: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="rascunho")  # rascunho|agendada|enviando|concluida|cancelada
    por_minuto: Mapped[int] = mapped_column(Integer, default=60)
    criada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DataHora(), default=agora)
    concluida_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)

    modelo: Mapped[ModeloMensagem] = relationship(lazy="joined")
    criada_por: Mapped[Usuario | None] = relationship(lazy="joined")


class CampanhaEnvio(Base):
    __tablename__ = "campanha_envios"
    __table_args__ = (UniqueConstraint("campanha_id", "contato_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campanha_id: Mapped[int] = mapped_column(ForeignKey("campanhas.id", ondelete="CASCADE"), index=True)
    contato_id: Mapped[int] = mapped_column(ForeignKey("contatos.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(12), default="pendente")  # pendente|enviada|entregue|lida|respondida|erro|ignorado
    whatsapp_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    erro: Mapped[str | None] = mapped_column(String(300), nullable=True)
    enviada_em: Mapped[datetime | None] = mapped_column(DataHora(), nullable=True)

    contato: Mapped[Contato] = relationship(lazy="joined")


class RespostaRapida(Base):
    __tablename__ = "respostas_rapidas"
    id: Mapped[int] = mapped_column(primary_key=True)
    atalho: Mapped[str] = mapped_column(String(40), unique=True)
    texto: Mapped[str] = mapped_column(Text)


class Configuracao(Base):
    __tablename__ = "configuracoes"
    chave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[Any] = mapped_column(JSON)


class HorarioAgente(Base):
    """Janela semanal em que o agente fica LIGADO (modo automático)."""

    __tablename__ = "horarios_agente"
    id: Mapped[int] = mapped_column(primary_key=True)
    dia_semana: Mapped[int] = mapped_column(Integer)  # 0 = segunda ... 6 = domingo
    inicio: Mapped[str] = mapped_column(String(5))   # HH:MM
    fim: Mapped[str] = mapped_column(String(5))      # HH:MM (menor que início = passa da meia-noite)


class ExcecaoAgente(Base):
    """Período pontual que vence a grade semanal (feriado, campanha, manutenção)."""

    __tablename__ = "excecoes_agente"
    id: Mapped[int] = mapped_column(primary_key=True)
    descricao: Mapped[str] = mapped_column(String(160))
    inicio: Mapped[datetime] = mapped_column(DataHora())
    fim: Mapped[datetime] = mapped_column(DataHora())
    agente_ativo: Mapped[bool] = mapped_column(Boolean)


class Auditoria(Base):
    __tablename__ = "auditoria"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    acao: Mapped[str] = mapped_column(String(60), index=True)
    entidade: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entidade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detalhes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DataHora(), default=agora, index=True)

    usuario: Mapped[Usuario | None] = relationship(lazy="joined")


__all__ = [
    "Auditoria", "CampoPersonalizado", "Configuracao", "Contato", "Conversa", "Equipe", "Etiqueta", "EtapaFunil",
    "ExcecaoAgente", "HorarioAgente", "Mensagem", "MensagemAgendada", "ModeloMensagem", "Campanha", "CampanhaEnvio",
    "Negocio", "RespostaRapida", "Tarefa", "Usuario", "UniqueConstraint",
    "MODO_AGENTE", "MODO_FILA", "MODO_HUMANO", "PAPEIS", "agora",
]
