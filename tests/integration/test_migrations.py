"""Ciclo completo de migraciones contra PostgreSQL.

Comprueba el requisito M-04 —**toda migracion aplica y revierte**— ejecutando
el ciclo real: `upgrade head`, `downgrade base` y reaplicacion.

La prueba deja la base de datos en `head`, su estado normal de trabajo. Es
segura porque la migracion fundacional no crea objetos de negocio: lo unico que
cambia es la tabla `alembic_version`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from app.shared.configuration import Settings

pytestmark = pytest.mark.integration

REVISION_FUNDACIONAL = "0001"
RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_config(database_settings: Settings) -> Iterator[Config]:
    """Configuracion de Alembic apuntando a la base de datos de pruebas."""
    import os

    configuracion = Config(str(RAIZ_DEL_REPOSITORIO / "alembic.ini"))
    configuracion.set_main_option("script_location", str(RAIZ_DEL_REPOSITORIO / "alembic"))

    # `alembic/env.py` obtiene la URL de la configuracion de la aplicacion.
    anterior = os.environ.get("BLOG_DATABASE_URL")
    os.environ["BLOG_DATABASE_URL"] = str(database_settings.database_url)
    from app.shared.configuration import get_settings

    get_settings.cache_clear()
    try:
        yield configuracion
    finally:
        if anterior is None:
            os.environ.pop("BLOG_DATABASE_URL", None)
        else:
            os.environ["BLOG_DATABASE_URL"] = anterior
        get_settings.cache_clear()


def _revision_aplicada(engine: Engine) -> str | None:
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as connection:
        resultado = connection.execute(text("SELECT version_num FROM alembic_version"))
        return resultado.scalar_one_or_none()


def test_upgrade_downgrade_y_reaplicacion(alembic_config: Config, database_engine: Engine) -> None:
    command.upgrade(alembic_config, "head")
    assert _revision_aplicada(database_engine) == REVISION_FUNDACIONAL

    command.downgrade(alembic_config, "base")
    assert _revision_aplicada(database_engine) is None

    command.upgrade(alembic_config, "head")
    assert _revision_aplicada(database_engine) == REVISION_FUNDACIONAL


def test_la_migracion_fundacional_no_crea_tablas_de_negocio(
    alembic_config: Config, database_engine: Engine
) -> None:
    """El modelo de datos del blog llega en `Task/008`."""
    command.upgrade(alembic_config, "head")

    tablas = set(inspect(database_engine).get_table_names())

    assert tablas <= {"alembic_version"}
