"""Trazabilidad extremo a extremo de una accion auditada (`Task/017`, O-02 y O-05).

Lo que se demuestra aqui es la cadena completa:

```
peticion HTTP
   -> X-Request-ID de la respuesta
   -> request_id de todos sus logs
   -> AuditEvent.request_id en PostgreSQL
```

`Task/011` y `Task/012` ya escribian `AuditEvent.request_id`, y la medicion del
*baseline* lo confirmo. Lo que faltaba era que ese identificador **saliera**: en
una escritura administrativa correcta se generaba, se guardaba en la fila y no
llegaba ni al cliente ni a ningun log, asi que el operador veia una fila de
auditoria con un identificador imposible de encontrar en ningun otro sitio.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditEvent
from app.shared.logging import JsonLogFormatter
from app.shared.logging.contexto import NOMBRE_DE_LA_CABECERA_DE_CORRELACION
from tests.integration.administracion import ADMIN, administrador_con_sesion
from tests.integration.datos_de_autenticacion import CONTRASENA, CORREO

pytestmark = pytest.mark.integration

CABECERA = NOMBRE_DE_LA_CABECERA_DE_CORRELACION


@contextmanager
def _log_capturado() -> Iterator[list[str]]:
    """Lineas JSON emitidas durante el bloque, tal y como saldrian por `stdout`.

    Se instala un manejador propio en el logger raiz en lugar de leer `capsys`
    porque la aplicacion de estas pruebas se construye en el `setup` de una
    fixture: `configure_logging` ata su `StreamHandler` al `sys.stdout` de esa
    fase, y `readouterr()` en el cuerpo del test no veria nada. Formateando con
    el `JsonLogFormatter` real se comprueba **la misma linea** que acabaria en
    Docker.
    """
    lineas: list[str] = []
    formateador = JsonLogFormatter()

    class _Recolector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lineas.append(formateador.format(record))

    recolector = _Recolector(level=logging.DEBUG)
    raiz = logging.getLogger()
    nivel_previo = raiz.level
    raiz.addHandler(recolector)
    raiz.setLevel(logging.DEBUG)
    try:
        yield lineas
    finally:
        raiz.removeHandler(recolector)
        raiz.setLevel(nivel_previo)


def _evento_de(sesion: Session, accion: str) -> AuditEvent:
    """El evento de una accion concreta.

    No se usa "el ultimo por fecha": `occurred_at` se rellena con `now()`, que en
    PostgreSQL es la marca de **inicio de la transaccion**, asi que el evento del
    login previo y el de la escritura pueden compartir instante al microsegundo y
    el desempate canonico —`id` ascendente, pensado para paginar— devolveria el
    equivocado. Filtrar por accion es determinista.
    """
    sesion.expire_all()
    eventos = list(sesion.scalars(select(AuditEvent).where(AuditEvent.action == accion)))
    assert len(eventos) == 1, f"se esperaba un unico evento '{accion}', hay {len(eventos)}"
    return eventos[0]


#: Acciones del catalogo cerrado que estas pruebas ejercitan.
CREAR_ETIQUETA = "tag.created"
ACCESO_FALLIDO = "authentication.login_failed"
ACCESO_CORRECTO = "authentication.login_succeeded"


def test_una_escritura_administrativa_correcta_guarda_el_id_que_devuelve(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """**El camino feliz**, que es justo el que no se podia rastrear.

    Antes de `Task/017` la respuesta `201` no llevaba ninguna cabecera de
    correlacion, asi que el valor guardado en `audit_events` era inalcanzable.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(f"{ADMIN}/tags", json={"name": "Observabilidad"})

    assert respuesta.status_code == 201, respuesta.text
    devuelto = respuesta.headers[CABECERA]
    assert _evento_de(sesion_de_pruebas, CREAR_ETIQUETA).request_id == devuelto


def test_el_id_entrante_valido_llega_hasta_la_auditoria(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Un operador puede fijar el identificador y luego buscarlo por ese valor."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    propio = "traza-de-operador-017"

    respuesta = cliente_administrativo.post(
        f"{ADMIN}/tags", json={"name": "Trazabilidad"}, headers={CABECERA: propio}
    )

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.headers[CABECERA] == propio
    assert _evento_de(sesion_de_pruebas, CREAR_ETIQUETA).request_id == propio


def test_un_id_entrante_invalido_no_llega_a_la_auditoria(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Lo que se guarda es siempre un identificador que respeta el contrato."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(
        f"{ADMIN}/tags", json={"name": "Saneado"}, headers={CABECERA: "no valido " * 20}
    )

    assert respuesta.status_code == 201, respuesta.text
    guardado = _evento_de(sesion_de_pruebas, CREAR_ETIQUETA).request_id
    assert guardado == respuesta.headers[CABECERA]
    assert guardado is not None
    assert len(guardado) <= 64


def test_un_id_de_64_caracteres_cabe_en_la_columna(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El limite del contrato es exactamente el de `VARCHAR(64)`: se ejerce."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    al_limite = "c" * 64

    respuesta = cliente_administrativo.post(
        f"{ADMIN}/tags", json={"name": "Al limite"}, headers={CABECERA: al_limite}
    )

    assert respuesta.status_code == 201, respuesta.text
    assert _evento_de(sesion_de_pruebas, CREAR_ETIQUETA).request_id == al_limite


def test_un_acceso_fallido_comparte_el_id_entre_cuerpo_de_error_y_auditoria(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Es el escenario que se midio a mano durante la definicion, ahora fijado."""
    respuesta = cliente_administrativo.post(
        f"{ADMIN}/auth/login",
        json={"email": "no-existe-task017@example.invalid", "password": "irrelevante"},
    )

    assert respuesta.status_code == 401
    de_la_cabecera = respuesta.headers[CABECERA]
    assert respuesta.json()["error"]["request_id"] == de_la_cabecera
    assert _evento_de(sesion_de_pruebas, ACCESO_FALLIDO).request_id == de_la_cabecera


def test_el_id_de_la_auditoria_aparece_en_los_logs_de_esa_peticion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El eslabon que cierra la cadena: la fila se puede buscar en Portainer."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    with _log_capturado() as lineas:
        respuesta = cliente_administrativo.post(f"{ADMIN}/tags", json={"name": "Correlacionada"})

    esperado = respuesta.headers[CABECERA]
    assert _evento_de(sesion_de_pruebas, CREAR_ETIQUETA).request_id == esperado
    assert any(esperado in linea for linea in lineas), (
        "el identificador de la fila no aparece en ninguna linea de log"
    )


def test_dos_escrituras_dejan_dos_eventos_con_identificadores_distintos(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    primera = cliente_administrativo.post(f"{ADMIN}/tags", json={"name": "Primera"})
    segunda = cliente_administrativo.post(f"{ADMIN}/tags", json={"name": "Segunda"})

    identificadores = {primera.headers[CABECERA], segunda.headers[CABECERA]}
    assert len(identificadores) == 2, "las dos peticiones compartieron identificador"

    sesion_de_pruebas.expire_all()
    guardados = {
        evento.request_id
        for evento in sesion_de_pruebas.scalars(
            select(AuditEvent).where(AuditEvent.action == CREAR_ETIQUETA)
        )
    }
    assert guardados == identificadores


# --- Lo que `Task/017` NO cambia -----------------------------------------


def test_una_lectura_administrativa_sigue_sin_auditarse(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """CONTENT_MODEL.md 3.9: *"las lecturas no se auditan"*. Se cuenta antes y despues."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    antes = sesion_de_pruebas.query(AuditEvent).count()

    assert cliente_administrativo.get(f"{ADMIN}/tags").status_code == 200
    assert cliente_administrativo.get(f"{ADMIN}/audit-events").status_code == 200

    sesion_de_pruebas.expire_all()
    assert sesion_de_pruebas.query(AuditEvent).count() == antes


def test_el_dto_publico_de_auditoria_sigue_con_exactamente_cinco_campos(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`Task/017` **no** expone `request_id` en el DTO: no hay consumidor (D-012)."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    cliente_administrativo.post(f"{ADMIN}/tags", json={"name": "Sin exponer"})

    elementos = cliente_administrativo.get(f"{ADMIN}/audit-events").json()["items"]

    assert elementos
    for elemento in elementos:
        assert set(elemento) == {"id", "occurred_at", "action", "entity_type", "entity_id"}
        assert "request_id" not in elemento


def test_el_historial_no_expone_el_identificador_ni_indirectamente(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    respuesta = cliente_administrativo.post(f"{ADMIN}/tags", json={"name": "Opaca"})
    identificador = respuesta.headers[CABECERA]

    historial = cliente_administrativo.get(f"{ADMIN}/audit-events").text

    assert identificador not in historial


def test_la_contrasena_de_un_acceso_fallido_no_aparece_en_el_log(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A-01 y O-08, con el senuelo buscado en la salida completa."""
    capsys.readouterr()
    senuelo = "TASK017_SECRET_PASSWORD_EN_LOGIN"

    cliente_administrativo.post(
        f"{ADMIN}/auth/login",
        json={"email": "no-existe-task017@example.invalid", "password": senuelo},
    )

    assert senuelo not in capsys.readouterr().out


def test_el_correo_intentado_no_aparece_en_el_log(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A-13: el correo intentado es dato personal de un tercero."""
    capsys.readouterr()
    correo = "TASK017-victima@example.invalid"

    cliente_administrativo.post(
        f"{ADMIN}/auth/login", json={"email": correo, "password": CONTRASENA}
    )

    assert correo not in capsys.readouterr().out


def test_la_cookie_de_sesion_no_aparece_en_el_log(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    capsys.readouterr()

    cliente_administrativo.get(f"{ADMIN}/auth/me")
    salida = capsys.readouterr().out

    for galleta in cliente_administrativo.cookies.values():
        assert galleta not in salida


def test_el_evento_de_una_escritura_admin_no_lleva_el_cuerpo_enviado(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    marcador = "TASK017_MARCADOR_DE_CUERPO"

    with _log_capturado() as lineas:
        cliente_administrativo.post(f"{ADMIN}/tags", json={"name": marcador})

    eventos = [json.loads(linea) for linea in lineas if "Peticion completada" in linea]
    assert eventos, "no se emitio el evento de peticion"
    for evento in eventos:
        assert marcador not in json.dumps(evento)


def test_ninguna_linea_de_una_escritura_admin_lleva_el_cuerpo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El senuelo se busca en **toda** la salida, no solo en el evento."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    marcador = "TASK017_MARCADOR_EN_CUALQUIER_LINEA"

    with _log_capturado() as lineas:
        cliente_administrativo.post(f"{ADMIN}/tags", json={"name": marcador})

    assert marcador not in "".join(lineas)


def test_el_login_correcto_tambien_correlaciona(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    from tests.integration.datos_de_autenticacion import administrador

    administrador(sesion_de_pruebas)

    respuesta = cliente_administrativo.post(
        f"{ADMIN}/auth/login", json={"email": CORREO, "password": CONTRASENA}
    )

    assert respuesta.status_code == 200
    assert _evento_de(sesion_de_pruebas, ACCESO_CORRECTO).request_id == respuesta.headers[CABECERA]


def test_la_auditoria_sigue_siendo_inmutable(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`Task/017` no relaja ninguna guarda de `Task/008`."""
    from app.modules.audit.infrastructure.models import AuditEventIsImmutableError

    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    cliente_administrativo.post(f"{ADMIN}/tags", json={"name": "Inmutable"})
    evento = _evento_de(sesion_de_pruebas, CREAR_ETIQUETA)

    with pytest.raises(AuditEventIsImmutableError):
        evento.request_id = "modificado-a-mano"
        sesion_de_pruebas.flush()
    sesion_de_pruebas.rollback()


def _sin_usar(_: Any) -> None:  # pragma: no cover - utilidad de tipado
    return None
