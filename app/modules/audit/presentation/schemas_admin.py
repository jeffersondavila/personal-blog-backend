"""Esquema HTTP del historial administrativo (`Task/012.1`).

**No se devuelve el modelo ORM** (regla 9 de software-architecture.md seccion
3.5). Aqui esa separacion tiene un efecto concreto y comprobado: `ip_address`,
`actor_id` y `event_metadata` **no tienen ninguna ruta** hacia una respuesta.

Los cinco campos del contrato `v1`
-----------------------------------

| Campo | Por que esta |
| --- | --- |
| `id` | Identidad estable; el panel necesita una clave de lista que no dependa de la posicion |
| `occurred_at` | **Es "ultimos"**: sin la fecha no hay orden cronologico que mostrar |
| `action` | **Es "que paso"**; catalogo cerrado de quince acciones (CONTENT_MODEL.md 3.9) |
| `entity_type` | **Es "sobre que"**: `content.*` no dice el tipo; lo dice esta columna |
| `entity_id` | Enlaza el evento con el elemento. Nulo en los eventos de sesion |

Con ellos se renderiza una linea entera del dashboard, que es el unico consumidor
que `MVP_SCOPE.md` seccion 3.3 define.

Lo que **no** sale, y por que
------------------------------

- **`ip_address`.** Dato personal y operativo que listar el historial no
  necesita. El requisito **O-09** pide no exportar datos personales
  innecesarios, y `security-boundaries.md` A-13 mantiene el historial libre de
  datos de terceros.
- **`actor_id`.** El MVP tiene **un** administrador (MVP_SCOPE.md seccion 3):
  devolver su propio identificador no informa de nada, y resolver el nombre
  exigiria un `JOIN` sin consumidor.
- **`event_metadata`.** Aunque la decision **D-012-O** garantiza metadatos
  minimos y no sensibles, es un objeto de **forma libre**: fijarlo en `v1`
  congelaria una estructura que hoy varia por accion.
- **`request_id`.** Su proposito —trazar una peticion extremo a extremo
  (api-contracts.md seccion 9)— pertenece a `Task/017`, que todavia no ha fijado
  la cabecera; la columna es hoy nula la mayoria de las veces.

Los cuatro comparten la misma razon de fondo: **anadir un campo opcional despues
es compatible; retirarlo, no** (api-contracts.md seccion 10, reglas 2 y 3). Es
el mismo criterio con el que la seccion 12 rechazo `access_expires_at`.

La superficie se declara **campo a campo**, no por reflexion sobre el modelo:
derivarla haria que una columna nueva se publicara sola.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.audit.infrastructure.models import AuditEvent


class EventoDeAuditoria(BaseModel):
    """Un evento del historial, tal como lo ve el dashboard."""

    id: uuid.UUID = Field(description="Identificador interno del evento.")
    occurred_at: datetime = Field(description="Momento del evento, en UTC.")
    action: str = Field(description="Accion realizada; catalogo cerrado de quince valores.")
    entity_type: str = Field(description="Tipo del elemento afectado.")
    entity_id: uuid.UUID | None = Field(
        default=None,
        description="Elemento afectado. Nulo en los eventos de sesion, que no afectan a ninguno.",
    )

    @classmethod
    def de_modelo(cls, evento: AuditEvent) -> EventoDeAuditoria:
        """Proyecta el modelo ORM sobre los cinco campos del contrato."""
        return cls(
            id=evento.id,
            occurred_at=evento.occurred_at,
            action=evento.action,
            entity_type=evento.entity_type,
            entity_id=evento.entity_id,
        )
