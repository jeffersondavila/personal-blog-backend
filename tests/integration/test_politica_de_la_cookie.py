"""Atributos de la cookie de sesion (matriz C de `Task/011`, decision D-011-B).

Se comprueban sobre la cabecera `Set-Cookie` **real** que emite el servidor, no
sobre el objeto que el cliente guarda: los atributos son instrucciones para el
navegador, y lo que importa es que se envien.

Va en integracion y no en contrato porque emitir la cookie exige un inicio de
sesion correcto, y eso exige un administrador en PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.authentication.presentation.cookies import NOMBRE_DE_LA_COOKIE
from app.shared.configuration import Settings
from tests.integration.datos_de_autenticacion import CONTRASENA, CORREO, administrador

pytestmark = pytest.mark.integration

ACCESO = "/api/v1/admin/auth/login"
CIERRE = "/api/v1/admin/auth/logout"


@pytest.fixture
def cliente_configurable(
    database_settings: Settings, sesion_de_pruebas: Session
) -> Iterator[Callable[..., TestClient]]:
    """Fabrica clientes con la configuracion de cookie que pida la prueba.

    La cadena hasta la guarda *fail-closed* se mantiene: depende de
    `database_settings` y de `sesion_de_pruebas`, y ambas derivan del resolutor
    verificado.
    """
    from app.main import create_app
    from app.shared.database import get_session

    abiertos: list[TestClient] = []

    def _fabricar(**configuracion: object) -> TestClient:
        aplicacion = create_app(settings=database_settings.model_copy(update=configuracion))
        aplicacion.dependency_overrides[get_session] = lambda: sesion_de_pruebas
        cliente = TestClient(aplicacion, raise_server_exceptions=False)
        abiertos.append(cliente)
        return cliente

    try:
        yield _fabricar
    finally:
        for cliente in abiertos:
            cliente.close()


def _cookie_de_acceso(cliente: TestClient) -> str:
    respuesta = cliente.post(ACCESO, json={"email": CORREO, "password": CONTRASENA})
    assert respuesta.status_code == 200
    return respuesta.headers["set-cookie"]


# --- C-01 ------------------------------------------------------------------
def test_la_cookie_es_httponly(
    cliente_configurable: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Es la razon entera de elegir cookie en lugar de `localStorage`.

    Sin `HttpOnly`, cualquier script inyectado en el panel podria leer la
    credencial y llevarsela; con el, no puede.
    """
    administrador(sesion_de_pruebas)

    assert "HttpOnly" in _cookie_de_acceso(cliente_configurable(auth_cookie_secure=False))


# --- C-02 ------------------------------------------------------------------
def test_la_cookie_es_secure_cuando_la_politica_lo_exige(
    cliente_configurable: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)

    assert "Secure" in _cookie_de_acceso(cliente_configurable(auth_cookie_secure=True))


def test_la_cookie_no_es_secure_en_el_entorno_local(
    cliente_configurable: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Control del anterior, y la unica situacion en que se apaga.

    El entorno local sirve por HTTP; una cookie `Secure` no llegaria nunca. Que
    **produccion** no pueda apagarlo lo garantiza la configuracion, que no
    arranca con esa combinacion.
    """
    administrador(sesion_de_pruebas)

    assert "Secure" not in _cookie_de_acceso(cliente_configurable(auth_cookie_secure=False))


# --- C-03 ------------------------------------------------------------------
def test_la_cookie_declara_samesite_lax(
    cliente_configurable: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """`Lax` y no `None`: la topologia elegida hace la peticion *same-site*.

    Con `SameSite=None` la cookie seria de terceros —bloqueada por Safari y en
    retirada en Chrome—, y con `Strict` llegar al panel desde un enlace externo
    mostraria una sesion cerrada que en realidad sigue abierta.
    """
    administrador(sesion_de_pruebas)

    emitida = _cookie_de_acceso(cliente_configurable(auth_cookie_secure=False)).lower()

    assert "samesite=lax" in emitida
    assert "samesite=none" not in emitida
    assert "samesite=strict" not in emitida


# --- C-04 ------------------------------------------------------------------
def test_la_cookie_se_limita_al_prefijo_administrativo(
    cliente_configurable: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """No viaja a los diez endpoints publicos, que no la necesitan."""
    administrador(sesion_de_pruebas)

    assert "Path=/api/v1/admin" in _cookie_de_acceso(cliente_configurable(auth_cookie_secure=False))


def test_la_cookie_no_declara_dominio(
    cliente_configurable: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Sin `Domain` es *host-only*: no se comparte con ningun subdominio.

    Declararlo la enviaria tambien a subdominios que hoy no existen y que nadie
    ha revisado.
    """
    administrador(sesion_de_pruebas)

    assert "Domain=" not in _cookie_de_acceso(cliente_configurable(auth_cookie_secure=False))


def test_la_cookie_caduca_a_la_vez_que_la_sesion(
    cliente_configurable: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)

    emitida = _cookie_de_acceso(cliente_configurable(auth_cookie_secure=False))

    assert "Max-Age=43200" in emitida


# --- C-05 ------------------------------------------------------------------
def test_la_credencial_no_aparece_en_el_cuerpo(
    cliente_configurable: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Si estuviera tambien en el JSON, `HttpOnly` no protegeria nada."""
    administrador(sesion_de_pruebas)
    cliente = cliente_configurable(auth_cookie_secure=False)

    respuesta = cliente.post(ACCESO, json={"email": CORREO, "password": CONTRASENA})

    credencial = respuesta.cookies[NOMBRE_DE_LA_COOKIE]
    assert credencial not in respuesta.text


# --- C-06 ------------------------------------------------------------------
def test_el_borrado_repite_los_atributos_de_la_emision(
    cliente_configurable: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """El navegador solo sustituye una cookie si `Name`, `Domain` y `Path` coinciden.

    Borrarla con un `Path` distinto del de emision dejaria la cookie instalada
    aunque el servidor hubiera revocado la sesion.
    """
    administrador(sesion_de_pruebas)
    cliente = cliente_configurable(auth_cookie_secure=False)
    emitida = _cookie_de_acceso(cliente)

    borrada = cliente.post(CIERRE).headers["set-cookie"]

    assert borrada.startswith(f"{NOMBRE_DE_LA_COOKIE}=")
    for atributo in ("Path=/api/v1/admin", "HttpOnly"):
        assert atributo in emitida
        assert atributo in borrada
