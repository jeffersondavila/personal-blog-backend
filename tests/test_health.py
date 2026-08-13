"""Pruebas del endpoint de vivacidad."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app import __version__


def test_health_devuelve_200_y_el_cuerpo_esperado(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "personal-blog-backend",
        "version": __version__,
    }


def test_health_no_expone_detalles_internos(client: TestClient) -> None:
    """No debe filtrar entorno, dependencias ni configuracion (api-contracts.md, 2)."""
    body: dict[str, Any] = client.get("/health").json()

    assert set(body) == {"status", "service", "version"}


def test_health_usa_el_nombre_configurado(settings_factory: Any) -> None:
    from app.main import create_app

    application = create_app(settings=settings_factory(app_name="otro-servicio"))

    with TestClient(application) as configured_client:
        assert configured_client.get("/health").json()["service"] == "otro-servicio"


def test_health_esta_fuera_del_prefijo_versionado(client: TestClient) -> None:
    """La sonda de plataforma no vive bajo /api/v1: no cambia de ruta con la version."""
    assert client.get("/api/v1/health").status_code == 404


def test_health_no_responde_a_metodos_no_permitidos(client: TestClient) -> None:
    response = client.post("/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
