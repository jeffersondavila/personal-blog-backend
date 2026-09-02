"""Contrato HTTP de la autenticacion administrativa (matriz C y P de `Task/011`).

Aqui se comprueba la **forma**: rutas, metodos, codigos, esquema de seguridad y
la politica de `Origin`. La semantica —que unas credenciales validas abran sesion,
que el bloqueo cuente— vive en `tests/integration/` contra PostgreSQL real
(BACKEND_TESTING_STRATEGY.md seccion 8.3).

Ninguna prueba de este modulo alcanza la base de datos, y no es casualidad: el
rechazo por origen y el rechazo por falta de sesion ocurren **antes** de que la
peticion llegue a consultar nada. Si alguna acabara tocando PostgreSQL, la sesion
prohibida del harness la pondria roja.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shared.configuration import Settings
from app.shared.database import get_session

ACCESO = "/api/v1/admin/auth/login"
CIERRE = "/api/v1/admin/auth/logout"
SESION_ACTUAL = "/api/v1/admin/auth/me"

PERMITIDO = "https://example.com"
AJENO = "https://evil.invalid"

CREDENCIALES = {"email": "administrador@example.invalid", "password": "da-igual"}


@pytest.fixture
def cliente_con_origenes(settings_factory: Any) -> Iterator[TestClient]:
    """Aplicacion con un origen administrativo declarado y sin base de datos.

    La sesion se sustituye por la guarda del harness de contrato: cualquier
    prueba de este modulo que llegara a consultar se pondria roja en lugar de
    pasar por accidente.
    """
    from app.main import create_app
    from tests.contract.conftest import _SesionProhibida

    configuracion: Settings = settings_factory(admin_allowed_origins=PERMITIDO)
    aplicacion: FastAPI = create_app(settings=configuracion)

    def _sesion_prohibida() -> Iterator[Any]:
        yield _SesionProhibida()

    aplicacion.dependency_overrides[get_session] = _sesion_prohibida
    with TestClient(aplicacion, raise_server_exceptions=False) as cliente:
        yield cliente


# --- C-07 ------------------------------------------------------------------
def test_un_origen_ajeno_no_puede_iniciar_sesion(cliente_con_origenes: TestClient) -> None:
    """Defensa CSRF de segunda capa: se rechaza **antes** de mirar credenciales.

    Responde `403` y no `401` porque no es un problema de identidad: la peticion
    podria traer credenciales perfectamente validas y aun asi no debe ejecutarse.
    """
    respuesta = cliente_con_origenes.post(ACCESO, json=CREDENCIALES, headers={"Origin": AJENO})

    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "forbidden"


def test_un_origen_ajeno_no_puede_cerrar_sesion(cliente_con_origenes: TestClient) -> None:
    respuesta = cliente_con_origenes.post(CIERRE, headers={"Origin": AJENO})

    assert respuesta.status_code == 403


def test_el_rechazo_por_origen_usa_la_envoltura_de_error_del_proyecto(
    cliente_con_origenes: TestClient,
) -> None:
    cuerpo = cliente_con_origenes.post(ACCESO, json=CREDENCIALES, headers={"Origin": AJENO}).json()

    assert set(cuerpo) == {"error"}
    assert set(cuerpo["error"]) == {"code", "message", "details", "request_id"}


def test_el_rechazo_por_origen_no_entrega_ninguna_cookie(
    cliente_con_origenes: TestClient,
) -> None:
    respuesta = cliente_con_origenes.post(ACCESO, json=CREDENCIALES, headers={"Origin": AJENO})

    assert "set-cookie" not in {clave.lower() for clave in respuesta.headers}


# --- C-08 ------------------------------------------------------------------
def test_el_origen_declarado_atraviesa_la_comprobacion(
    cliente_con_origenes: TestClient,
) -> None:
    """Control positivo, y la unica forma de saber que la guarda no rechaza todo.

    Se usa `logout` **sin cookie**: la peticion pasa la comprobacion de origen y
    se detiene en la de sesion, sin llegar a la base de datos. Un `401` demuestra
    que el origen se acepto; un `403` demostraria lo contrario.
    """
    respuesta = cliente_con_origenes.post(CIERRE, headers={"Origin": PERMITIDO})

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "unauthenticated"


# --- C-09 ------------------------------------------------------------------
def test_una_peticion_sin_origen_atraviesa_la_comprobacion(
    cliente_con_origenes: TestClient,
) -> None:
    """Un cliente que no es un navegador no puede montar un CSRF."""
    respuesta = cliente_con_origenes.post(CIERRE)

    assert respuesta.status_code == 401


# --- C-10 ------------------------------------------------------------------
def test_una_lectura_desde_un_origen_ajeno_no_se_rechaza_por_origen(
    cliente_con_origenes: TestClient,
) -> None:
    """`GET /me` no cambia estado, asi que la politica no le aplica.

    Sigue exigiendo sesion —de ahi el `401`—, pero el motivo del rechazo es la
    falta de credencial y no el origen. Que un `403` apareciera aqui indicaria
    que la comprobacion se esta aplicando donde no toca.
    """
    respuesta = cliente_con_origenes.get(SESION_ACTUAL, headers={"Origin": AJENO})

    assert respuesta.status_code == 401


# --- Fail-closed sin configuracion -----------------------------------------
def test_sin_origenes_declarados_ningun_navegador_puede_escribir(
    cliente_publico: TestClient,
) -> None:
    """`cliente_publico` no declara ningun origen administrativo.

    Consecuencia deliberada de la decision D-011-K, y documentada en
    `.env.example`: hasta que se declare el origen del panel, ninguna peticion
    con `Origin` puede iniciar ni cerrar sesion. No existe un origen por defecto
    seguro y no se supone ninguno.
    """
    respuesta = cliente_publico.post(ACCESO, json=CREDENCIALES, headers={"Origin": PERMITIDO})

    assert respuesta.status_code == 403


# --- P-01 a P-05: especificacion OpenAPI -----------------------------------
@pytest.fixture
def documento(cliente_publico: TestClient) -> dict[str, Any]:
    contenido: dict[str, Any] = cliente_publico.get("/openapi.json").json()
    return contenido


def test_la_especificacion_declara_los_tres_endpoints_de_autenticacion(
    documento: dict[str, Any],
) -> None:
    administrativas = {ruta for ruta in documento["paths"] if "/admin" in ruta}

    assert administrativas == {ACCESO, CIERRE, SESION_ACTUAL}


def test_no_se_declara_ningun_crud_administrativo(documento: dict[str, Any]) -> None:
    """El CRUD administrativo es de `Task/012` y todavia no existe.

    Documentar una superficie que no esta implementada es peor que no
    documentarla: un cliente generado a partir de la especificacion fallaria al
    llamarla.
    """
    for recurso in ("posts", "book-reviews", "videos", "projects", "tags", "media", "profile"):
        assert f"/api/v1/admin/{recurso}" not in documento["paths"]


def test_el_acceso_es_el_unico_endpoint_administrativo_publico(
    documento: dict[str, Any],
) -> None:
    """security-boundaries.md seccion 2: `login` y nada mas."""
    assert "security" not in documento["paths"][ACCESO]["post"]


@pytest.mark.parametrize(("ruta", "metodo"), [(CIERRE, "post"), (SESION_ACTUAL, "get")])
def test_los_endpoints_protegidos_declaran_su_requisito_de_seguridad(
    documento: dict[str, Any], ruta: str, metodo: str
) -> None:
    requisitos = documento["paths"][ruta][metodo]["security"]

    assert requisitos == [{"sesionAdministrativa": []}]


def test_el_esquema_de_seguridad_describe_la_cookie_real(documento: dict[str, Any]) -> None:
    """OpenAPI no puede mentir sobre como se autentica.

    Un esquema `http`/`bearer` describiria una cabecera `Authorization` que este
    backend **no lee**, y un cliente generado a partir de el no se autenticaria
    nunca.
    """
    from app.modules.authentication.presentation.cookies import NOMBRE_DE_LA_COOKIE

    esquema = documento["components"]["securitySchemes"]["sesionAdministrativa"]

    assert esquema["type"] == "apiKey"
    assert esquema["in"] == "cookie"
    assert esquema["name"] == NOMBRE_DE_LA_COOKIE


def test_las_rutas_publicas_no_declaran_ningun_requisito_de_seguridad(
    documento: dict[str, Any],
) -> None:
    """Regresion de `Task/009`: la API publica sigue siendo anonima.

    Es la comprobacion que detectaria el error mas caro de esta tarea —proteger
    `/api/v1` entero por comodidad— sin necesidad de recorrer cada endpoint a
    mano.
    """
    for ruta, operaciones in documento["paths"].items():
        if "/admin" in ruta:
            continue
        for metodo, operacion in operaciones.items():
            assert "security" not in operacion, f"{metodo.upper()} {ruta} exige autenticacion"


# --- P-06 ------------------------------------------------------------------
def test_el_contrato_publico_no_cambia(documento: dict[str, Any]) -> None:
    """Las diez rutas publicas y la sonda de vivacidad, intactas."""
    publicas = {ruta for ruta in documento["paths"] if "/admin" not in ruta}

    assert publicas == {
        "/health",
        "/api/v1/profile",
        "/api/v1/posts",
        "/api/v1/posts/{slug}",
        "/api/v1/book-reviews",
        "/api/v1/book-reviews/{slug}",
        "/api/v1/videos",
        "/api/v1/projects",
        "/api/v1/projects/{slug}",
        "/api/v1/tags",
        "/api/v1/search",
    }
