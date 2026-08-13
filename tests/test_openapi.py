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
    """`/ready` y los recursos de contenido llegan en tareas posteriores."""
    document: dict[str, Any] = client.get("/openapi.json").json()

    assert list(document["paths"]) == ["/health"]
