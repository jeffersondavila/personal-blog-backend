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

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

pytestmark = pytest.mark.integration


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
