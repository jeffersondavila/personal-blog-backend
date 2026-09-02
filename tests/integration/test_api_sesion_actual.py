"""`GET /api/v1/admin/auth/me` contra PostgreSQL real (matriz M de `Task/011`).

Comprueba lo unico que hace valioso a este endpoint: que la identidad que
devuelve **se deriva de la sesion**, no de nada que el cliente haya dicho.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.authentication.domain.sesion import (
    generar_credencial,
    huella_de_credencial,
)
from app.modules.authentication.infrastructure.models import AdministratorSession
from app.modules.authentication.infrastructure.repositorios import RepositorioSqlDeSesiones
from tests.integration.datos_de_autenticacion import CONTRASENA, CORREO, administrador

pytestmark = pytest.mark.integration

ACCESO = "/api/v1/admin/auth/login"
SESION_ACTUAL = "/api/v1/admin/auth/me"
COOKIE = "blog_admin_session"


def _iniciar_sesion(cliente: TestClient) -> None:
    respuesta = cliente.post(ACCESO, json={"email": CORREO, "password": CONTRASENA})
    assert respuesta.status_code == 200


def _consultar_con(cliente: TestClient, credencial: str | None = None) -> Any:
    """Consulta la sesion actual con la credencial indicada, o sin ninguna.

    La cookie se fija **en el cliente** y no en la peticion: httpx deprecó las
    cookies por peticion, y el proyecto ejecuta la suite con `-W error`, asi que
    usarlas convertiria cada una de estas pruebas en un fallo por advertencia.
    """
    cliente.cookies.clear()
    if credencial is not None:
        cliente.cookies.set(COOKIE, credencial)
    try:
        return cliente.get(SESION_ACTUAL)
    finally:
        cliente.cookies.clear()


# --- M-01 y M-07 -----------------------------------------------------------
def test_con_sesion_valida_devuelve_la_identidad(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)
    _iniciar_sesion(cliente_administrativo)

    respuesta = cliente_administrativo.get(SESION_ACTUAL)

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "id": str(fila.id),
        "email": CORREO,
        "display_name": fila.display_name,
    }


def test_la_identidad_devuelta_no_incluye_nada_mas(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas, intentos_fallidos=3)
    _iniciar_sesion(cliente_administrativo)

    assert set(cliente_administrativo.get(SESION_ACTUAL).json()) == {"id", "email", "display_name"}


# --- M-06 ------------------------------------------------------------------
def test_la_identidad_no_se_toma_de_lo_que_diga_el_cliente(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El cliente puede afirmar lo que quiera; la identidad sale de la sesion.

    Es la diferencia entre autenticar y creerse una cabecera.
    """
    fila = administrador(sesion_de_pruebas)
    _iniciar_sesion(cliente_administrativo)

    respuesta = cliente_administrativo.get(
        SESION_ACTUAL,
        headers={
            "X-Administrator-Email": "otro@example.invalid",
            "X-Administrator-Id": "00000000-0000-0000-0000-000000000001",
        },
        params=None,
    )

    assert respuesta.json()["email"] == CORREO
    assert respuesta.json()["id"] == str(fila.id)


# --- M-02 ------------------------------------------------------------------
def test_sin_cookie_responde_401(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)

    respuesta = cliente_administrativo.get(SESION_ACTUAL)

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "unauthenticated"


# --- M-03 ------------------------------------------------------------------
def test_una_credencial_desconocida_responde_401(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)

    respuesta = _consultar_con(cliente_administrativo, generar_credencial())

    assert respuesta.status_code == 401


def test_una_credencial_con_forma_invalida_responde_401_y_no_estalla(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Basura en la cookie es una entrada hostil como cualquier otra."""
    administrador(sesion_de_pruebas)

    for basura in ("   ", "no-es-una-credencial", "a" * 5000):
        assert _consultar_con(cliente_administrativo, basura).status_code == 401


# --- M-04 ------------------------------------------------------------------
def test_una_sesion_caducada_responde_401(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)
    credencial = generar_credencial()
    RepositorioSqlDeSesiones(sesion_de_pruebas).crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(credencial),
        expira_en=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert _consultar_con(cliente_administrativo, credencial).status_code == 401


def test_una_sesion_vigente_creada_a_mano_si_autentica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Control positivo de la prueba anterior.

    Sin el, una implementacion que rechazara **toda** credencial creada fuera del
    endpoint de acceso pasaria la comprobacion de caducidad sin comprobar nada.
    """
    fila = administrador(sesion_de_pruebas)
    credencial = generar_credencial()
    RepositorioSqlDeSesiones(sesion_de_pruebas).crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(credencial),
        expira_en=datetime.now(UTC) + timedelta(hours=1),
    )

    respuesta = _consultar_con(cliente_administrativo, credencial)

    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == str(fila.id)


# --- M-05 ------------------------------------------------------------------
def test_una_sesion_revocada_responde_401(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)
    credencial = generar_credencial()
    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)
    repositorio.crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(credencial),
        expira_en=datetime.now(UTC) + timedelta(hours=1),
    )
    repositorio.revocar(huella_de_credencial(credencial), instante=datetime.now(UTC))

    assert _consultar_con(cliente_administrativo, credencial).status_code == 401


# --- Los cuatro rechazos son el mismo --------------------------------------
def test_los_cuatro_motivos_de_rechazo_responden_igual(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Cual de los cuatro ocurrio es estado interno del servidor.

    Al cliente le sirve exactamente para lo mismo en los cuatro casos: volver a
    iniciar sesion.
    """
    fila = administrador(sesion_de_pruebas)
    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)

    caducada = generar_credencial()
    repositorio.crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(caducada),
        expira_en=datetime.now(UTC) - timedelta(seconds=1),
    )
    revocada = generar_credencial()
    repositorio.crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(revocada),
        expira_en=datetime.now(UTC) + timedelta(hours=1),
    )
    repositorio.revocar(huella_de_credencial(revocada), instante=datetime.now(UTC))

    cuerpos = []
    for credencial in (None, generar_credencial(), caducada, revocada):
        respuesta = _consultar_con(cliente_administrativo, credencial)
        assert respuesta.status_code == 401
        cuerpo = respuesta.json()
        cuerpo["error"].pop("request_id")
        cuerpos.append(cuerpo)

    assert cuerpos[1:] == cuerpos[:-1], f"los rechazos no son indistinguibles: {cuerpos}"


# --- Aislamiento entre sesiones --------------------------------------------
def test_cada_sesion_resuelve_a_su_propio_administrador(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Con dos sesiones vivas, cada credencial debe resolver la suya.

    Aunque hoy haya un unico administrador, resolver "la ultima sesion creada"
    en lugar de "la sesion de esta credencial" seria un defecto que solo se veria
    el dia que hubiera dos.
    """
    fila = administrador(sesion_de_pruebas)
    _iniciar_sesion(cliente_administrativo)
    primera = cliente_administrativo.cookies[COOKIE]
    cliente_administrativo.cookies.clear()
    _iniciar_sesion(cliente_administrativo)
    segunda = cliente_administrativo.cookies[COOKIE]
    cliente_administrativo.cookies.clear()

    assert primera != segunda
    assert len(list(sesion_de_pruebas.execute(select(AdministratorSession)).scalars())) == 2
    for credencial in (primera, segunda):
        respuesta = _consultar_con(cliente_administrativo, credencial)
        assert respuesta.status_code == 200
        assert respuesta.json()["id"] == str(fila.id)


# --- Cache -----------------------------------------------------------------
def test_la_sesion_actual_no_se_cachea(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Es la respuesta mas peligrosa de cachear: lleva una identidad dentro."""
    administrador(sesion_de_pruebas)
    _iniciar_sesion(cliente_administrativo)

    assert cliente_administrativo.get(SESION_ACTUAL).headers["cache-control"] == "no-store"
