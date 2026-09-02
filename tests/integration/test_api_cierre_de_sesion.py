"""`POST /api/v1/admin/auth/logout` contra PostgreSQL real (matriz O de `Task/011`).

USER_FLOWS.md B.12 no pide que el navegador olvide la cookie: pide que la sesion
**se invalide en el servidor**. La diferencia es exactamente la prueba
`test_la_misma_credencial_ya_no_autentica_despues_de_cerrar_sesion`, y es la que
justifica toda la decision D-011-B.
"""

from __future__ import annotations

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
from tests.integration.datos_de_autenticacion import CONTRASENA, CORREO, administrador

pytestmark = pytest.mark.integration

ACCESO = "/api/v1/admin/auth/login"
CIERRE = "/api/v1/admin/auth/logout"
SESION_ACTUAL = "/api/v1/admin/auth/me"
COOKIE = "blog_admin_session"


def _iniciar_sesion(cliente: TestClient) -> str:
    respuesta = cliente.post(ACCESO, json={"email": CORREO, "password": CONTRASENA})
    assert respuesta.status_code == 200
    return respuesta.cookies[COOKIE]


def _con_credencial(cliente: TestClient, credencial: str, metodo: str, ruta: str) -> Any:
    """Ejecuta una peticion con la credencial indicada fijada en el cliente."""
    cliente.cookies.clear()
    cliente.cookies.set(COOKIE, credencial)
    try:
        return cliente.request(metodo, ruta)
    finally:
        cliente.cookies.clear()


# --- O-01 ------------------------------------------------------------------
def test_cerrar_sesion_responde_sin_contenido(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)
    _iniciar_sesion(cliente_administrativo)

    respuesta = cliente_administrativo.post(CIERRE)

    assert respuesta.status_code == 204
    assert respuesta.content == b""


def test_cerrar_sesion_marca_la_revocacion_en_la_base(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """La revocacion es un hecho persistido, no un estado en memoria.

    Tiene que serlo: en Lambda la peticion siguiente puede atenderla otra
    instancia, que no comparte memoria con esta.
    """
    administrador(sesion_de_pruebas)
    _iniciar_sesion(cliente_administrativo)

    cliente_administrativo.post(CIERRE)
    sesion_de_pruebas.expire_all()

    fila = sesion_de_pruebas.execute(select(AdministratorSession)).scalar_one()
    assert fila.revoked_at is not None


# --- O-02: la prueba que da sentido a la tarea ------------------------------
def test_la_misma_credencial_ya_no_autentica_despues_de_cerrar_sesion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """**Esta es la comprobacion que un JWT no podria pasar.**

    Se guarda la credencial **antes** de cerrar sesion y se vuelve a presentar
    despues, saltandose el borrado de la cookie. Si la invalidacion viviera solo
    en el navegador —"logout borra el token"—, esta credencial seguiria abriendo
    la sesion y el contrato de USER_FLOWS.md B.12 no se cumpliria.
    """
    administrador(sesion_de_pruebas)
    credencial = _iniciar_sesion(cliente_administrativo)
    assert cliente_administrativo.get(SESION_ACTUAL).status_code == 200

    cliente_administrativo.post(CIERRE)

    reutilizada = _con_credencial(cliente_administrativo, credencial, "GET", SESION_ACTUAL)
    assert reutilizada.status_code == 401
    assert reutilizada.json()["error"]["code"] == "unauthenticated"


def test_la_credencial_revocada_tampoco_sirve_para_volver_a_cerrar_sesion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)
    credencial = _iniciar_sesion(cliente_administrativo)
    cliente_administrativo.post(CIERRE)

    repetido = _con_credencial(cliente_administrativo, credencial, "POST", CIERRE)

    assert repetido.status_code == 401


# --- O-04 ------------------------------------------------------------------
def test_cerrar_sesion_pide_al_navegador_que_olvide_la_cookie(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Es la mitad cosmetica del cierre; la que protege es la revocacion.

    Los atributos deben coincidir con los de emision o el navegador no encuentra
    la cookie que debe sustituir y se queda con la anterior.
    """
    administrador(sesion_de_pruebas)
    _iniciar_sesion(cliente_administrativo)

    respuesta = cliente_administrativo.post(CIERRE)

    emitida = respuesta.headers["set-cookie"]
    assert emitida.startswith(f"{COOKIE}=")
    assert "Path=/api/v1/admin" in emitida
    assert "HttpOnly" in emitida


def test_el_cliente_deja_de_estar_autenticado_tras_cerrar_sesion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Comportamiento observable desde el navegador, sin manipular cookies."""
    administrador(sesion_de_pruebas)
    _iniciar_sesion(cliente_administrativo)

    cliente_administrativo.post(CIERRE)

    assert cliente_administrativo.get(SESION_ACTUAL).status_code == 401


# --- O-05 ------------------------------------------------------------------
def test_cerrar_sesion_sin_sesion_responde_401(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """No es una operacion publica: `logout` exige una sesion valida."""
    administrador(sesion_de_pruebas)

    respuesta = cliente_administrativo.post(CIERRE)

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "unauthenticated"


def test_cerrar_sesion_con_una_credencial_desconocida_responde_401(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)

    respuesta = _con_credencial(cliente_administrativo, generar_credencial(), "POST", CIERRE)

    assert respuesta.status_code == 401


# --- Aislamiento entre sesiones --------------------------------------------
def test_cerrar_una_sesion_no_cierra_las_demas(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Politica D-011-E: `logout` cierra **la** sesion, no todas.

    Cerrar sesion en el movil no debe expulsar al propietario del portatil.
    "Cerrar todas las sesiones" no lo pide ninguna fuente canonica y no se
    inventa aqui.
    """
    administrador(sesion_de_pruebas)
    primera = _iniciar_sesion(cliente_administrativo)
    cliente_administrativo.cookies.clear()
    segunda = _iniciar_sesion(cliente_administrativo)
    cliente_administrativo.cookies.clear()

    assert _con_credencial(cliente_administrativo, primera, "POST", CIERRE).status_code == 204

    assert _con_credencial(cliente_administrativo, primera, "GET", SESION_ACTUAL).status_code == 401
    assert _con_credencial(cliente_administrativo, segunda, "GET", SESION_ACTUAL).status_code == 200


def test_la_revocacion_afecta_a_una_unica_fila(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Control estructural del caso anterior, mirando la base."""
    administrador(sesion_de_pruebas)
    primera = _iniciar_sesion(cliente_administrativo)
    cliente_administrativo.cookies.clear()
    _iniciar_sesion(cliente_administrativo)
    cliente_administrativo.cookies.clear()

    _con_credencial(cliente_administrativo, primera, "POST", CIERRE)
    sesion_de_pruebas.expire_all()

    filas = list(sesion_de_pruebas.execute(select(AdministratorSession)).scalars())
    revocadas = [fila for fila in filas if fila.revoked_at is not None]
    assert len(filas) == 2
    assert len(revocadas) == 1
    assert revocadas[0].token_hash == huella_de_credencial(primera)


# --- Cache -----------------------------------------------------------------
def test_la_respuesta_de_cierre_no_se_cachea(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)
    _iniciar_sesion(cliente_administrativo)

    assert cliente_administrativo.post(CIERRE).headers["cache-control"] == "no-store"
