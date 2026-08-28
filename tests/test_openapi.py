"""Pruebas de la especificacion OpenAPI generada."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app import __version__


def test_openapi_se_genera_y_es_valido(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document: dict[str, Any] = response.json()
    assert document["openapi"].startswith("3.")
    assert document["info"]["title"] == "personal-blog-backend"
    assert document["info"]["version"] == __version__


def test_openapi_documenta_el_endpoint_de_salud(client: TestClient) -> None:
    document: dict[str, Any] = client.get("/openapi.json").json()

    assert "/health" in document["paths"]
    operacion = document["paths"]["/health"]["get"]
    assert operacion["tags"] == ["health"]
    esquema = operacion["responses"]["200"]["content"]["application/json"]["schema"]
    assert esquema["$ref"].endswith("HealthResponse")


def test_documentacion_interactiva_disponible(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_openapi_no_declara_endpoints_no_implementados(client: TestClient) -> None:
    """Sigue sin declararse lo que todavia no existe.

    Hasta `Task/009` esta prueba afirmaba `paths == ["/health"]`, porque era la
    unica ruta del backend. `Task/009` publica los diez recursos de la API
    publica, asi que **esa expectativa cambio por un cambio de requisito**, que
    es el primero de los supuestos que BACKEND_TESTING_STRATEGY.md seccion 9
    admite para modificar un test.

    Lo que no cambia es lo que la prueba protege: que no aparezca documentado
    nada que no se haya implementado. Se sigue comprobando, sobre lo que
    corresponde a las tareas siguientes:

    - `/ready` es de `Task/017`.
    - Los endpoints administrativos, de `Task/011` y `Task/012`.

    La comprobacion **exacta** del conjunto de rutas de la API publica vive en
    `tests/contract/test_openapi_publica.py`, junto al resto del contrato HTTP.
    Aqui no se duplica.
    """
    document: dict[str, Any] = client.get("/openapi.json").json()
    rutas = set(document["paths"])

    assert "/health" in rutas
    assert "/ready" not in rutas, "`/ready` es de `Task/017` y no debe existir todavia"
    assert not [ruta for ruta in rutas if "admin" in ruta], (
        "la API administrativa es de `Task/011` y `Task/012`"
    )
