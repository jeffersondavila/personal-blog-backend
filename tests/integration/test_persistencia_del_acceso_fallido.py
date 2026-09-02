"""El estado defensivo de un intento fallido **sobrevive al `401`** (caso A-09).

Por que esta prueba existe y por que no usa el harness habitual
---------------------------------------------------------------

Un intento de acceso fallido **escribe**: incrementa el contador, puede activar
el bloqueo y —desde el *slice* de auditoria— deja un evento. Si ese fallo se
senalara lanzando una excepcion sin mas, la excepcion subiria por la dependencia
de sesion de FastAPI, `session_scope` haria `rollback`, y todo eso se perderia:
el contador volveria a cero en cada intento y el bloqueo **no llegaria a existir
nunca**. Es un defecto silencioso —la respuesta HTTP seria exactamente la misma—
y por eso hace falta una prueba que lo vea.

El resto de pruebas de integracion sustituyen `get_session` por la sesion
transaccional del harness, que **no** pasa por `session_scope`. Con esa
sustitucion, esta comprobacion pasaria hubiera `commit` o no: seria tautologica.
Asi que aqui se ejercita la **ruta real** —`session_scope`, con su `commit` y su
`rollback`— contra la base de pruebas, y se limpia lo escrito en un `finally`.

Sigue derivando del resolutor verificado del harness (`CERT-AUD-002`): la
configuracion y el motor vienen de `database_settings` y `database_engine`, que
solo se entregan tras comprobar que el destino es la base de pruebas.
"""

from __future__ import annotations

from collections.abc import Iterator

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


@pytest.fixture
def administrador_confirmado(
    database_engine: Engine, esquema_migrado: None, configured_process: None
) -> Iterator[Session]:
    """Administrador **realmente escrito** en la base, y su limpieza garantizada.

    No se puede usar la sesion transaccional del harness: la aplicacion abre su
    propia sesion y no veria una fila que sigue sin confirmarse.

    Se limpia **antes y despues**. Despues, porque lo escrito aqui sobrevive al
    final de la prueba y `administrators.is_singleton` es unico: una fila
    olvidada impide que cualquier prueba posterior cree su administrador. Antes,
    porque una ejecucion anterior interrumpida —un `SIGKILL`, un tiempo de
    espera— puede haber dejado la suya, y entonces el fallo aparecería aqui sin
    tener nada que ver con lo que esta prueba comprueba.

    El orden del borrado lo decide `limpiar_autenticacion`, y no es cosmetico:
    `audit_events.actor_id` usa `ON DELETE RESTRICT`.
    """
    with Session(database_engine) as sesion:
        limpiar_autenticacion(sesion)
        administrador(sesion)
        sesion.commit()
        try:
            yield sesion
        finally:
            sesion.rollback()
            limpiar_autenticacion(sesion)
            sesion.commit()


@pytest.fixture
def cliente_sin_sustituir_la_sesion(database_settings: Settings) -> Iterator[TestClient]:
    """Aplicacion con su dependencia de sesion **real**.

    Es lo que hace que la prueba observe `session_scope` de verdad: su `commit`
    al salir y su `rollback` cuando algo lanza.
    """
    from app.main import create_app

    with TestClient(create_app(settings=database_settings)) as cliente:
        yield cliente


def test_un_intento_fallido_deja_el_contador_escrito_pese_al_401(
    cliente_sin_sustituir_la_sesion: TestClient, administrador_confirmado: Session
) -> None:
    respuesta = cliente_sin_sustituir_la_sesion.post(
        ACCESO, json={"email": CORREO, "password": "no-es-la-contrasena"}
    )

    assert respuesta.status_code == 401

    administrador_confirmado.expire_all()
    fila = administrador_confirmado.execute(select(Administrator)).scalar_one()
    assert fila.failed_login_attempts == 1, (
        "el contador se perdio: el camino de fallo esta revirtiendo su propia escritura"
    )


def test_varios_intentos_fallidos_acumulan_en_la_base(
    cliente_sin_sustituir_la_sesion: TestClient, administrador_confirmado: Session
) -> None:
    """Control del caso anterior: si cada intento revirtiera, el contador seria 1.

    Que llegue a 3 demuestra que **cada** intento persistio el suyo, no solo el
    ultimo.
    """
    for _ in range(3):
        cliente_sin_sustituir_la_sesion.post(
            ACCESO, json={"email": CORREO, "password": "no-es-la-contrasena"}
        )

    administrador_confirmado.expire_all()
    fila = administrador_confirmado.execute(select(Administrator)).scalar_one()
    assert fila.failed_login_attempts == 3


def test_un_acceso_correcto_por_la_ruta_real_persiste_su_sesion(
    cliente_sin_sustituir_la_sesion: TestClient, administrador_confirmado: Session
) -> None:
    """Control positivo: el camino de exito tambien escribe de verdad.

    Sin el, una implementacion que no confirmara **nada** pasaria las dos pruebas
    de arriba si ademas dejara el contador intacto por otro motivo.
    """
    respuesta = cliente_sin_sustituir_la_sesion.post(
        ACCESO, json={"email": CORREO, "password": CONTRASENA}
    )

    assert respuesta.status_code == 200
    administrador_confirmado.expire_all()
    assert administrador_confirmado.execute(select(AdministratorSession)).scalar_one() is not None
