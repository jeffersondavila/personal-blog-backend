"""Contrato adversario de Task018: HTTP, errores y configuracion."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.shared.configuration import ConfigurationError

ORIGEN = "https://sitio.example.test"
SENUELO = "CANARY018-49f910e7"


@pytest.fixture
def cliente_cors(settings_factory: Any) -> TestClient:
    from app.main import create_app

    return TestClient(
        create_app(settings_factory(admin_allowed_origins=ORIGEN)),
        raise_server_exceptions=False,
    )


def test_cors_autoriza_origen_exacto_con_credenciales(cliente_cors: TestClient) -> None:
    respuesta = cliente_cors.get("/health", headers={"Origin": ORIGEN})
    assert respuesta.status_code == 200
    assert respuesta.headers.get("access-control-allow-origin") == ORIGEN
    assert respuesta.headers.get("access-control-allow-credentials") == "true"
    assert "origin" in respuesta.headers.get("vary", "").lower()
    assert "x-request-id" in respuesta.headers.get("access-control-expose-headers", "").lower()


def test_preflight_permite_metodo_y_cabeceras_explicitos(cliente_cors: TestClient) -> None:
    respuesta = cliente_cors.options(
        "/api/v1/admin/auth/login",
        headers={
            "Origin": ORIGEN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )
    assert respuesta.status_code == 200
    assert respuesta.headers.get("access-control-allow-origin") == ORIGEN
    assert respuesta.headers.get("access-control-allow-credentials") == "true"
    assert "*" not in respuesta.headers.get("access-control-allow-methods", "")
    assert "*" not in respuesta.headers.get("access-control-allow-headers", "")
    assert respuesta.headers.get("x-request-id")


@pytest.mark.parametrize("origen", ["null", "https://ajeno.test", ORIGEN + ".ajeno.test"])
def test_cors_no_concede_lectura_a_origen_ajeno(cliente_cors: TestClient, origen: str) -> None:
    respuesta = cliente_cors.get("/health", headers={"Origin": origen})
    assert respuesta.status_code == 200
    assert "access-control-allow-origin" not in respuesta.headers


@pytest.mark.parametrize(("metodo", "cabecera"), [("TRACE", "content-type"), ("POST", "x-hostil")])
def test_preflight_rechaza_metodos_y_cabeceras_no_autorizados(
    cliente_cors: TestClient, metodo: str, cabecera: str
) -> None:
    respuesta = cliente_cors.options(
        "/api/v1/admin/auth/login",
        headers={
            "Origin": ORIGEN,
            "Access-Control-Request-Method": metodo,
            "Access-Control-Request-Headers": cabecera,
        },
    )
    assert respuesta.status_code == 400


@pytest.mark.parametrize(
    "ruta", ["/health", "/ready", "/api/v1/inexistente", "/api/v1/admin/auth/me"]
)
def test_cabeceras_api_tambien_en_errores(cliente_cors: TestClient, ruta: str) -> None:
    respuesta = cliente_cors.get(ruta)
    assert respuesta.headers.get("x-content-type-options") == "nosniff"
    assert respuesta.headers.get("x-frame-options") == "DENY"
    assert respuesta.headers.get("referrer-policy") == "no-referrer"
    assert "frame-ancestors 'none'" in respuesta.headers.get("content-security-policy", "")
    assert respuesta.headers.get("permissions-policy")
    assert respuesta.headers.get("x-robots-tag") == "noindex, nofollow"
    assert "strict-transport-security" not in respuesta.headers
    if "/admin/" in ruta:
        assert respuesta.headers.get("cache-control") == "no-store"


def test_sitemap_no_recibe_noindex(cliente_cors: TestClient) -> None:
    respuesta = cliente_cors.get("/sitemap.xml")
    assert "x-robots-tag" not in respuesta.headers


def test_un_500_conserva_cors_cabeceras_y_correlacion(cliente_cors: TestClient) -> None:
    application = cliente_cors.app
    assert isinstance(application, FastAPI)

    @application.get("/fallo018")
    def _fallo() -> None:
        raise RuntimeError(f"password={SENUELO}")

    respuesta = cliente_cors.get(
        "/fallo018", headers={"Origin": ORIGEN, "X-Request-ID": "task018-fallo-http"}
    )
    assert respuesta.status_code == 500
    assert SENUELO not in respuesta.text
    assert respuesta.headers.get("access-control-allow-origin") == ORIGEN
    assert respuesta.headers.get("x-content-type-options") == "nosniff"
    assert respuesta.headers.get("x-request-id") == "task018-fallo-http"
    assert respuesta.json()["error"]["request_id"] == "task018-fallo-http"


@pytest.mark.parametrize("estado", [400, 401, 403, 405, 422, 451, 503])
def test_excepcion_http_no_refleja_detalles_internos(application: FastAPI, estado: int) -> None:
    """451 no esta en la tabla de mensajes: es el caso que detecta un respaldo
    que devolviera `exc.detail`. Sin el, la prueba pasaria igual con la fuga."""

    @application.get("/error018")
    def _fallo() -> None:
        raise HTTPException(estado, f"SQL SELECT password={SENUELO} /srv/app/internal.py")

    with TestClient(application, raise_server_exceptions=False) as cliente:
        respuesta = cliente.get("/error018")
    assert respuesta.status_code == estado
    assert SENUELO not in respuesta.text
    assert "SELECT" not in respuesta.text
    assert "/srv/" not in respuesta.text


@pytest.mark.parametrize(
    "origen", ["http://sitio:abc", "http://sitio:99999", "http://*.test", "http://sitio\\ajeno"]
)
def test_origen_configurado_invalido_falla_sin_exponer_valor(
    settings_factory: Any, origen: str
) -> None:
    with pytest.raises(ConfigurationError) as error:
        settings_factory(admin_allowed_origins=origen)
    assert origen not in str(error.value)


def test_origen_duplicado_no_puede_evadir_csrf(cliente_cors: TestClient) -> None:
    respuesta = cliente_cors.post(
        "/api/v1/admin/auth/login",
        headers=[("Origin", ORIGEN), ("Origin", "https://ajeno.test")],
        json={"email": "prueba@example.test", "password": SENUELO},
    )
    assert respuesta.status_code == 403


def test_validacion_no_filtra_el_mensaje_de_un_validador(application: FastAPI) -> None:
    from fastapi.exceptions import RequestValidationError

    @application.get("/validacion018")
    def _validar() -> None:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", "pagina"),
                    "msg": f"Value error, SELECT password={SENUELO} /srv/app/internal.py",
                    "input": SENUELO,
                    "ctx": {"error": ValueError(SENUELO)},
                }
            ]
        )

    with TestClient(application, raise_server_exceptions=False) as cliente:
        respuesta = cliente.get("/validacion018")
    assert respuesta.status_code == 422
    assert SENUELO not in respuesta.text
    assert "SELECT" not in respuesta.text
    assert "/srv/" not in respuesta.text
    assert respuesta.json()["error"]["details"]["fields"][0]["field"] == "query.pagina"


def test_cors_vacio_no_abre_acceso_y_rechaza_escritura_de_navegador(
    settings_factory: Any,
) -> None:
    from app.main import create_app

    with TestClient(create_app(settings_factory(admin_allowed_origins=""))) as cliente:
        respuesta = cliente.get("/health", headers={"Origin": ORIGEN})
        assert "access-control-allow-origin" not in respuesta.headers
        respuesta = cliente.post(
            "/api/v1/admin/auth/login",
            headers={"Origin": ORIGEN},
            json={"email": "prueba@example.test", "password": SENUELO},
        )
        assert respuesta.status_code == 403
