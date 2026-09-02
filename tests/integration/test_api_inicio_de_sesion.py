"""`POST /api/v1/admin/auth/login` contra PostgreSQL real (matriz L de `Task/011`).

Es el **unico endpoint administrativo publico** (security-boundaries.md seccion 2)
y, por serlo, el que mas se prueba: cada respuesta que distinga un caso de otro es
informacion que un atacante puede usar para enumerar cuentas.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.authentication.infrastructure.models import (
    Administrator,
    AdministratorSession,
)
from tests.integration.datos_de_autenticacion import CONTRASENA, CORREO, administrador

pytestmark = pytest.mark.integration

ACCESO = "/api/v1/admin/auth/login"


def _acceder(cliente: TestClient, *, correo: str = CORREO, contrasena: str = CONTRASENA) -> Any:
    return cliente.post(ACCESO, json={"email": correo, "password": contrasena})


# --- L-01 ------------------------------------------------------------------
def test_las_credenciales_correctas_inician_sesion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)

    respuesta = _acceder(cliente_administrativo)

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "id": str(fila.id),
        "email": CORREO,
        "display_name": fila.display_name,
    }


def test_el_acceso_correcto_entrega_la_cookie_de_sesion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)

    respuesta = _acceder(cliente_administrativo)

    assert "blog_admin_session" in respuesta.cookies


def test_el_correo_se_acepta_con_cualquier_combinacion_de_mayusculas(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El propietario escribe su propio correo: no debe fallar por una mayuscula."""
    administrador(sesion_de_pruebas)

    assert _acceder(cliente_administrativo, correo=CORREO.upper()).status_code == 200


# --- L-02, L-03 y L-04 -----------------------------------------------------
def test_un_correo_inexistente_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)

    respuesta = _acceder(cliente_administrativo, correo="nadie@example.invalid")

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "invalid_credentials"


def test_una_contrasena_incorrecta_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)

    respuesta = _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "invalid_credentials"


def test_el_correo_inexistente_y_la_contrasena_incorrecta_son_indistinguibles(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """USER_FLOWS.md B.1: el error es generico y no revela si el usuario existe.

    Se comparan **estado, codigo y mensaje**. El `request_id` cambia por
    definicion en cada peticion y se retira antes de comparar: es correlacion,
    no informacion sobre la cuenta.
    """
    administrador(sesion_de_pruebas)

    inexistente = _acceder(cliente_administrativo, correo="nadie@example.invalid")
    equivocada = _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    assert inexistente.status_code == equivocada.status_code

    def sin_correlacion(respuesta: Any) -> dict[str, Any]:
        cuerpo: dict[str, Any] = respuesta.json()
        cuerpo["error"].pop("request_id")
        return cuerpo

    assert sin_correlacion(inexistente) == sin_correlacion(equivocada)


def test_ningun_rechazo_entrega_cookie_de_sesion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)

    respuesta = _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    assert "set-cookie" not in {clave.lower() for clave in respuesta.headers}


# --- L-05 y L-06 -----------------------------------------------------------
def test_el_acceso_correcto_fecha_el_ultimo_ingreso(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)
    assert fila.last_login_at is None

    _acceder(cliente_administrativo)
    sesion_de_pruebas.expire_all()

    assert fila.last_login_at is not None


def test_el_acceso_correcto_reinicia_el_contador_de_fallos(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas, intentos_fallidos=3)

    _acceder(cliente_administrativo)
    sesion_de_pruebas.expire_all()

    assert fila.failed_login_attempts == 0
    assert fila.locked_until is None


# --- L-07 ------------------------------------------------------------------
def test_el_acceso_correcto_persiste_una_sesion_para_ese_administrador(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)

    _acceder(cliente_administrativo)

    sesiones = list(sesion_de_pruebas.execute(select(AdministratorSession)).scalars())
    assert len(sesiones) == 1
    assert sesiones[0].administrator_id == fila.id
    assert sesiones[0].revoked_at is None


def test_la_sesion_persistida_corresponde_a_la_cookie_entregada(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Cierra el circulo: la huella guardada es la de la credencial recibida."""
    from app.modules.authentication.domain.sesion import huella_de_credencial

    administrador(sesion_de_pruebas)

    respuesta = _acceder(cliente_administrativo)

    credencial = respuesta.cookies["blog_admin_session"]
    persistida = sesion_de_pruebas.execute(select(AdministratorSession)).scalar_one()
    assert persistida.token_hash == huella_de_credencial(credencial)


def test_dos_accesos_correctos_crean_dos_sesiones(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Politica D-011-E: el propietario puede tener portatil y movil a la vez."""
    administrador(sesion_de_pruebas)

    _acceder(cliente_administrativo)
    _acceder(cliente_administrativo)

    sesiones = list(sesion_de_pruebas.execute(select(AdministratorSession)).scalars())
    assert len(sesiones) == 2
    assert len({sesion.token_hash for sesion in sesiones}) == 2


# --- L-08 ------------------------------------------------------------------
def test_la_respuesta_no_transporta_ningun_secreto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """La credencial vive en la cookie `HttpOnly`, y solo ahi.

    Si apareciera tambien en el cuerpo, JavaScript podria leerla y `HttpOnly`
    dejaria de proteger nada — que es el motivo entero de haber elegido cookie.
    """
    fila = administrador(sesion_de_pruebas)

    respuesta = _acceder(cliente_administrativo)

    cuerpo = respuesta.text
    assert respuesta.cookies["blog_admin_session"] not in cuerpo
    assert fila.password_hash not in cuerpo
    assert CONTRASENA not in cuerpo


def test_la_respuesta_no_expone_el_estado_defensivo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Cuantos intentos fallidos lleva la cuenta no es asunto del cliente."""
    administrador(sesion_de_pruebas, intentos_fallidos=2)

    devuelto = set(_acceder(cliente_administrativo).json())

    assert devuelto == {"id", "email", "display_name"}


# --- L-09 ------------------------------------------------------------------
def test_sin_administrador_el_acceso_se_rechaza_sin_estallar(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Una base recien migrada no tiene administrador (no lo crea ninguna migracion).

    Debe responder como cualquier credencial invalida: ni `500`, ni un mensaje
    que anuncie que el sistema esta sin configurar, ni —desde luego— crear un
    administrador por su cuenta.
    """
    assert sesion_de_pruebas.execute(select(Administrator)).first() is None

    respuesta = _acceder(cliente_administrativo)

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "invalid_credentials"
    assert sesion_de_pruebas.execute(select(Administrator)).first() is None


def test_el_mensaje_de_rechazo_no_menciona_la_configuracion_del_sistema(
    cliente_administrativo: TestClient,
) -> None:
    mensaje = _acceder(cliente_administrativo).json()["error"]["message"].lower()

    for delator in ("administrador", "configur", "no existe", "vacia", "vacía"):
        assert delator not in mensaje, f"el mensaje delata el estado interno: {mensaje!r}"


# --- Cache -----------------------------------------------------------------
def test_la_respuesta_de_acceso_no_se_cachea(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Una respuesta de autenticacion en una cache compartida es una fuga.

    `200` es cacheable por defecto segun la norma; decirlo explicitamente cuesta
    una cabecera.
    """
    administrador(sesion_de_pruebas)

    respuesta = _acceder(cliente_administrativo)

    assert respuesta.headers["cache-control"] == "no-store"
