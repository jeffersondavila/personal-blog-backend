"""Modelo ORM del registro de auditoria.

`Task/008` define **la persistencia y sus invariantes minimas**. El servicio de
auditoria, el *middleware*, el catalogo definitivo de acciones y los enganches
automaticos son de `Task/011` y `Task/012`.

La referencia polimorfica, y por que no lleva clave foranea
-----------------------------------------------------------

`entity_type` + `entity_id` identifican el elemento afectado. **No hay clave
foranea**, y es una decision, no un olvido:

1. **Un evento debe sobrevivir a lo que describe.** Si borrar un articulo
   borrara o bloqueara su historial de auditoria, el registro dejaria de ser
   historial. Una clave foranea produce exactamente uno de esos dos efectos.
2. **No existe una clave foranea hacia varias tablas.** Las alternativas serian
   una supertabla `content` —la superentidad que este modelo descarta por
   diseno— o una columna nula por cada tipo, que ademas no sabria expresar "solo
   una de ellas esta rellena".

**El precio, dicho sin adornos:** la base no puede garantizar que
`entity_type` + `entity_id` apunten a algo que exista. Es integridad que el
esquema **no** ofrece, y quien lea el historial debe contar con referencias a
elementos ya eliminados. Se acepta porque un registro historico describe lo que
paso, no lo que sigue existiendo. Los UUID reducen el dano: una referencia con el
tipo equivocado no coincide con ninguna fila de ninguna otra tabla, cosa que si
ocurriria con enteros secuenciales.

`actor_id` **si** es clave foranea, con `ON DELETE RESTRICT`: el administrador es
una entidad del sistema, no un elemento auditado, y borrarlo dejando su historial
huerfano seria perder la respuesta a "quien hizo esto".

Inmutabilidad: que garantizan exactamente las guardas
------------------------------------------------------

Las dos guardas de mas abajo se registran en el *mapper*, asi que actuan cuando
la **unit of work** de SQLAlchemy va a emitir un `UPDATE` o un `DELETE` sobre una
instancia de `AuditEvent`. Ese es el camino por el que se escribe normalmente:
cargar la entidad, tocarla y hacer `flush`.

**Lo que cubren:**

- `evento.action = "otra"` seguido de `flush` -> rechazado.
- `session.delete(evento)` seguido de `flush` -> rechazado.

**Lo que NO cubren, comprobado y no supuesto:**

- DML masivo del ORM: `session.execute(update(AuditEvent).where(...).values(...))`
  y su equivalente con `delete()`. Esas sentencias van directas al motor sin
  pasar por el *mapper*.
- Sentencias de nivel Core sobre la tabla, y cualquier SQL escrito a mano.

La distincion importa y no se maquilla: **es codigo de aplicacion el que puede
sortear la guarda por la ruta masiva**. Decir "la aplicacion no puede modificar un
evento" seria falso. Lo cierto es mas modesto y se sostiene: *la ruta normal de
escritura del ORM esta cerrada, y las demas no*.

Cerrar el resto no se hace con mas enganches, que siempre dejan una ruta mas:
se hace **retirando `UPDATE` y `DELETE` sobre `audit_events` al rol de base de
datos de la aplicacion**. Eso es privilegio minimo (requisito S-01) y pertenece
al endurecimiento de `Task/018`. Mientras tanto, el perimetro real esta fijado por
prueba en `tests/integration/test_auditoria.py`, que comprueba **las dos
mitades**: lo que se bloquea y lo que no.

Que NO se guarda aqui
---------------------

`metadata` es **contexto adicional no sensible**. Nunca contrasenas, tokens,
secretos, cabeceras de autorizacion ni la propia `DATABASE_URL` (requisitos S-08
y O-08). Ser un campo libre no lo convierte en un vertedero: lo que no deberia
aparecer en un log tampoco debe aparecer aqui.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, DateTime, ForeignKey, Index, String, Uuid, event, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.shared.database.base import Base
from app.shared.database.mixins import UuidPrimaryKeyMixin
from app.shared.errors.exceptions import ConflictError


class AuditEventIsImmutableError(ConflictError):
    """Se intento modificar o eliminar un registro de auditoria ya escrito."""

    code = "audit_event_is_immutable"


LONGITUD_DE_ACCION = 64
LONGITUD_DE_TIPO_DE_ENTIDAD = 64
LONGITUD_DE_IDENTIFICADOR_DE_PETICION = 64
#: 45 caracteres cubren IPv6 y las formas IPv4 mapeadas.
LONGITUD_DE_DIRECCION_IP = 45


class AuditEvent(UuidPrimaryKeyMixin, Base):
    """Registro inmutable de una accion administrativa.

    No lleva `updated_at`, y su ausencia es parte del diseno: un evento no se
    modifica, asi que no hay nada que fechar.
    """

    __tablename__ = "audit_events"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: Administrador que ejecuto la accion. Admite nulo porque hay eventos sin
    #: actor identificado: un intento de acceso fallido tambien se audita
    #: (USER_FLOWS.md B.1) y en ese momento no se sabe quien lo intento.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("administrators.id", ondelete="RESTRICT"), index=True
    )
    #: Accion realizada. Cadena libre a este nivel: el catalogo exacto de
    #: acciones auditables se cierra en `Task/011` y `Task/012`, y congelarlo hoy
    #: en un `CHECK` obligaria a migrar el esquema para decidirlo.
    action: Mapped[str] = mapped_column(String(LONGITUD_DE_ACCION), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(LONGITUD_DE_TIPO_DE_ENTIDAD), nullable=False)
    #: Admite nulo: iniciar o cerrar sesion no afecta a ningun elemento.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    #: Correlation ID de la peticion (api-contracts.md seccion 9). Admite nulo
    #: mientras `Task/017` no fije la cabecera concreta.
    request_id: Mapped[str | None] = mapped_column(String(LONGITUD_DE_IDENTIFICADOR_DE_PETICION))
    #: El atributo de Python no puede llamarse `metadata`: ese nombre lo ocupa el
    #: objeto `MetaData` de la base declarativa de SQLAlchemy. La **columna** si
    #: se llama `metadata`, que es como la nombra CONTENT_MODEL.md.
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    ip_address: Mapped[str | None] = mapped_column(String(LONGITUD_DE_DIRECCION_IP))

    __table_args__ = (
        # Listado cronologico del historial.
        Index("ix_audit_events_occurred_at", "occurred_at"),
        # "Que le paso a este elemento": la consulta natural sobre la referencia
        # polimorfica, y la unica forma de recorrerla sin escanear la tabla.
        Index("ix_audit_events_entity_type_entity_id", "entity_type", "entity_id"),
        # Trazabilidad extremo a extremo por correlation ID: el objetivo
        # declarado en api-contracts.md seccion 9.
        Index("ix_audit_events_request_id", "request_id"),
    )


@event.listens_for(AuditEvent, "before_update", propagate=True)
def _rechazar_la_modificacion(
    mapper: Mapper[AuditEvent], connection: Connection, target: AuditEvent
) -> None:
    """Rechaza el `UPDATE` que la *unit of work* del ORM emitiria sobre un evento.

    Se engancha al *mapper* y no a un caso de uso concreto: la garantia no
    depende de que cada codigo futuro se acuerde de respetarla.

    **Alcance exacto**: cubre el camino por el que se escribe normalmente —cargar
    la entidad, modificarla y hacer `flush`—. **No** cubre las sentencias DML
    masivas (`session.execute(update(AuditEvent)...)`), que no pasan por el
    *mapper*. Ver la nota del modulo.
    """
    raise AuditEventIsImmutableError(
        "Un registro de auditoria no se modifica: solo se crea y se lee.",
    )


@event.listens_for(AuditEvent, "before_delete", propagate=True)
def _rechazar_el_borrado(
    mapper: Mapper[AuditEvent], connection: Connection, target: AuditEvent
) -> None:
    """La otra mitad: la *unit of work* del ORM tampoco puede eliminar un evento.

    Mismo alcance que la guarda de actualizacion, y las mismas dos rutas fuera de
    su alcance.

    La retencion del historial —cuanto tiempo se conserva y como se purga— es una
    decision de operacion que CONTENT_MODEL.md deja pendiente, y desde luego no se
    resuelve dando a la aplicacion la capacidad de borrar eventos uno a uno.
    """
    raise AuditEventIsImmutableError(
        "Un registro de auditoria no se elimina: solo se crea y se lee.",
    )
