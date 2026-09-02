"""Limite de tasa del inicio de sesion (matriz R de `Task/011`, decision D-011-I).

Es el **otro** alcance de la proteccion, distinto del bloqueo de cuenta: este
protege el endpoint frente a rafagas desde un origen, y particiona por direccion
IP. Ninguno sustituye al otro.

Va contra PostgreSQL real porque el contador **vive en PostgreSQL**: es
justamente lo que lo hace compartido entre instancias, que es la restriccion
escrita en D-09.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.authentication.infrastructure.models import LoginRateLimit
from app.shared.configuration import Settings
from tests.integration.datos_de_autenticacion import (
    CONTRASENA,
    CORREO,
    administrador,
    limpiar_autenticacion,
)

pytestmark = pytest.mark.integration

ACCESO = "/api/v1/admin/auth/login"
LIMITE = 10


@pytest.fixture
def cliente_con_direccion(
    database_settings: Settings, sesion_de_pruebas: Session
) -> Iterator[Callable[..., TestClient]]:
    """Fabrica clientes con la direccion de par TCP que pida la prueba.

    El limite particiona por direccion, asi que comprobar la particion exige
    poder hablar desde dos direcciones distintas. La sesion sigue siendo la
    transaccional del harness —se revierte al terminar— y la cadena hasta el
    resolutor verificado se mantiene: esta fixture depende de `database_settings`
    y de `sesion_de_pruebas`, y ambas derivan de el.
    """
    from app.main import create_app
    from app.shared.database import get_session

    abiertos: list[TestClient] = []

    def _fabricar(direccion: str = "203.0.113.7", **configuracion: Any) -> TestClient:
        ajustes = (
            database_settings.model_copy(update=configuracion)
            if configuracion
            else database_settings
        )
        aplicacion = create_app(settings=ajustes)
        aplicacion.dependency_overrides[get_session] = lambda: sesion_de_pruebas
        cliente = TestClient(aplicacion, raise_server_exceptions=False, client=(direccion, 50000))
        abiertos.append(cliente)
        return cliente

    try:
        yield _fabricar
    finally:
        for cliente in abiertos:
            cliente.close()


def _fallar(cliente: TestClient, **cabeceras: str) -> Any:
    return cliente.post(
        ACCESO,
        json={"email": CORREO, "password": "no-es-la-contrasena"},
        headers=cabeceras or None,
    )


# --- R-01 y R-02 -----------------------------------------------------------
def test_los_intentos_por_debajo_del_limite_no_se_rechazan_por_tasa(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion()

    codigos = [_fallar(cliente).status_code for _ in range(LIMITE - 1)]

    assert codigos == [401] * (LIMITE - 1)


def test_el_intento_que_alcanza_el_limite_todavia_se_atiende(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """El limite es *cuantos se admiten*, no *a partir de cual se corta*."""
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion()

    codigos = [_fallar(cliente).status_code for _ in range(LIMITE)]

    assert codigos[-1] == 401


# --- R-03, R-04 y R-05 -----------------------------------------------------
def test_el_intento_por_encima_del_limite_se_rechaza_con_429(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion()
    for _ in range(LIMITE):
        _fallar(cliente)

    respuesta = _fallar(cliente)

    assert respuesta.status_code == 429
    assert respuesta.json()["error"]["code"] == "too_many_requests"


def test_el_rechazo_por_tasa_usa_la_envoltura_de_error_del_proyecto(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion()
    for _ in range(LIMITE + 1):
        respuesta = _fallar(cliente)

    cuerpo = respuesta.json()
    assert set(cuerpo) == {"error"}
    assert set(cuerpo["error"]) == {"code", "message", "details", "request_id"}


def test_el_rechazo_por_tasa_declara_cuando_reintentar(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Un `429` sin `Retry-After` obliga al cliente legitimo a adivinar."""
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion()
    for _ in range(LIMITE + 1):
        respuesta = _fallar(cliente)

    reintentar = int(respuesta.headers["retry-after"])
    assert 0 < reintentar <= 300


def test_el_limite_no_entrega_ninguna_sesion(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Control: ni siquiera con las credenciales correctas se pasa del limite."""
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion()
    for _ in range(LIMITE):
        _fallar(cliente)

    respuesta = cliente.post(ACCESO, json={"email": CORREO, "password": CONTRASENA})

    assert respuesta.status_code == 429
    assert "set-cookie" not in {clave.lower() for clave in respuesta.headers}


# --- R-06 ------------------------------------------------------------------
def test_el_cubo_de_una_direccion_no_afecta_a_otra(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Si el contador fuera global, agotarlo dejaria al propietario sin acceso
    desde cualquier sitio — el atacante conseguiria una negacion de servicio.

    **El atacante usa un correo que no existe, y eso no es un detalle.** La
    primera version de esta prueba le hacia gastar sus intentos contra el correo
    real, y fallaba: los fallos activaban el **bloqueo de cuenta**, que es la
    otra proteccion y no depende del origen, asi que el propietario tampoco
    entraba. La prueba estaba mezclando los dos alcances y no medía lo que decia
    medir. Aislarlos es lo correcto: aqui se comprueba **solo** la particion del
    limite de tasa; el bloqueo tiene sus propias pruebas.
    """
    administrador(sesion_de_pruebas)
    atacante = cliente_con_direccion("198.51.100.5")
    propietario = cliente_con_direccion("203.0.113.7")
    for _ in range(LIMITE + 1):
        atacante.post(ACCESO, json={"email": "nadie@example.invalid", "password": "da-igual"})

    respuesta = propietario.post(ACCESO, json={"email": CORREO, "password": CONTRASENA})

    assert respuesta.status_code == 200


def test_cada_direccion_tiene_su_propia_fila(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)
    _fallar(cliente_con_direccion("198.51.100.5"))
    _fallar(cliente_con_direccion("203.0.113.7"))

    claves = set(sesion_de_pruebas.execute(select(LoginRateLimit.client_key)).scalars())

    assert claves == {"198.51.100.5", "203.0.113.7"}


# --- R-07 ------------------------------------------------------------------
def test_una_cabecera_reenviada_falsificada_no_evade_el_limite(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Es el caso que convierte el limite en un adorno si se hace mal.

    Sin proxies de confianza declarados —el valor por defecto—, enviar una
    `X-Forwarded-For` distinta en cada intento **no** crea cubos nuevos: todos
    caen en la direccion real del par TCP.
    """
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion()

    for numero in range(LIMITE + 1):
        respuesta = _fallar(cliente, **{"X-Forwarded-For": f"198.51.100.{numero}"})

    assert respuesta.status_code == 429
    claves = set(sesion_de_pruebas.execute(select(LoginRateLimit.client_key)).scalars())
    assert claves == {"203.0.113.7"}


def test_con_un_proxy_declarado_si_se_atiende_la_cabecera(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Control positivo del caso anterior.

    Sin el, una implementacion que ignorara `X-Forwarded-For` **siempre** pasaria
    la prueba de arriba sin haber implementado ninguna politica de confianza.
    """
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion(trusted_proxy_hop_count=1)

    _fallar(cliente, **{"X-Forwarded-For": "198.51.100.42"})

    claves = set(sesion_de_pruebas.execute(select(LoginRateLimit.client_key)).scalars())
    assert claves == {"198.51.100.42"}


# --- R-08 ------------------------------------------------------------------
def test_al_expirar_la_ventana_el_contador_se_reinicia(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """La ventana es fija: cuando queda atras, empieza otra desde cero.

    Se envejece la fila en la base en lugar de esperar cinco minutos reales: lo
    que se comprueba es la regla, no la paciencia de la suite.
    """
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion()
    for _ in range(LIMITE + 1):
        _fallar(cliente)
    assert _fallar(cliente).status_code == 429

    fila = sesion_de_pruebas.execute(select(LoginRateLimit)).scalar_one()
    fila.window_started_at = datetime.now(UTC) - timedelta(seconds=301)
    sesion_de_pruebas.flush()

    assert _fallar(cliente).status_code == 401


def test_el_contador_arranca_de_nuevo_tras_la_ventana(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    administrador(sesion_de_pruebas)
    cliente = cliente_con_direccion()
    for _ in range(3):
        _fallar(cliente)

    fila = sesion_de_pruebas.execute(select(LoginRateLimit)).scalar_one()
    fila.window_started_at = datetime.now(UTC) - timedelta(seconds=301)
    sesion_de_pruebas.flush()
    _fallar(cliente)
    sesion_de_pruebas.expire_all()

    assert sesion_de_pruebas.execute(select(LoginRateLimit)).scalar_one().attempts == 1


# --- La tabla no guarda identidades ----------------------------------------
def test_el_contador_no_registra_a_quien_intento_entrar(
    cliente_con_direccion: Callable[..., TestClient], sesion_de_pruebas: Session
) -> None:
    """Quien intento entrar es asunto de la auditoria (requisito O-09)."""
    limpiar_autenticacion(sesion_de_pruebas)
    administrador(sesion_de_pruebas)
    _fallar(cliente_con_direccion())

    fila = sesion_de_pruebas.execute(select(LoginRateLimit)).scalar_one()
    valores = " ".join(str(getattr(fila, columna.name)) for columna in fila.__table__.columns)
    assert CORREO not in valores
    assert CONTRASENA not in valores
