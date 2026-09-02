"""Bloqueo de cuenta sobre PostgreSQL real (matriz B de `Task/011`).

Aqui se comprueba lo que las reglas puras no pueden: que el estado **se
persiste**, que el bloqueo **se aplica al responder** y que dos intentos
simultaneos no se pisan.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.authentication.infrastructure.models import (
    Administrator,
    AdministratorSession,
)
from app.shared.configuration import Settings
from tests.integration.datos_de_autenticacion import (
    CONTRASENA,
    CORREO,
    administrador,
    limpiar_autenticacion,
)

pytestmark = pytest.mark.integration

ACCESO = "/api/v1/admin/auth/login"
UMBRAL = 5


def _fallar(cliente: TestClient) -> Any:
    return cliente.post(ACCESO, json={"email": CORREO, "password": "no-es-la-contrasena"})


def _acertar(cliente: TestClient) -> Any:
    return cliente.post(ACCESO, json={"email": CORREO, "password": CONTRASENA})


# --- B-01 y B-02 -----------------------------------------------------------
def test_un_fallo_incrementa_el_contador_persistido(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)

    _fallar(cliente_de_la_api)
    sesion_de_pruebas.expire_all()

    assert fila.failed_login_attempts == 1
    assert fila.locked_until is None


def test_los_fallos_anteriores_al_umbral_no_bloquean(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)

    for _ in range(UMBRAL - 1):
        _fallar(cliente_de_la_api)
    sesion_de_pruebas.expire_all()

    assert fila.failed_login_attempts == UMBRAL - 1
    assert fila.locked_until is None


def test_las_credenciales_correctas_siguen_valiendo_antes_del_umbral(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """Control positivo: la cuenta todavia no esta bloqueada."""
    administrador(sesion_de_pruebas)
    for _ in range(UMBRAL - 1):
        _fallar(cliente_de_la_api)

    assert _acertar(cliente_de_la_api).status_code == 200


# --- B-03 ------------------------------------------------------------------
def test_el_fallo_numero_umbral_activa_el_bloqueo(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)

    for _ in range(UMBRAL):
        _fallar(cliente_de_la_api)
    sesion_de_pruebas.expire_all()

    assert fila.failed_login_attempts == UMBRAL
    assert fila.locked_until is not None
    assert fila.locked_until > datetime.now(UTC)


# --- B-04 ------------------------------------------------------------------
def test_durante_el_bloqueo_ni_las_credenciales_correctas_entran(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """Es lo que hace del bloqueo una proteccion y no un adorno."""
    administrador(
        sesion_de_pruebas,
        intentos_fallidos=UMBRAL,
        bloqueado_hasta=datetime.now(UTC) + timedelta(minutes=15),
    )

    respuesta = _acertar(cliente_de_la_api)

    assert respuesta.status_code == 401
    assert not list(sesion_de_pruebas.execute(select(AdministratorSession)).scalars())


def test_el_bloqueo_no_se_distingue_de_unas_credenciales_invalidas(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision D-011-L, y es la que mas cuesta explicar: la cuenta bloqueada
    responde **igual** que cualquier otro rechazo.

    Si respondiera distinto, averiguar el correo real seria trivial: se envia el
    umbral de intentos a un correo cualquiera y se mira si la respuesta cambia.
    Con un correo inventado nunca cambiaria —no hay cuenta que bloquear—; con el
    real, si.

    El precio esta aceptado y documentado: el propietario que se bloquee a si
    mismo vera "credenciales invalidas". El motivo real queda en la auditoria y
    en el log, que es donde el operador puede consultarlo.
    """
    administrador(
        sesion_de_pruebas,
        intentos_fallidos=UMBRAL,
        bloqueado_hasta=datetime.now(UTC) + timedelta(minutes=15),
    )

    bloqueada = _acertar(cliente_de_la_api)
    inexistente = cliente_de_la_api.post(
        ACCESO, json={"email": "nadie@example.invalid", "password": CONTRASENA}
    )

    assert bloqueada.status_code == inexistente.status_code

    def sin_correlacion(respuesta: Any) -> dict[str, Any]:
        cuerpo: dict[str, Any] = respuesta.json()
        cuerpo["error"].pop("request_id")
        return cuerpo

    assert sin_correlacion(bloqueada) == sin_correlacion(inexistente)


def test_un_fallo_durante_el_bloqueo_no_lo_alarga(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """Si cada intento desplazara el bloqueo, un atacante podria mantener al
    propietario fuera de su panel indefinidamente.
    """
    vence = datetime.now(UTC) + timedelta(minutes=15)
    fila = administrador(sesion_de_pruebas, intentos_fallidos=UMBRAL, bloqueado_hasta=vence)

    _fallar(cliente_de_la_api)
    sesion_de_pruebas.expire_all()

    assert fila.locked_until == vence


# --- B-05 y B-06 -----------------------------------------------------------
def test_tras_vencer_el_bloqueo_se_vuelve_a_admitir_el_intento(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador(
        sesion_de_pruebas,
        intentos_fallidos=UMBRAL,
        bloqueado_hasta=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert _acertar(cliente_de_la_api).status_code == 200


def test_el_primer_fallo_tras_vencer_el_bloqueo_no_vuelve_a_bloquear(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """Sin el reinicio del contador, el bloqueo temporal seria permanente en la
    practica: el contador seguiria en el umbral y un solo fallo bastaria.
    """
    fila = administrador(
        sesion_de_pruebas,
        intentos_fallidos=UMBRAL,
        bloqueado_hasta=datetime.now(UTC) - timedelta(seconds=1),
    )

    _fallar(cliente_de_la_api)
    sesion_de_pruebas.expire_all()

    assert fila.failed_login_attempts == 1
    assert fila.locked_until is None


def test_el_acceso_correcto_limpia_contador_y_bloqueo(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(
        sesion_de_pruebas,
        intentos_fallidos=UMBRAL,
        bloqueado_hasta=datetime.now(UTC) - timedelta(seconds=1),
    )

    _acertar(cliente_de_la_api)
    sesion_de_pruebas.expire_all()

    assert fila.failed_login_attempts == 0
    assert fila.locked_until is None


# --- B-07: concurrencia ----------------------------------------------------
def test_dos_fallos_simultaneos_cuentan_dos(
    database_engine: Engine,
    database_settings: Settings,
    esquema_migrado: None,
    configured_process: None,
) -> None:
    """`failed_login_attempts` es estado de seguridad y no puede perder escrituras.

    Sin bloqueo de fila, las dos peticiones leen el mismo contador, las dos
    escriben el mismo valor y **una de las dos actualizaciones desaparece**: un
    umbral de cinco intentos se convertiria, ante un atacante que pida en
    paralelo, en uno de diez o mas.

    La prueba es determinista y no depende de ganar ninguna carrera: las dos
    peticiones se lanzan a la vez y **se exige el resultado correcto**, que es
    exactamente 2. Con la implementacion ingenua el resultado seria 1.

    Va contra dos conexiones reales —por eso no usa la sesion transaccional del
    harness—: el bloqueo de fila lo da PostgreSQL, y con una sola conexion no hay
    nada que serializar.
    """
    from app.main import create_app

    with Session(database_engine) as preparacion:
        limpiar_autenticacion(preparacion)
        administrador(preparacion)
        preparacion.commit()

    aplicacion = create_app(settings=database_settings)
    barrera = threading.Barrier(2)
    respuestas: list[int] = []

    def intentar() -> None:
        with TestClient(aplicacion) as cliente:
            barrera.wait(timeout=10)
            respuestas.append(_fallar(cliente).status_code)

    hilos = [threading.Thread(target=intentar) for _ in range(2)]
    try:
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)

        with Session(database_engine) as comprobacion:
            fila = comprobacion.execute(select(Administrator)).scalar_one()
            assert respuestas == [401, 401]
            assert fila.failed_login_attempts == 2, (
                "se perdio una actualizacion: el contador de intentos fallidos "
                "no esta protegido frente a peticiones simultaneas"
            )
    finally:
        with Session(database_engine) as limpieza:
            limpiar_autenticacion(limpieza)
            limpieza.commit()
