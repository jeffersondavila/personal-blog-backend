"""Entorno de ejecucion de Alembic.

La URL de conexion **no** se lee de `alembic.ini`, sino de la configuracion
tipada de la aplicacion: asi existe una sola fuente de configuracion y ninguna
credencial acaba en un archivo versionado (requisitos T-01 y S-10).

`target_metadata` apunta a los metadatos de `app.shared.database.Base`. En
`Task/005` no hay ningun modelo colgando de esa base todavia; la comparacion
sirve desde `Task/008`, cuando aparezca el modelo de datos del blog.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from app.shared.configuration import get_settings
from app.shared.database import Base
from app.shared.database.session import create_database_engine

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera el SQL de las migraciones sin conectarse a la base de datos."""
    settings = get_settings()
    context.configure(
        url=settings.sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica las migraciones contra la base de datos configurada."""
    engine = create_database_engine(get_settings())
    try:
        with engine.connect() as connection:
            _run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
