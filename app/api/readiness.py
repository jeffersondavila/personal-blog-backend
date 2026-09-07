"""Endpoint de disponibilidad real del servicio (`Task/017`, requisito O-04).

`GET /ready` responde a una pregunta distinta de la de `/health`:

```
/health  = el PROCESO esta vivo
/ready   = puede ATENDER TRAFICO usando sus dependencias
```

Dos preguntas, dos consumidores, dos consecuencias. El `HEALTHCHECK` de Docker
sigue en `/health` —su pregunta es sobre el contenedor—, y el `healthCheck` de
Traefik pasa a `/ready`, porque su consecuencia es **retirar de rotacion** un
backend que no puede servir.

Que comprueba, y como
---------------------

- **PostgreSQL:** un `SELECT 1` real. No basta con que la configuracion exista
  ni con que el motor se haya podido construir: el motor es perezoso, asi que
  nada de eso demuestra que haya una conexion posible.
- **Almacenamiento:** `ObjectStorage.comprobar_disponibilidad()`, que hace una
  operacion de red de solo lectura y **si distingue el bucket ausente**.

Ninguna de las dos muta nada.

Que **no** demuestra
--------------------

Que se pueda **escribir**. Demostrarlo exigiria escribir, y una sonda que muta
el almacenamiento en cada comprobacion no es aceptable —Traefik la ejecuta cada
diez segundos—. `/ready` afirma que las dependencias estan ahi y responden, no
que toda operacion futura vaya a tener permiso. La politica de permisos de
produccion es de `Task/030`.

Por que el cuerpo no dice que fallo
-----------------------------------

`api-contracts.md` seccion 2: *"Ninguno expone detalles internos"*. Un
`{"database": "down"}` le diria a un cliente anonimo que parte de la
infraestructura esta caida, que es reconocimiento gratuito. El codigo HTTP ya
transporta lo unico que el consumidor necesita decidir; el **operador** obtiene
el componente y el motivo del log, que si los distingue.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import lru_cache, partial
from http import HTTPStatus
from threading import BoundedSemaphore
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.shared.configuration import Settings, get_settings
from app.shared.logging import get_logger
from app.shared.storage import ErrorDeAlmacenamiento, ObjectStorage
from app.shared.storage.fabrica import obtener_almacenamiento

_logger = get_logger(__name__)

router = APIRouter(tags=["health"])

# Presupuesto HTTP total: deja 0.5s al transporte frente a Traefik (3s).
# Los drivers sincronos no se pueden cancelar desde asyncio. Dos plazas,
# retenidas HASTA terminar el driver, impiden acumular hilos o trabajo en cola
# si vence el plazo. El pool operativo de la aplicacion no participa.
SEGUNDOS_DE_PRESUPUESTO: Final[float] = 2.5
_ejecutor_de_sondas = ThreadPoolExecutor(max_workers=2, thread_name_prefix="readiness")
_plazas_de_sonda = BoundedSemaphore(2)


async def plazo_de_readiness() -> float:
    """FastAPI memoriza esta dependencia por peticion: ambas sondas comparten plazo."""
    return time.perf_counter() + SEGUNDOS_DE_PRESUPUESTO


async def _ejecutar_sonda(
    operacion: Callable[[], str | None],
    componente: str,
    plazo: float,
) -> str | None:
    restante = plazo - time.perf_counter()
    if restante <= 0 or not _plazas_de_sonda.acquire(blocking=False):
        _logger.warning(
            "Sonda sin presupuesto o capacidad",
            extra={"componente": componente, "motivo": "presupuesto_o_capacidad_agotados"},
        )
        return componente
    try:
        futuro = _ejecutor_de_sondas.submit(copy_context().run, operacion)
    except RuntimeError:
        _plazas_de_sonda.release()
        raise
    futuro.add_done_callback(lambda _: _plazas_de_sonda.release())
    try:
        motivo = await asyncio.wait_for(asyncio.wrap_future(futuro), timeout=restante)
        if motivo is not None:
            # Se registra en la tarea HTTP, nunca desde un driver que pudiera
            # terminar despues del timeout y de cerrar el contexto de peticion.
            _logger.warning(
                "Dependencia no disponible",
                extra={"componente": componente, "motivo": motivo},
            )
            return componente
        return None
    except TimeoutError:
        _logger.warning(
            "Sonda excedio el presupuesto",
            extra={
                "componente": componente,
                "motivo": "timeout",
                "timeout_s": SEGUNDOS_DE_PRESUPUESTO,
            },
        )
        return componente


class ReadinessResponse(BaseModel):
    """Cuerpo de la respuesta de disponibilidad.

    Un solo campo, y con un valor de un conjunto cerrado. No enumera
    componentes: ver el modulo.
    """

    status: Literal["ready", "not_ready"] = Field(description="Disponibilidad del servicio.")


def obtener_almacenamiento_para_readiness(
    configuracion: Annotated[Settings, Depends(get_settings)],
) -> ObjectStorage:
    """Almacenamiento sobre el que se ejecuta la sonda.

    Es una dependencia propia y no un uso directo de la fabrica para que una
    prueba pueda sustituirla sin tocar el resto de la aplicacion.
    """
    return obtener_almacenamiento(configuracion)


@lru_cache(maxsize=4)
def motor_de_sonda(configuracion: Settings) -> Engine:
    """Motor dedicado a la sonda de readiness, con presupuesto propio.

    Por que no se reutiliza `get_engine()`
    --------------------------------------

    Por dos razones, y ambas se midieron.

    1. **Tiempo.** El motor del proceso usa
       `BLOG_DATABASE_CONNECT_TIMEOUT_SECONDS`, **10 segundos por defecto**, y
       `psycopg` prueba cada direccion que resuelve el anfitrion: con `localhost`
       resolviendo a `::1` y a `127.0.0.1`, una base inalcanzable tarda unos
       **20 segundos**. El `healthCheck` de Traefik usa `timeout: 3s`, asi que la
       sonda habria caducado siempre y ademas dejaria peticiones colgadas.
       Acortar el timeout **global** no es una opcion: penalizaria a la
       aplicacion en un arranque en frio legitimo.
    2. **Configuracion.** `get_engine()` resuelve `get_settings()` por su cuenta,
       asi que ignora la configuracion con la que se construyo la aplicacion. La
       sonda debe comprobar **la base que esta aplicacion usaria**.

    `NullPool` es deliberado: la sonda abre una conexion, la usa y la cierra. No
    tiene sentido que una comprobacion de salud retenga conexiones del pool que
    las peticiones reales necesitan.
    """
    return create_engine(
        configuracion.sqlalchemy_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": SEGUNDOS_DE_CONEXION_DE_LA_SONDA},
        future=True,
    )


async def comprobar_base_de_datos(
    configuracion: Annotated[Settings, Depends(get_settings)],
    plazo: Annotated[float, Depends(plazo_de_readiness)],
) -> str | None:
    """Ejecuta la sonda dedicada dentro del presupuesto total de la peticion."""
    return await _ejecutar_sonda(
        partial(_comprobar_base_de_datos, configuracion), COMPONENTE_BASE_DE_DATOS, plazo
    )


def _comprobar_base_de_datos(configuracion: Settings) -> str | None:
    """Ejecuta `SELECT 1` contra PostgreSQL.

    Devuelve `None` si responde, o el **nombre del componente** si no. Devolver
    el nombre en lugar de lanzar mantiene la decision del codigo HTTP en un solo
    sitio —el endpoint— y permite que el log nombre el componente sin que ese
    nombre llegue nunca a la respuesta.

    `statement_timeout` acota la consulta desde el servidor. Es necesario porque
    `connect_timeout` **solo gobierna la apertura de la conexion**: sobre una
    conexion ya establecida y en el pool, una consulta puede quedarse esperando
    indefinidamente sin que aquel intervenga.
    """
    try:
        with motor_de_sonda(configuracion).connect() as conexion:
            conexion.execute(text(f"SET statement_timeout = {_MILISEGUNDOS_DE_CONSULTA}"))
            conexion.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        # El motivo va al log, no a la respuesta: la excepcion de SQLAlchemy
        # lleva la cadena de conexion (requisitos S-07 y S-08). El formateador
        # la redacta ademas antes de emitirla.
        return type(error).__name__
    return None


async def comprobar_almacenamiento(
    almacenamiento: Annotated[ObjectStorage, Depends(obtener_almacenamiento_para_readiness)],
    plazo: Annotated[float, Depends(plazo_de_readiness)],
) -> str | None:
    """Comparte el presupuesto con PostgreSQL; no suma otro timeout HTTP."""
    return await _ejecutar_sonda(
        partial(_comprobar_almacenamiento, almacenamiento), COMPONENTE_ALMACENAMIENTO, plazo
    )


def _comprobar_almacenamiento(almacenamiento: ObjectStorage) -> str | None:
    """Ejerce la sonda de `ObjectStorage`. Devuelve el componente si no responde."""
    try:
        almacenamiento.comprobar_disponibilidad()
    except ErrorDeAlmacenamiento as error:
        # `str(error)` es seguro: `_fallo()` del adaptador ya construye el
        # mensaje sin credenciales, sin URL firmada y sin el texto original del
        # SDK, que queda en `__cause__`.
        return str(error)
    return None


#: Limite de la **consulta** de readiness, en milisegundos.
#:
#: `connect_timeout` no lo cubre: solo gobierna la apertura de la conexion. Sobre
#: una conexion ya establecida, una consulta puede esperar indefinidamente. Son
#: dos limites distintos porque acotan dos fases distintas.
_MILISEGUNDOS_DE_CONSULTA: Final[int] = 2000

#: Limite de la **conexion** de la sonda, en segundos.
#:
#: Muy por debajo de los 10 s del motor de la aplicacion, y elegido contra el
#: `timeout: 3s` del `healthCheck` de Traefik: `psycopg` prueba cada direccion
#: que resuelve el anfitrion, asi que el peor caso realista son dos intentos.
SEGUNDOS_DE_CONEXION_DE_LA_SONDA: Final[int] = 2

#: Nombres de componente. Viajan al **log**, nunca a la respuesta.
COMPONENTE_BASE_DE_DATOS: Final[str] = "base_de_datos"
COMPONENTE_ALMACENAMIENTO: Final[str] = "almacenamiento"


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Disponibilidad real del servicio",
    description=(
        "Responde 200 si PostgreSQL y el almacenamiento de objetos responden. "
        "Responde 503 si alguno no lo hace. No expone que componente fallo."
    ),
    responses={503: {"description": "Alguna dependencia no esta disponible."}},
)
def read_readiness(
    respuesta: Response,
    base_de_datos: Annotated[str | None, Depends(comprobar_base_de_datos)],
    almacenamiento: Annotated[str | None, Depends(comprobar_almacenamiento)],
) -> ReadinessResponse:
    """Devuelve la disponibilidad del servicio y sus dependencias.

    **No usa la envoltura comun de error** de api-contracts.md seccion 7, y es
    deliberado: `/health` y `/ready` viven fuera de `/api/v1` porque no forman
    parte del contrato de datos del frontend (seccion 2). `/health` ya responde
    `{"status": "ok", ...}` con la misma logica. Un `503` aqui no es un error de
    la aplicacion que un cliente deba interpretar: es el estado del servicio.
    """
    respuesta.headers["Cache-Control"] = "no-store"

    fallidos = [componente for componente in (base_de_datos, almacenamiento) if componente]
    if fallidos:
        respuesta.status_code = HTTPStatus.SERVICE_UNAVAILABLE
        return ReadinessResponse(status="not_ready")

    return ReadinessResponse(status="ready")
