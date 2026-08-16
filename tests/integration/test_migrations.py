"""Ciclo completo de migraciones contra PostgreSQL.

Comprueba el requisito M-04 —**toda migracion aplica y revierte**— ejecutando el
ciclo real: `upgrade head`, `downgrade base` y reaplicacion.

**Estas pruebas son destructivas.** `downgrade base` revierte el esquema entero.
Solo se ejecutan contra la base de pruebas verificada por la guarda
*fail-closed* de `conftest.py`, que exige nombre con sufijo `_test` **y** la
marca `personal-blog:test-database` dentro de la propia base.

Al terminar, la base queda en `head`, su estado normal de trabajo.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from app.shared.configuration import Settings

pytestmark = pytest.mark.integration

RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_config(database_settings: Settings, database_engine: Engine) -> Iterator[Config]:
    """Configuracion de Alembic apuntando a la base de datos de pruebas.

    Depende de `database_engine` **a proposito**, aunque no lo use: es la
    fixture que ejecuta la guarda *fail-closed*. Asi ninguna prueba futura puede
    obtener un `Config` capaz de hacer `downgrade` sin haber pasado antes por la
    verificacion del destino. La proteccion es estructural, no una convencion
    que haya que recordar.
    """
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


def _tablas_del_esquema(engine: Engine) -> set[str]:
    """Tablas del proyecto, excluida la contabilidad de Alembic.

    `alembic_version` la crea Alembic en el primer `upgrade` y **no** la suelta
    en `downgrade base`: es su propio registro, no un objeto del esquema del
    blog. Incluirla haria fallar la comparacion por un motivo que no tiene nada
    que ver con el contrato que se esta probando.
    """
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def _head(configuracion: Config) -> str:
    """Revision `head` leida del directorio de scripts.

    No se fija ningun identificador en el codigo de la prueba: cuando
    `Task/008` anada la primera migracion de negocio, `head` cambiara y esta
    prueba seguira siendo correcta sin tocarla.
    """
    head = ScriptDirectory.from_config(configuracion).get_current_head()
    assert head is not None, "el proyecto no tiene ninguna migracion"
    return head


def test_upgrade_downgrade_y_reaplicacion(alembic_config: Config, database_engine: Engine) -> None:
    head = _head(alembic_config)

    command.upgrade(alembic_config, "head")
    assert _revision_aplicada(database_engine) == head

    command.downgrade(alembic_config, "base")
    assert _revision_aplicada(database_engine) is None

    command.upgrade(alembic_config, "head")
    assert _revision_aplicada(database_engine) == head


def test_el_downgrade_revierte_todo_lo_que_el_upgrade_creo(
    alembic_config: Config, database_engine: Engine
) -> None:
    """Contrato durable de M-04, valido tambien despues de `Task/008`.

    Sustituye a la antigua asercion `tablas <= {"alembic_version"}`, que
    afirmaba que el proyecto **no tiene tablas de negocio**. Eso era cierto solo
    en el estado previo a `Task/008` y habria puesto la suite en rojo al
    aparecer la primera tabla legitima del blog.

    Lo que se comprueba ahora no caduca: el esquema despues de
    `upgrade` + `downgrade` debe ser identico al de antes. Una migracion que
    cree una tabla y olvide soltarla en su `downgrade` rompe esta prueba, que es
    justo el defecto que M-04 quiere impedir.
    """
    command.downgrade(alembic_config, "base")
    antes = _tablas_del_esquema(database_engine)

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    despues = _tablas_del_esquema(database_engine)

    try:
        assert despues == antes, (
            "el ciclo upgrade/downgrade dejo objetos huerfanos: "
            f"sobran {sorted(despues - antes)}, faltan {sorted(antes - despues)}"
        )
    finally:
        # La base se devuelve a `head` pase lo que pase con la asercion.
        command.upgrade(alembic_config, "head")
