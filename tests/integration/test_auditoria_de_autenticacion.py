"""Auditoria de la autenticacion (matriz A de `Task/011`).

`Task/008` creo la tabla y sus guardas de inmutabilidad, y dejo escrito que **el
catalogo de acciones lo cierran `Task/011` y `Task/012`**. Aqui se cierra la parte
de autenticacion: cuatro acciones, ni una mas.

Requisito O-05 —toda accion administrativa deja rastro— y requisito S-08 —ese
rastro no contiene secretos—. La segunda mitad importa tanto como la primera: una
auditoria que guardara la contrasena intentada seria peor que no tener auditoria.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import AccionAuditada
from app.modules.audit.infrastructure.models import AuditEvent
from app.shared.configuration import Settings
from tests.integration.datos_de_autenticacion import CONTRASENA, CORREO, administrador

pytestmark = pytest.mark.integration

ACCESO = "/api/v1/admin/auth/login"
CIERRE = "/api/v1/admin/auth/logout"
UMBRAL = 5


@pytest.fixture
def cliente_con_direccion(
    database_settings: Settings, sesion_de_pruebas: Session
) -> Iterator[Callable[..., TestClient]]:
    """Fabrica clientes con la direccion de par TCP que pida la prueba.

    La cadena hasta la guarda *fail-closed* se mantiene: depende de
    `database_settings` y de `sesion_de_pruebas`, y ambas derivan del resolutor
    verificado.
    """
    from app.main import create_app
    from app.shared.database import get_session

    abiertos: list[TestClient] = []

    def _fabricar(direccion: str = "203.0.113.7") -> TestClient:
        aplicacion = create_app(
            settings=database_settings.model_copy(update={"auth_cookie_secure": False})
        )
        aplicacion.dependency_overrides[get_session] = lambda: sesion_de_pruebas
        cliente = TestClient(aplicacion, raise_server_exceptions=False, client=(direccion, 50000))
        abiertos.append(cliente)
        return cliente

    try:
        yield _fabricar
    finally:
        for cliente in abiertos:
            cliente.close()


def _eventos(sesion: Session) -> list[AuditEvent]:
    """Historial ordenado por instante.

    **Entre eventos de peticiones distintas el orden es firme; entre eventos de
    la misma peticion, no.** `occurred_at` lo pone `now()` de PostgreSQL, que
    devuelve el instante de **inicio de la transaccion**: los dos eventos que
    puede emitir un mismo intento —fallo y bloqueo— comparten marca. Por eso
    ninguna prueba afirma cual va antes: seria afirmar algo que el
    almacenamiento no garantiza, y acabaria fallando un dia sin motivo.
    """
    return list(sesion.execute(select(AuditEvent).order_by(AuditEvent.occurred_at)).scalars())


def _acceder(cliente: TestClient, *, correo: str = CORREO, contrasena: str = CONTRASENA) -> Any:
    return cliente.post(ACCESO, json={"email": correo, "password": contrasena})


# --- A-01 ------------------------------------------------------------------
def test_el_acceso_correcto_deja_su_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)

    _acceder(cliente_administrativo)

    eventos = _eventos(sesion_de_pruebas)
    assert [evento.action for evento in eventos] == [AccionAuditada.ACCESO_CORRECTO]
    assert eventos[0].actor_id == fila.id
    assert eventos[0].entity_type == "administrator"


# --- A-02 ------------------------------------------------------------------
def test_el_acceso_fallido_deja_su_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)

    _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    eventos = _eventos(sesion_de_pruebas)
    assert [evento.action for evento in eventos] == [AccionAuditada.ACCESO_FALLIDO]
    assert eventos[0].actor_id == fila.id


def test_un_fallo_con_correo_desconocido_se_audita_sin_actor(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`actor_id` admite nulo justamente por este caso.

    Un intento contra un correo que no existe tambien se audita —es la senal de
    que alguien esta probando—, y en ese momento no hay ningun administrador a
    quien atribuirselo.
    """
    administrador(sesion_de_pruebas)

    _acceder(cliente_administrativo, correo="nadie@example.invalid")

    eventos = _eventos(sesion_de_pruebas)
    assert [evento.action for evento in eventos] == [AccionAuditada.ACCESO_FALLIDO]
    assert eventos[0].actor_id is None


def test_el_correo_intentado_no_se_guarda_en_la_auditoria(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Se registra **que** hubo un intento fallido, no contra que direccion.

    Guardar el correo recibido convertiria la auditoria en un almacen de datos
    personales de terceros alimentado por cualquiera que envie peticiones
    (requisito O-09). Correlacionar intentos ya es posible por IP y por
    `request_id`, que es informacion minima y suficiente.
    """
    administrador(sesion_de_pruebas)

    _acceder(cliente_administrativo, correo="victima@example.invalid")

    evento = _eventos(sesion_de_pruebas)[0]
    assert "victima@example.invalid" not in str(evento.event_metadata)


# --- A-03 ------------------------------------------------------------------
def test_el_cierre_de_sesion_deja_su_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    fila = administrador(sesion_de_pruebas)
    _acceder(cliente_administrativo)

    cliente_administrativo.post(CIERRE)

    acciones = [evento.action for evento in _eventos(sesion_de_pruebas)]
    assert acciones == [AccionAuditada.ACCESO_CORRECTO, AccionAuditada.CIERRE_DE_SESION]
    assert _eventos(sesion_de_pruebas)[-1].actor_id == fila.id


# --- A-04 ------------------------------------------------------------------
def test_el_bloqueo_deja_su_propio_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El bloqueo es un hecho distinto del fallo que lo provoco.

    Sin evento propio, el operador tendria que deducirlo contando fallos, y el
    unico sitio donde el propietario puede enterarse de por que no entra es
    justamente este.
    """
    administrador(sesion_de_pruebas)

    for _ in range(UMBRAL):
        _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    acciones = [evento.action for evento in _eventos(sesion_de_pruebas)]
    assert acciones.count(AccionAuditada.CUENTA_BLOQUEADA) == 1
    assert acciones.count(AccionAuditada.ACCESO_FALLIDO) == UMBRAL


def test_el_bloqueo_no_se_reaudita_en_cada_intento_posterior(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Control del caso anterior: se audita la **transicion**, no el estado.

    Sin esto, cada intento durante el bloqueo anadiria un evento y el historial
    quedaria inservible justo cuando hace falta leerlo.
    """
    administrador(sesion_de_pruebas)

    for _ in range(UMBRAL + 4):
        _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    acciones = [evento.action for evento in _eventos(sesion_de_pruebas)]
    assert acciones.count(AccionAuditada.CUENTA_BLOQUEADA) == 1


# --- A-05 ------------------------------------------------------------------
def test_el_evento_lleva_el_identificador_de_la_peticion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Objetivo declarado en api-contracts.md seccion 9: rastrear extremo a extremo.

    El identificador del evento es **el mismo** que el que viaja en el cuerpo de
    error, asi que un incidente reportado por el propietario se localiza en la
    auditoria con el dato que el ya tiene delante.
    """
    administrador(sesion_de_pruebas)

    respuesta = _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    evento = _eventos(sesion_de_pruebas)[0]
    assert evento.request_id is not None
    assert evento.request_id == respuesta.json()["error"]["request_id"]


def test_dos_peticiones_producen_identificadores_distintos(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Control: un identificador constante no correlacionaria nada."""
    administrador(sesion_de_pruebas)

    _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")
    _acceder(cliente_administrativo, contrasena="tampoco-es")

    identificadores = {evento.request_id for evento in _eventos(sesion_de_pruebas)}
    assert len(identificadores) == 2


# --- A-06 ------------------------------------------------------------------
def test_el_evento_lleva_la_direccion_del_cliente(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """La direccion se registra tal cual la resuelve la politica de confianza.

    Se usa un cliente con una direccion real porque el `TestClient` por defecto
    se presenta como `testclient`, que no es una direccion IP.
    """
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion("203.0.113.7")

    cliente.post(ACCESO, json={"email": CORREO, "password": "no-es-la-contrasena"})

    assert _eventos(sesion_de_pruebas)[0].ip_address == "203.0.113.7"


def test_un_par_sin_direccion_reconocible_se_registra_como_desconocido(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Control *fail-closed* del caso anterior.

    Cuando lo que llega no es una direccion IP —y `testclient`, el anfitrion que
    usa el cliente de pruebas, no lo es— se registra `unknown` en lugar de
    guardar texto arbitrario en una columna de 45 caracteres. Es la misma regla
    que impide que una cabecera manipulada acabe en la base.
    """
    administrador(sesion_de_pruebas)

    _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    assert _eventos(sesion_de_pruebas)[0].ip_address == "unknown"


# --- A-07 ------------------------------------------------------------------
def test_ningun_evento_de_autenticacion_contiene_un_secreto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Requisito S-08, comprobado sobre **todas** las columnas de cada evento.

    Se recorre la fila entera y no solo `metadata`: si alguien colara un secreto
    en `action` o en `entity_type`, esta prueba lo veria igual.
    """
    fila = administrador(sesion_de_pruebas)
    _acceder(cliente_administrativo)
    credencial = cliente_administrativo.cookies["blog_admin_session"]
    cliente_administrativo.post(CIERRE)
    _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    prohibidos = (CONTRASENA, fila.password_hash, credencial, "no-es-la-contrasena")
    for evento in _eventos(sesion_de_pruebas):
        volcado = " ".join(
            str(getattr(evento, columna.name)) for columna in evento.__table__.columns
        )
        for secreto in prohibidos:
            assert secreto not in volcado, f"la auditoria filtro un secreto: {evento.action}"


def test_la_auditoria_no_guarda_la_huella_de_la_sesion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Ni siquiera la huella: identifica la sesion y no aporta nada al historial."""
    from app.modules.authentication.domain.sesion import huella_de_credencial

    administrador(sesion_de_pruebas)
    _acceder(cliente_administrativo)
    huella = huella_de_credencial(cliente_administrativo.cookies["blog_admin_session"])
    cliente_administrativo.post(CIERRE)

    for evento in _eventos(sesion_de_pruebas):
        assert huella not in str(evento.event_metadata)


# --- A-08 ------------------------------------------------------------------
def test_los_eventos_de_autenticacion_siguen_siendo_inmutables(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`Task/011` solo **crea** eventos: no debilita las guardas de `Task/008`."""
    from app.modules.audit.infrastructure.models import AuditEventIsImmutableError

    administrador(sesion_de_pruebas)
    _acceder(cliente_administrativo)
    evento = _eventos(sesion_de_pruebas)[0]

    evento.action = "otra-cosa"
    with pytest.raises(AuditEventIsImmutableError):
        sesion_de_pruebas.flush()


# --- Catalogo cerrado ------------------------------------------------------
def test_el_catalogo_de_acciones_de_autenticacion_tiene_cuatro_entradas() -> None:
    """Cuatro acciones, y las cuatro tienen un consumidor real.

    `Task/012` anadira las suyas; inventarlas aqui seria escribir historial que
    nadie produce.
    """
    assert {accion.value for accion in AccionAuditada} == {
        "authentication.login_succeeded",
        "authentication.login_failed",
        "authentication.logout",
        "authentication.account_locked",
    }


def test_un_rechazo_por_limite_de_tasa_no_genera_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """No esta en el catalogo, y es deliberado.

    Un limite superado es un hecho **operativo del endpoint**, no una accion
    administrativa: auditarlo llenaria el historial de ruido producido por
    cualquiera desde fuera. El contador ya deja constancia en su propia tabla y
    el log estructurado registra la peticion.
    """
    administrador(sesion_de_pruebas)
    for _ in range(11):
        _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")
    antes = len(_eventos(sesion_de_pruebas))

    respuesta = _acceder(cliente_administrativo, contrasena="no-es-la-contrasena")

    assert respuesta.status_code == 429
    assert len(_eventos(sesion_de_pruebas)) == antes
    assert all(evento.action in set(AccionAuditada) for evento in _eventos(sesion_de_pruebas))
