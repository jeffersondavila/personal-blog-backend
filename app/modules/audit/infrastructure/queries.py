"""Consultas del historial administrativo (`Task/012.1`).

Solo lectura, asi que **no pasan por la capa `application`**: mismo criterio
**D-009-Q** que `Task/009` aplico a las consultas publicas y que
`media/infrastructure/queries.py` ya sigue. Una capa de aplicacion que solo
reenviara la llamada seria una abstraccion vacia (ADR-004, requisito M-06).

Tampoco hay repositorio: el repositorio existe donde hay escritura, y aqui **no
la hay**. La escritura del historial sigue siendo exclusivamente
`RegistroSqlDeAuditoria`, que esta tarea no toca.

Orden: **`occurred_at` descendente, desempate por `id` ascendente**

El desempate no es cosmetico. `occurred_at` tiene `server_default=func.now()`, y
en PostgreSQL `now()` es la marca de **inicio de la transaccion**: dos eventos
escritos en la misma transaccion la comparten exactamente. Es el mismo problema
que la decision **D-H** describe para `created_at` en la biblioteca de medios, y
un `LIMIT`/`OFFSET` sobre un orden **no total** puede repetir u omitir filas
entre paginas.

`id` es la clave primaria —`UNIQUE NOT NULL`—, que es justo lo que convierte el
orden en total. Y **ascendente**, que es la convencion ya fijada tres veces en
este proyecto: `published_at DESC, slug ASC` (**D-009-F**), `updated_at DESC,
slug ASC` (**D-012-L**) y `created_at DESC, object_key ASC` (medios). Como el
identificador es un UUID v4 generado en Python, no es monotono y ninguna
direccion transporta significado cronologico: entre dos opciones equivalentes se
elige la que el proyecto ya usa.

Indice: **ninguno nuevo**

`ix_audit_events_occurred_at` existe desde la migracion `0002` y `data-model.md`
seccion 5 lo justifica precisamente como *"listado cronologico del historial"*.
PostgreSQL recorre un B-tree en sentido inverso sin coste anadido, asi que sirve
para el `DESC`. No se anade un indice compuesto `(occurred_at, id)`: el
desempate solo actua entre las pocas filas que comparten instante, y ordenarlas
cuesta lo mismo que compararlas. Optimizar sin medir seria adivinar.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditEvent
from app.shared.pagination import ParametrosDePagina


def contar_eventos_de_auditoria(sesion: Session) -> int:
    """Total de eventos registrados en el historial."""
    return sesion.execute(select(func.count()).select_from(AuditEvent)).scalar_one()


def listar_eventos_de_auditoria(
    sesion: Session, *, parametros: ParametrosDePagina
) -> Sequence[AuditEvent]:
    """Pagina del historial, del evento mas reciente al mas antiguo.

    No carga ninguna relacion: el DTO no expone el actor, asi que un `JOIN` con
    `administrators` traeria filas que nadie va a leer.
    """
    consulta = (
        select(AuditEvent)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.asc())
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).scalars().all()
