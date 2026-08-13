"""Configuracion de las pruebas de integracion.

Estas pruebas necesitan el PostgreSQL del entorno local levantado por
`personal-blog-infra`. Se omiten —no fallan— cuando no hay base de datos
disponible, para que `pytest` siga siendo ejecutable sin Docker.

La URL se toma de `PERSONAL_BLOG_TEST_DATABASE_URL`. El nombre no lleva el
prefijo `BLOG_` a proposito: las pruebas limpian ese prefijo del entorno para
aislarse de la configuracion de la maquina.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from app.shared.configuration import Settings, build_settings
from app.shared.database.session import create_database_engine

TEST_DATABASE_URL_VARIABLE = "PERSONAL_BLOG_TEST_DATABASE_URL"


def _url_de_pruebas() -> str | None:
    return os.environ.get(TEST_DATABASE_URL_VARIABLE)


@pytest.fixture(scope="session")
def database_settings() -> Settings:
    """Configuracion apuntando a la base de datos real de pruebas."""
    url = _url_de_pruebas()
    if not url:
        pytest.skip(f"{TEST_DATABASE_URL_VARIABLE} no definida: se omite la integracion")
    return build_settings(app_env="test", database_url=url, log_format="text", _env_file=None)


@pytest.fixture
def configured_process(database_settings: Settings, database_engine: Engine) -> Iterator[None]:
    """Deja el proceso configurado contra la base de datos real.

    Lo necesitan las funciones que resuelven la configuracion por si mismas
    —`session_scope`, `get_session`— en lugar de recibirla como argumento.
    """
    from app.shared.configuration import get_settings
    from app.shared.database import dispose_engine

    anterior = os.environ.get("BLOG_DATABASE_URL")
    os.environ["BLOG_DATABASE_URL"] = str(database_settings.database_url)
    get_settings.cache_clear()
    dispose_engine()
    try:
        yield
    finally:
        dispose_engine()
        if anterior is None:
            os.environ.pop("BLOG_DATABASE_URL", None)
        else:
            os.environ["BLOG_DATABASE_URL"] = anterior
        get_settings.cache_clear()


@pytest.fixture(scope="session")
def database_engine(database_settings: Settings) -> Iterator[Engine]:
    """Motor conectado a la base de datos de pruebas.

    Si la base no responde, la prueba se omite: la ausencia del entorno local
    no es un fallo del codigo.
    """
    engine = create_database_engine(database_settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        engine.dispose()
        pytest.skip(f"PostgreSQL no esta disponible: {type(error).__name__}")
    try:
        yield engine
    finally:
        engine.dispose()
