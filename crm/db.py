"""Conexão com o banco (SQLAlchemy). SQLite por padrão; Postgres via CRM_BANCO."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import URL_BANCO

_eh_sqlite = URL_BANCO.startswith("sqlite")
motor = create_engine(
    URL_BANCO,
    connect_args={"check_same_thread": False, "timeout": 30} if _eh_sqlite else {},
)

if _eh_sqlite:
    @event.listens_for(motor, "connect")
    def _pragmas(conexao, _):  # noqa: ANN001
        c = conexao.cursor()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.close()

FabricaSessao = sessionmaker(bind=motor, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def obter_db() -> Iterator[Session]:
    """Dependência do FastAPI."""
    db = FabricaSessao()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def sessao() -> Iterator[Session]:
    db = FabricaSessao()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
