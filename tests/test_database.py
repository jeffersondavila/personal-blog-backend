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


def test_la_base_declarativa_no_declara_todavia_ninguna_tabla() -> None:
    """El modelo de datos del blog es `Task/008`, no `Task/005`."""
    assert Base.metadata.tables == {}


def test_la_convencion_de_nombres_esta_activa() -> None:
    convencion = Base.metadata.naming_convention

    assert convencion["pk"] == "pk_%(table_name)s"
    assert str(convencion["fk"]).startswith("fk_")
