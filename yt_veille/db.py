"""Accès à la base de données (moteur, sessions, création des tables)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

_settings = get_settings()

# `future=True` est le mode SQLAlchemy 2.0.
# `check_same_thread=False` n'est utile que pour SQLite.
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    _settings.database_url,
    future=True,
    connect_args=_connect_args,
    # Indispensable avec Neon : le calcul s'endort et ferme les connexions.
    # `pool_pre_ping` teste la connexion avant usage et la recrée si besoin ;
    # `pool_recycle` force le renouvellement des connexions anciennes.
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def init_db() -> None:
    """Crée les tables si elles n'existent pas encore."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Ouvre une session et la ferme proprement (avec commit/rollback)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
