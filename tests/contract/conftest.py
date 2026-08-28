"""Cliente HTTP para las pruebas de **contrato**.

Que se prueba aqui y que no
---------------------------

`tests/contract/` comprueba la **forma HTTP**: rutas, metodos, codigos de
estado, envoltura de error, validacion de parametros y la especificacion
OpenAPI. La **semantica** —que un borrador no salga, que el filtro por etiqueta
recorra las asociaciones reales, que `total` cuente el conjunto completo— vive
en `tests/integration/` y se ejecuta contra PostgreSQL real
(BACKEND_TESTING_STRATEGY.md seccion 8.3).

Por eso estas pruebas **no necesitan base de datos**: todo lo que comprueban
ocurre antes de que la peticion llegue a una consulta. Un `422` de validacion se
resuelve en la capa de transporte, y la especificacion OpenAPI se genera sin
ejecutar ningun endpoint.

Por que la sesion se sustituye por un objeto que estalla
--------------------------------------------------------

FastAPI resuelve **todas** las dependencias de una operacion, incluida la que
entrega la sesion, incluso cuando la validacion de los parametros va a fallar.
Sin sustituirla, cada prueba de validacion intentaria conectar a la URL ficticia
del harness y el `422` esperado se convertiria en un error de conexion.

La sustitucion **no** es un mock de PostgreSQL para aparentar integracion: es la
afirmacion de que ninguna prueba de este directorio debe llegar a la base de
datos. Y se hace cumplir: el objeto entregado **lanza al primer uso**. Si una
prueba de contrato acabara alcanzando la consulta, se pondria roja en lugar de
pasar por accidente contra una sesion inerte.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, NoReturn

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shared.configuration import Settings
from app.shared.database import get_session


class _SesionProhibida:
    """Sustituto de `Session` que rechaza cualquier uso.

    No es una sesion falsa que devuelve datos vacios: es una guarda. Una prueba
    de contrato que llegue a consultar algo tiene un defecto —pertenece a
    `tests/integration/`— y debe fallar diciendolo.
    """

    def __getattr__(self, nombre: str) -> NoReturn:
        raise AssertionError(
            f"una prueba de contrato intento usar la sesion de base de datos ({nombre!r}). "
            "Las pruebas de contrato comprueban la forma HTTP y no deben alcanzar "
            "PostgreSQL: el comportamiento que dependa de datos pertenece a "
            "tests/integration/, contra PostgreSQL real."
        )


@pytest.fixture
def aplicacion_publica(settings: Settings) -> FastAPI:
    """Aplicacion completa con la sesion de base de datos neutralizada."""
    from app.main import create_app

    aplicacion = create_app(settings=settings)

    def _sesion_prohibida() -> Iterator[Any]:
        yield _SesionProhibida()

    aplicacion.dependency_overrides[get_session] = _sesion_prohibida
    return aplicacion


@pytest.fixture
def cliente_publico(aplicacion_publica: FastAPI) -> Iterator[TestClient]:
    """Cliente HTTP contra la aplicacion publica."""
    with TestClient(aplicacion_publica, raise_server_exceptions=False) as cliente:
        yield cliente
