"""Motor y sesiones de SQLAlchemy.

Decisiones vigentes en `Task/005`:

- **Motor sincrono con psycopg 3.** El backend termina ejecutandose en Lambda
  (ADR-003), donde una invocacion atiende una peticion: la asincronia no aporta
  concurrencia real y si complica el codigo.
- **El motor se crea de forma perezosa**, en la primera llamada, no al importar
  el modulo. Asi la aplicacion arranca y responde `/health` aunque PostgreSQL
  todavia no este disponible: la comprobacion de dependencias es `/ready`
  (`Task/017`).
- **`pool_pre_ping` activo.** Un contenedor reiniciado o una conexion caducada
  producirian, si no, un fallo en la primera consulta.
- La **estrategia definitiva de pooling para Lambda** —conexiones cortas,
  proxy o pooler externo— se decide en `Task/029` (riesgo R-03). Lo que hay
  aqui es un pool convencional, valido para la ejecucion local y configurable
  por variables de entorno.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.shared.configuration import Settings, get_settings


def create_database_engine(settings: Settings) -> Engine:
    """Crea un motor de SQLAlchemy a partir de la configuracion recibida."""
    return create_engine(
        settings.sqlalchemy_url,
        echo=settings.database_echo,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
        pool_recycle=settings.database_pool_recycle_seconds,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
        future=True,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Devuelve el motor del proceso, creandolo la primera vez."""
    return create_database_engine(get_settings())


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    """Devuelve la fabrica de sesiones del proceso."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def dispose_engine() -> None:
    """Cierra el pool y olvida el motor memorizado.

    Necesario al terminar un proceso o entre pruebas que cambian la
    configuracion: sin esto, el motor anterior seguiria en la cache.
    """
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sesion con transaccion delimitada: confirma al salir y revierte si falla."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """Dependencia de FastAPI que entrega una sesion por peticion.

    Todavia no la consume ningun endpoint: los primeros que acceden a datos
    llegan en `Task/009`. Se define aqui porque es el contrato que fija como se
    obtiene una sesion, y las pruebas de integracion ya lo ejercitan.
    """
    with session_scope() as session:
        yield session
