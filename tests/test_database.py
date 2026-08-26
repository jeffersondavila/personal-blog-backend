"""Pruebas del acceso a datos que no necesitan una base de datos en marcha.

Comprueban como se construye el motor. La conexion real y el ciclo de
migraciones viven en `tests/integration/`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.pool import QueuePool

from app.shared.database import Base, dispose_engine, get_engine, get_sessionmaker
from app.shared.database.session import create_database_engine


def test_el_motor_usa_el_driver_y_la_base_configurados(settings: Any) -> None:
    engine = create_database_engine(settings)
    try:
        assert engine.dialect.driver == "psycopg"
        assert engine.url.database == "base_de_prueba"
    finally:
        engine.dispose()


def test_el_motor_aplica_los_parametros_del_pool(settings_factory: Any) -> None:
    engine = create_database_engine(settings_factory(database_pool_size=3))
    try:
        pool = engine.pool
        assert isinstance(pool, QueuePool)
        assert pool.size() == 3
    finally:
        engine.dispose()


def test_el_motor_no_registra_sql_por_defecto(settings: Any) -> None:
    engine = create_database_engine(settings)
    try:
        assert engine.echo is False
    finally:
        engine.dispose()


def test_crear_el_motor_no_abre_conexiones(settings: Any) -> None:
    """El arranque no debe depender de que PostgreSQL este disponible."""
    engine = create_database_engine(settings)
    try:
        pool = engine.pool
        assert isinstance(pool, QueuePool)
        assert pool.checkedout() == 0
    finally:
        engine.dispose()


def test_dispose_engine_limpia_las_caches(monkeypatch: Any) -> None:
    monkeypatch.setenv(
        "BLOG_DATABASE_URL",
        "postgresql://usuario:clave@localhost:5432/base_de_prueba",
    )
    from app.shared.configuration import get_settings

    get_settings.cache_clear()
    try:
        primero = get_engine()
        assert get_sessionmaker() is get_sessionmaker()
        dispose_engine()
        assert get_engine() is not primero
    finally:
        dispose_engine()
        get_settings.cache_clear()


def test_la_base_declarativa_reune_las_tablas_del_modelo() -> None:
    """Sustituye a `test_la_base_declarativa_no_declara_todavia_ninguna_tabla`.

    Aquella prueba afirmaba `Base.metadata.tables == {}` —"el proyecto no tiene
    tablas de negocio"—, cierto en `Task/005` y **condenado a caducar**: se puso
    en rojo al aparecer la primera tabla legitima del blog, exactamente como le
    ocurrio a la prueba de migraciones que `Task/005.6` ya tuvo que rehacer por el
    mismo motivo. El requisito cambio: `Task/008` es la tarea que trae el modelo.

    Lo que se comprueba ahora no caduca: **importar el registro de modelos deja
    tablas colgando de la base declarativa**. Cuantas y cuales lo verifica
    `tests/unit/test_registro_de_modelos.py`, y que coincidan con el esquema real,
    `tests/integration/test_esquema_fisico.py`.
    """
    import app.modules.models  # noqa: F401  (registrar es el objeto de la prueba)

    assert Base.metadata.tables, "el registro de modelos no aporto ninguna tabla"


def test_la_convencion_de_nombres_esta_activa() -> None:
    convencion = Base.metadata.naming_convention

    assert convencion["pk"] == "pk_%(table_name)s"
    assert str(convencion["fk"]).startswith("fk_")
