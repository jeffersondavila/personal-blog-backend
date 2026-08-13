"""Acceso a PostgreSQL: base declarativa, motor y sesiones."""

from app.shared.database.base import NAMING_CONVENTION, Base
from app.shared.database.session import (
    dispose_engine,
    get_engine,
    get_session,
    get_sessionmaker,
    session_scope,
)

__all__ = [
    "NAMING_CONVENTION",
    "Base",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "session_scope",
]
