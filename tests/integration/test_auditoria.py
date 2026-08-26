"""Persistencia e inmutabilidad del registro de auditoria (matriz G).

`Task/008` no construye el servicio de auditoria: no hay *middleware*, ni
catalogo de acciones, ni enganches automaticos. Lo que si le corresponde es que
el **esquema y su capa de persistencia** cumplan la invariante 8 de
CONTENT_MODEL.md: *un `AuditEvent` nunca se modifica ni se elimina*.

Alcance exacto de la inmutabilidad que se prueba aqui
-----------------------------------------------------

Las guardas viven en el *mapper*, asi que actuan sobre la **unit of work** del
ORM: cargar la entidad, modificarla y hacer `flush`. Ese es el camino por el que
se escribe normalmente, y esta cerrado.

**No** estan cerradas las sentencias DML masivas del ORM ni las de nivel Core.
Este modulo lo comprueba en las dos direcciones —lo que se bloquea **y lo que
no**— para que la garantia quede fijada por prueba y nadie la lea de mas. Cerrar
el resto se hace retirando `UPDATE` y `DELETE` sobre `audit_events` al rol de
base de datos de la aplicacion: privilegio minimo (S-01), `Task/018`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Delete, Update, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditEvent, AuditEventIsImmutableError
from app.modules.authentication.infrastructure.models import Administrator
from app.modules.posts.infrastructure.models import Post

pytestmark = pytest.mark.integration

HASH_DE_RELLENO = "no-es-un-hash-real-task-008"


def _administrador() -> Administrator:
    return Administrator(
        email="persona@ejemplo.invalid",
        password_hash=HASH_DE_RELLENO,
        display_name="Administradora de prueba",
    )


def _evento(**campos: object) -> AuditEvent:
    valores: dict[str, object] = {"action": "post.published", "entity_type": "post"}
    valores.update(campos)
    return AuditEvent(**valores)


# --- G-01 ------------------------------------------------------------------
def test_se_registra_un_evento_con_su_actor(sesion_de_pruebas: Session) -> None:
    administrador = _administrador()
    articulo = Post(slug="auditado", title="Auditado")
    sesion_de_pruebas.add_all([administrador, articulo])
    sesion_de_pruebas.flush()

    evento = _evento(actor_id=administrador.id, entity_id=articulo.id)
    sesion_de_pruebas.add(evento)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(evento)

    assert evento.actor_id == administrador.id
    assert evento.occurred_at.tzinfo is not None


# --- G-02 ------------------------------------------------------------------
def test_un_evento_sin_actor_identificado_se_acepta(sesion_de_pruebas: Session) -> None:
    """Un intento de acceso fallido se audita sin saber quien lo intento (B.1)."""
    sesion_de_pruebas.add(
        _evento(action="auth.login_failed", entity_type="administrator", actor_id=None)
    )

    sesion_de_pruebas.flush()  # no debe lanzar


# --- G-03 ------------------------------------------------------------------
def test_la_referencia_polimorfica_no_exige_que_el_elemento_exista(
    sesion_de_pruebas: Session,
) -> None:
    """Es el precio consciente de no poner clave foranea, y se deja escrito.

    Un evento debe poder describir algo que ya fue eliminado: para eso existe un
    historial.
    """
    sesion_de_pruebas.add(
        _evento(action="post.deleted", entity_type="post", entity_id=uuid.uuid4())
    )

    sesion_de_pruebas.flush()  # no debe lanzar


# --- G-04 ------------------------------------------------------------------
def test_un_actor_inexistente_se_rechaza(sesion_de_pruebas: Session) -> None:
    """`actor_id` **si** es clave foranea: el actor no es un elemento auditado."""
    sesion_de_pruebas.add(_evento(actor_id=uuid.uuid4()))

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- G-05 ------------------------------------------------------------------
def test_modificar_un_evento_registrado_se_rechaza(sesion_de_pruebas: Session) -> None:
    evento = _evento()
    sesion_de_pruebas.add(evento)
    sesion_de_pruebas.flush()

    evento.action = "post.archived"

    with pytest.raises(AuditEventIsImmutableError):
        sesion_de_pruebas.flush()


# --- G-06 ------------------------------------------------------------------
def test_eliminar_un_evento_registrado_se_rechaza(sesion_de_pruebas: Session) -> None:
    evento = _evento()
    sesion_de_pruebas.add(evento)
    sesion_de_pruebas.flush()

    sesion_de_pruebas.delete(evento)

    with pytest.raises(AuditEventIsImmutableError):
        sesion_de_pruebas.flush()


# --- G-07 ------------------------------------------------------------------
def test_no_se_puede_eliminar_un_administrador_con_historial(
    sesion_de_pruebas: Session,
) -> None:
    administrador = _administrador()
    sesion_de_pruebas.add(administrador)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.add(_evento(actor_id=administrador.id))
    sesion_de_pruebas.flush()

    sesion_de_pruebas.delete(administrador)

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- G-08 ------------------------------------------------------------------
def test_el_contexto_adicional_se_guarda_estructurado(sesion_de_pruebas: Session) -> None:
    contexto = {"slug": "un-articulo", "campos_modificados": ["title", "summary"]}
    evento = _evento(event_metadata=contexto, request_id="peticion-de-prueba-0001")
    sesion_de_pruebas.add(evento)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(evento)

    assert evento.event_metadata == contexto
    assert evento.request_id == "peticion-de-prueba-0001"


def test_el_contexto_adicional_nace_vacio(sesion_de_pruebas: Session) -> None:
    """Sin contexto es `{}`, no `NULL`: quien lo lea no tiene que distinguir dos vacios."""
    evento = _evento()
    sesion_de_pruebas.add(evento)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(evento)

    assert evento.event_metadata == {}


def test_un_evento_no_tiene_marca_de_modificacion() -> None:
    """La ausencia es el diseno: lo que no se modifica no necesita fecharse."""
    assert "updated_at" not in AuditEvent.__table__.columns


# --- Perimetro exacto de la guarda ----------------------------------------
@pytest.mark.parametrize("operacion", ["update", "delete"])
def test_el_dml_masivo_del_orm_no_pasa_por_la_guarda(
    sesion_de_pruebas: Session, operacion: str
) -> None:
    """Documenta un hueco **real**, en lugar de dejar que la garantia suene mayor.

    Una sentencia `update()` o `delete()` ejecutada contra el modelo no recorre la
    *unit of work*: viaja al motor sin pasar por el *mapper*, asi que las guardas
    no la ven. Es codigo de aplicacion perfectamente valido, y por eso afirmar
    "la aplicacion no puede modificar un evento" seria falso.

    **Esta prueba esta escrita para ponerse roja el dia que el hueco se cierre.**
    Si alguien anade una guarda de sesion, o `Task/018` retira los privilegios al
    rol, este caso fallara y obligara a revisar la documentacion en lugar de
    dejarla desactualizada afirmando de menos.
    """
    evento = _evento()
    sesion_de_pruebas.add(evento)
    sesion_de_pruebas.flush()

    identificador = evento.id
    instruccion: Update | Delete = (
        update(AuditEvent).where(AuditEvent.id == identificador).values(action="post.archived")
        if operacion == "update"
        else delete(AuditEvent).where(AuditEvent.id == identificador)
    )

    sesion_de_pruebas.execute(instruccion)
    sesion_de_pruebas.expire_all()
    persistido = sesion_de_pruebas.get(AuditEvent, identificador)

    # Se comprueba el **efecto**, no un contador: la sentencia llego de verdad a
    # la fila. Un `rowcount` podria mentir; el estado de la base, no.
    if operacion == "update":
        alcanzado = persistido is not None and persistido.action == "post.archived"
    else:
        alcanzado = persistido is None

    assert alcanzado, (
        "el DML masivo del ORM dejo de alcanzar audit_events. Si es porque la "
        "guarda se reforzo, actualiza tambien el docstring del modelo, "
        "data-model.md (seccion 6.0, D-N e invariante 16) y el criterio de "
        "aceptacion 11: la garantia documentada tiene que seguir coincidiendo "
        "con la real."
    )
