"""Pruebas del manejo centralizado de errores.

Verifican las dos garantias del modelo comun de error (api-contracts.md,
seccion 7): forma estable y **ninguna filtracion interna** (requisito S-07).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shared.errors import (
    ApplicationError,
    ConflictError,
    DependencyUnavailableError,
    ResourceNotFoundError,
    ValidationFailedError,
)

SECRETO_INTERNO = "detalle-interno-que-no-debe-salir"


def _asegurar_forma_del_error(cuerpo: dict[str, Any]) -> dict[str, Any]:
    """Comprueba la envoltura comun y devuelve el objeto `error`."""
    assert set(cuerpo) == {"error"}
    error = cuerpo["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], dict)
    uuid.UUID(error["request_id"])
    return dict(error)


def test_ruta_inexistente_devuelve_el_modelo_comun(client: TestClient) -> None:
    response = client.get("/ruta-que-no-existe")

    assert response.status_code == 404
    error = _asegurar_forma_del_error(response.json())
    assert error["code"] == "resource_not_found"


def test_cada_error_lleva_un_request_id_distinto(client: TestClient) -> None:
    primero = client.get("/ruta-que-no-existe").json()["error"]["request_id"]
    segundo = client.get("/ruta-que-no-existe").json()["error"]["request_id"]

    assert primero != segundo


@pytest.mark.parametrize(
    ("excepcion", "estado", "codigo"),
    [
        (ResourceNotFoundError, 404, "resource_not_found"),
        (ValidationFailedError, 422, "validation_error"),
        (ConflictError, 409, "conflict"),
        (DependencyUnavailableError, 503, "dependency_unavailable"),
        (ApplicationError, 500, "application_error"),
    ],
)
def test_los_errores_de_aplicacion_se_traducen(
    application: FastAPI,
    excepcion: type[ApplicationError],
    estado: int,
    codigo: str,
) -> None:
    @application.get("/prueba/error-de-aplicacion")
    def _provocar() -> None:
        raise excepcion("Mensaje para el cliente", details={"campo": "valor"})

    with TestClient(application, raise_server_exceptions=False) as cliente:
        response = cliente.get("/prueba/error-de-aplicacion")

    assert response.status_code == estado
    error = _asegurar_forma_del_error(response.json())
    assert error["code"] == codigo
    assert error["message"] == "Mensaje para el cliente"
    assert error["details"] == {"campo": "valor"}


def test_una_excepcion_no_prevista_se_convierte_en_500_opaco(application: FastAPI) -> None:
    @application.get("/prueba/fallo")
    def _fallar() -> None:
        raise RuntimeError(SECRETO_INTERNO)

    with TestClient(application, raise_server_exceptions=False) as cliente:
        response = cliente.get("/prueba/fallo")

    assert response.status_code == 500
    error = _asegurar_forma_del_error(response.json())
    assert error["code"] == "internal_error"
    assert SECRETO_INTERNO not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text


def test_la_validacion_de_entrada_devuelve_422_con_los_campos(application: FastAPI) -> None:
    @application.get("/prueba/validacion")
    def _validar(pagina: int) -> dict[str, int]:
        return {"pagina": pagina}

    with TestClient(application, raise_server_exceptions=False) as cliente:
        response = cliente.get("/prueba/validacion", params={"pagina": "no-es-un-numero"})

    assert response.status_code == 422
    error = _asegurar_forma_del_error(response.json())
    assert error["code"] == "validation_error"
    campos = error["details"]["fields"]
    assert any(campo["field"].endswith("pagina") for campo in campos)


def test_los_errores_de_aplicacion_no_conocen_el_framework() -> None:
    """El dominio lanza estas excepciones: no deben importar FastAPI (ADR-004)."""
    import ast
    from pathlib import Path

    import app.shared.errors.exceptions as modulo

    fuente = modulo.__file__
    assert fuente is not None
    arbol = ast.parse(Path(fuente).read_text(encoding="utf-8"))

    importados: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            importados.add(nodo.module.split(".")[0])

    assert not importados & {"fastapi", "starlette", "sqlalchemy"}
