"""Conexion real contra el PostgreSQL del entorno local."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

pytestmark = pytest.mark.integration


def test_la_conexion_funciona(database_engine: Engine) -> None:
    with database_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


def test_el_motor_habla_con_postgresql(database_engine: Engine) -> None:
    with database_engine.connect() as connection:
        version = connection.execute(text("SELECT version()")).scalar_one()

    assert isinstance(version, str)
    assert version.startswith("PostgreSQL")


def test_la_sesion_ejecuta_y_confirma(database_engine: Engine) -> None:
    from sqlalchemy.orm import sessionmaker

    fabrica = sessionmaker(bind=database_engine, autoflush=False, expire_on_commit=False)
    sesion = fabrica()
    try:
        assert sesion.execute(text("SELECT current_database()")).scalar_one()
        sesion.commit()
    finally:
        sesion.close()


def test_la_codificacion_de_la_base_es_utf8(database_engine: Engine) -> None:
    """El proyecto trabaja en UTF-8 (api-contracts.md, seccion 1)."""
    with database_engine.connect() as connection:
        codificacion = connection.execute(text("SHOW server_encoding")).scalar_one()

    assert codificacion == "UTF8"


def test_session_scope_entrega_una_sesion_utilizable(configured_process: None) -> None:
    """Contrato de `session_scope`: abre, confirma al salir y cierra."""
    from app.shared.database import session_scope

    with session_scope() as sesion:
        assert sesion.execute(text("SELECT 1")).scalar_one() == 1

    # Al salir del contexto la sesion queda cerrada: sin transaccion viva.
    assert not sesion.in_transaction()


def test_session_scope_revierte_si_falla(configured_process: None) -> None:
    from app.shared.database import session_scope

    with pytest.raises(RuntimeError), session_scope() as sesion:
        sesion.execute(text("SELECT 1"))
        raise RuntimeError("fallo dentro de la transaccion")


def test_la_dependencia_de_fastapi_entrega_una_sesion(configured_process: None) -> None:
    """`get_session` es el contrato que consumiran los endpoints desde `Task/009`."""
    from app.shared.database import get_session

    generador = get_session()
    sesion = next(generador)
    try:
        assert sesion.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        # Agotar el generador ejecuta el cierre, igual que hace FastAPI al
        # terminar la peticion.
        assert next(generador, None) is None
