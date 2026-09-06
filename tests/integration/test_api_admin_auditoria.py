"""El historial administrativo contra PostgreSQL real (`Task/012.1`).

`MVP_SCOPE.md` seccion 3.3 fija como alcance minimo del dashboard *"conteo de
contenido por tipo y estado, ultimos elementos modificados y **ultimos eventos de
auditoria**"*. Estas pruebas cubren la tercera parte, que es la que faltaba.

Se ejecutan contra PostgreSQL real y **no** simulan el orden en Python: el
`ORDER BY` lo resuelve el motor, que es lo unico que demuestra que la consulta
esta bien escrita. Ordenar una lista en la prueba probaria la prueba.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import (
    ENTIDAD_ADMINISTRADOR,
    ENTIDAD_ARTICULO,
    AccionAuditada,
)
from app.modules.audit.infrastructure.models import AuditEvent
from app.modules.posts.domain import PostStatus
from tests.integration.administracion import (
    ADMIN,
    administrador_con_sesion,
    administrador_con_sesion_sin_auditar,
)
from tests.integration.datos import articulo

pytestmark = pytest.mark.integration

HISTORIAL = f"{ADMIN}/audit-events"

#: Instante fijo del que cuelgan los eventos fabricados. Se usa un valor
#: explicito en lugar de `now()` para que el orden esperado no dependa de la
#: velocidad de la maquina.
BASE = datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC)


def _evento(
    sesion: Session,
    *,
    occurred_at: datetime,
    action: str = AccionAuditada.CONTENIDO_PUBLICADO,
    entity_type: str = ENTIDAD_ARTICULO,
    entity_id: uuid.UUID | None = None,
    ip_address: str | None = "203.0.113.7",
    request_id: str | None = "req-de-prueba",
    event_metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Escribe un evento con instante controlado.

    `ip_address`, `request_id` y `event_metadata` se rellenan **a proposito**:
    las pruebas de privacidad solo valen si el dato existe en la fila y aun asi
    no sale en la respuesta.
    """
    fila = AuditEvent(
        occurred_at=occurred_at,
        action=str(action),
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        request_id=request_id,
        event_metadata=event_metadata if event_metadata is not None else {"slug": "docker"},
    )
    sesion.add(fila)
    sesion.flush()
    return fila


def _contar(sesion: Session) -> int:
    return sesion.execute(select(func.count()).select_from(AuditEvent)).scalar_one()


def _ids(cuerpo: dict[str, Any]) -> list[str]:
    return [elemento["id"] for elemento in cuerpo["items"]]


def _elemento_de(cliente: TestClient, fila: AuditEvent) -> dict[str, Any]:
    """Busca un evento concreto en el historial por su identificador.

    No se usa `items[0]`: abrir sesion **tambien** audita, y ese evento lleva la
    hora real del reloj, asi que encabeza el historial. Buscar por identificador
    hace la prueba independiente del instante en que se ejecute.
    """
    cuerpo: dict[str, Any] = cliente.get(HISTORIAL, params={"page_size": 50}).json()
    coincidencias: list[dict[str, Any]] = [
        elemento for elemento in cuerpo["items"] if elemento["id"] == str(fila.id)
    ]
    assert coincidencias, f"el evento {fila.id} no aparece en el historial"
    return coincidencias[0]


# --- Autenticacion ---------------------------------------------------------
def test_sin_sesion_el_historial_no_se_lee(cliente_administrativo: TestClient) -> None:
    """A-01: la proteccion es la de `Task/011`, heredada del router comun."""
    respuesta = cliente_administrativo.get(HISTORIAL)

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "unauthenticated"


def test_con_sesion_valida_el_historial_responde(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """A-03."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert cliente_administrativo.get(HISTORIAL).status_code == 200


# --- Coleccion -------------------------------------------------------------
def test_un_historial_vacio_es_una_pagina_vacia(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-01: `total = 0` produce `pages = 0`, no una pagina vacia inventada.

    Es el unico caso que **no** puede prepararse iniciando sesion: el acceso
    escribe `authentication.login_succeeded` —y debe hacerlo (USER_FLOWS.md
    B.1)—, asi que tras un login el historial jamas tiene cero filas. La sesion
    se construye por el harness con las mismas funciones de dominio que usa el
    codigo real (ver `administrador_con_sesion_sin_auditar`), de modo que no se
    borra ningun evento ni se relaja ninguna invariante: el evento no llega a
    existir.

    El `assert` previo sobre la tabla real evita la tautologia: sin el, un
    `total` de cero podria venir de un filtro accidental en lugar de de una
    coleccion realmente vacia.

    No lo cubre `test_una_pagina_fuera_de_rango_es_una_pagina_vacia`: alli
    `items` tambien viene vacio, pero con `total > 0` y `pages > 0`.
    """
    administrador_con_sesion_sin_auditar(cliente_administrativo, sesion_de_pruebas)

    assert _contar(sesion_de_pruebas) == 0

    respuesta = cliente_administrativo.get(HISTORIAL)
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo["items"] == []
    assert cuerpo["page"] == 1
    assert cuerpo["page_size"] == 12
    assert cuerpo["total"] == 0
    assert cuerpo["pages"] == 0


def test_la_envoltura_declara_el_total_real(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """La envoltura no inventa nada cuando si hay filas.

    Complementa al caso vacio por el otro extremo: aqui el acceso ya ha escrito
    su evento, y `total` debe coincidir con lo que hay en la tabla.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    cuerpo = cliente_administrativo.get(HISTORIAL).json()

    assert cuerpo["total"] == _contar(sesion_de_pruebas)
    assert cuerpo["pages"] == 1
    assert len(cuerpo["items"]) == cuerpo["total"]


def test_un_evento_se_devuelve_entero(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-02."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    identificador = uuid.uuid4()
    fila = _evento(sesion_de_pruebas, occurred_at=BASE, entity_id=identificador)

    elemento = _elemento_de(cliente_administrativo, fila)

    assert elemento["action"] == AccionAuditada.CONTENIDO_PUBLICADO
    assert elemento["entity_type"] == ENTIDAD_ARTICULO
    assert elemento["entity_id"] == str(identificador)
    assert elemento["occurred_at"].startswith("2026-09-05T12:00:00")


# --- Orden -----------------------------------------------------------------
def test_los_eventos_salen_del_mas_reciente_al_mas_antiguo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-03: `occurred_at` descendente, resuelto por el motor."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    for minutos in (0, 10, 20, 30, 40):
        _evento(sesion_de_pruebas, occurred_at=BASE + timedelta(minutes=minutos))

    cuerpo = cliente_administrativo.get(HISTORIAL).json()
    fechas = [elemento["occurred_at"] for elemento in cuerpo["items"]]

    assert fechas == sorted(fechas, reverse=True)


def test_los_eventos_del_mismo_instante_desempatan_por_identificador(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-04: `id` **ascendente**, la convencion de D-009-F, D-012-L y medios.

    Tres eventos con el **mismo** `occurred_at`: sin desempate el orden lo
    decidiria el plan de ejecucion, y la paginacion dejaria de ser estable.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    empatados = [_evento(sesion_de_pruebas, occurred_at=BASE) for _ in range(3)]
    esperados = [str(fila.id) for fila in sorted(empatados, key=lambda fila: fila.id)]

    devueltos = [
        elemento["id"]
        for elemento in cliente_administrativo.get(HISTORIAL).json()["items"]
        if elemento["id"] in set(esperados)
    ]

    assert devueltos == esperados


def test_el_orden_es_repetible(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-04 (continuacion): dos lecturas identicas devuelven el mismo orden."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    for _ in range(5):
        _evento(sesion_de_pruebas, occurred_at=BASE)

    primera = _ids(cliente_administrativo.get(HISTORIAL).json())
    segunda = _ids(cliente_administrativo.get(HISTORIAL).json())

    assert primera == segunda


# --- Estabilidad de la paginacion -----------------------------------------
def test_la_paginacion_no_repite_ni_omite_con_eventos_empatados(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-05: es el defecto concreto que el desempate existe para evitar."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    for _ in range(25):
        _evento(sesion_de_pruebas, occurred_at=BASE)

    primera = _ids(cliente_administrativo.get(HISTORIAL, params={"page": 1}).json())
    segunda = _ids(cliente_administrativo.get(HISTORIAL, params={"page": 2}).json())

    assert len(primera) == 12
    assert set(primera).isdisjoint(segunda)
    assert len(set(primera) | set(segunda)) == len(primera) + len(segunda)


# --- Paginacion ------------------------------------------------------------
def test_el_tamano_por_defecto_es_doce(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-06."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    for minutos in range(20):
        _evento(sesion_de_pruebas, occurred_at=BASE + timedelta(minutes=minutos))

    cuerpo = cliente_administrativo.get(HISTORIAL).json()

    assert cuerpo["page_size"] == 12
    assert len(cuerpo["items"]) == 12


def test_un_tamano_por_encima_del_maximo_se_recorta(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-07: `api-contracts.md` seccion 5 — se recorta, **no es un error**."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.get(HISTORIAL, params={"page_size": 500})

    assert respuesta.status_code == 200
    assert respuesta.json()["page_size"] == 50


@pytest.mark.parametrize(
    "parametros",
    [{"page_size": 0}, {"page": 0}, {"page": "abc"}, {"page_size": "-1"}],
    ids=["page_size=0", "page=0", "page=abc", "page_size=-1"],
)
def test_una_paginacion_invalida_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, parametros: dict[str, Any]
) -> None:
    """D-08 y D-09."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert cliente_administrativo.get(HISTORIAL, params=parametros).status_code == 422


def test_una_pagina_fuera_de_rango_es_una_pagina_vacia(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-10: `200` con `items` vacio, nunca un error."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    _evento(sesion_de_pruebas, occurred_at=BASE)

    respuesta = cliente_administrativo.get(HISTORIAL, params={"page": 99})

    assert respuesta.status_code == 200
    assert respuesta.json()["items"] == []


def test_el_total_y_el_numero_de_paginas_son_coherentes(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-11: `pages` se deriva de `total` y del tamano aplicado."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    while _contar(sesion_de_pruebas) < 13:
        _evento(sesion_de_pruebas, occurred_at=BASE)

    cuerpo = cliente_administrativo.get(HISTORIAL).json()

    assert cuerpo["total"] == _contar(sesion_de_pruebas)
    assert cuerpo["pages"] == -(-cuerpo["total"] // 12)


# --- Nulabilidad -----------------------------------------------------------
def test_un_evento_de_sesion_no_tiene_elemento_afectado(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-12: `entity_id` nulo se serializa como `null`, sin fallar."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    fila = _evento(
        sesion_de_pruebas,
        occurred_at=BASE + timedelta(hours=1),
        action=AccionAuditada.CIERRE_DE_SESION,
        entity_type=ENTIDAD_ADMINISTRADOR,
        entity_id=None,
    )

    elemento = _elemento_de(cliente_administrativo, fila)

    assert elemento["action"] == AccionAuditada.CIERRE_DE_SESION
    assert elemento["entity_id"] is None


# --- Parametros desconocidos ----------------------------------------------
@pytest.mark.parametrize("parametro", ["foo", "action", "entity_type", "actor_id", "status"])
def test_un_parametro_desconocido_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, parametro: str
) -> None:
    """D-13: decision **D-009-C**, heredada del router administrativo comun.

    Incluye los filtros que **no** existen: pedirlos no los ignora, los rechaza.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert cliente_administrativo.get(HISTORIAL, params={parametro: "x"}).status_code == 422


# --- Evento real, no fabricado --------------------------------------------
def test_un_evento_escrito_por_un_caso_de_uso_real_aparece_en_el_historial(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """D-14: el historial refleja lo que hace la aplicacion, no solo filas puestas a mano.

    Se publica un articulo con el endpoint administrativo real y se comprueba que
    su evento `content.published` aparece con los datos correctos.

    **No se afirma que encabece el historial**, y la razon es exactamente la que
    justifica el desempate de `queries.py`: `occurred_at` tiene
    `server_default=func.now()`, que en PostgreSQL es la marca de **inicio de la
    transaccion**. El acceso y la publicacion ocurren dentro de la misma
    transaccion de la prueba, asi que comparten el instante **al microsegundo** y
    quien salga primero lo decide el desempate por `id`, no la cronologia.
    Exigir una posicion aqui seria exigir un orden que el dato no contiene.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    borrador = articulo(
        "docker-en-produccion",
        estado=PostStatus.DRAFT,
        resumen="Resumen suficiente para publicar.",
        contenido="Cuerpo del articulo.",
    )
    sesion_de_pruebas.add(borrador)
    sesion_de_pruebas.flush()

    publicacion = cliente_administrativo.post(f"{ADMIN}/posts/{borrador.id}/publish")
    assert publicacion.status_code == 200, publicacion.text

    cuerpo = cliente_administrativo.get(HISTORIAL, params={"page_size": 50}).json()
    publicados = [
        elemento
        for elemento in cuerpo["items"]
        if elemento["action"] == AccionAuditada.CONTENIDO_PUBLICADO
    ]

    assert len(publicados) == 1
    assert publicados[0]["entity_type"] == ENTIDAD_ARTICULO
    assert publicados[0]["entity_id"] == str(borrador.id)


# --- La lectura no se audita ----------------------------------------------
def test_leer_el_historial_no_escribe_en_el_historial(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """**Requisito central.** CONTENT_MODEL.md 3.9: *"las lecturas no se auditan"*.

    Sin *mock*: se cuentan las filas reales antes y despues. La prueba se pone
    roja el dia que alguien decida auditar una lectura.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    for minutos in range(3):
        _evento(sesion_de_pruebas, occurred_at=BASE + timedelta(minutes=minutos))
    sesion_de_pruebas.commit()

    antes = _contar(sesion_de_pruebas)
    assert cliente_administrativo.get(HISTORIAL).status_code == 200
    sesion_de_pruebas.expire_all()
    despues = _contar(sesion_de_pruebas)

    assert despues == antes


# --- Privacidad del DTO sobre la respuesta real ---------------------------
@pytest.mark.parametrize(
    "campo", ["actor_id", "event_metadata", "metadata", "request_id", "ip_address"]
)
def test_la_respuesta_real_no_transporta_campos_internos(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, campo: str
) -> None:
    """No basta con OpenAPI: se inspecciona el JSON entero de la respuesta.

    El evento se escribe **con** los tres datos rellenos, de modo que la prueba
    falla si la serializacion los filtrara.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    _evento(
        sesion_de_pruebas,
        occurred_at=BASE,
        ip_address="203.0.113.7",
        request_id="req-secreto",
        event_metadata={"slug": "docker", "estado_anterior": "draft"},
    )

    texto = cliente_administrativo.get(HISTORIAL).text

    assert campo not in texto


def test_cada_elemento_tiene_exactamente_los_cinco_campos_del_contrato(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """La superficie del DTO, comprobada sobre la respuesta y no sobre el esquema."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    _evento(sesion_de_pruebas, occurred_at=BASE)

    for elemento in cliente_administrativo.get(HISTORIAL).json()["items"]:
        assert set(elemento) == {"id", "occurred_at", "action", "entity_type", "entity_id"}


# --- Seguridad del transporte ---------------------------------------------
def test_el_historial_no_se_cachea(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B-13: `Cache-Control: no-store` en todo el prefijo administrativo."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.get(HISTORIAL)

    assert respuesta.headers["cache-control"] == "no-store"


def test_un_get_no_exige_origen(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """La politica vigente solo comprueba `Origin` en los metodos que cambian estado.

    No se anade ninguna excepcion: el resultado se deriva de
    `app/shared/security/origen.py`, que deja fuera `GET`, `HEAD` y `OPTIONS`.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.get(HISTORIAL, headers={"Origin": "https://evil.invalid"})

    assert respuesta.status_code == 200


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_el_historial_no_admite_escritura(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, metodo: str
) -> None:
    """Invariantes 16 y 16b: la ruta no ofrece ninguna forma de escribir."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.request(metodo, HISTORIAL)

    assert respuesta.status_code == 405


def test_no_existe_el_detalle_de_un_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El MVP lista; no navega a un evento suelto. La ausencia es el contrato."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    fila = _evento(sesion_de_pruebas, occurred_at=BASE)

    assert cliente_administrativo.get(f"{HISTORIAL}/{fila.id}").status_code == 404
