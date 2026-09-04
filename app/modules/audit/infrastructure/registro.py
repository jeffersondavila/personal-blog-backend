"""Escritura de eventos de auditoria (`Task/011`, ampliada en `Task/012`).

Implementa el puerto `RegistroDeAuditoria` que declara el dominio de este mismo
modulo (`Task/012` lo mudo aqui desde `authentication`, donde `Task/011` lo dejo
cuando era su unico consumidor). Solo **crea**: la auditoria no se modifica ni se
borra, y las guardas que lo garantizan viven en el modelo desde `Task/008`. Esta
tarea no las toca ni las necesita relajar.

No confirma la transaccion: el evento se hace duradero con el resto de la
operacion que lo produjo, que es lo correcto. Un intento fallido cuyo contador se
persistiera pero cuyo evento se perdiera contaria una historia incompleta.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditEvent


class RegistroSqlDeAuditoria:
    """Escribe eventos de auditoria en PostgreSQL."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def registrar(
        self,
        accion: str,
        *,
        entidad: str,
        actor_id: uuid.UUID | None,
        entidad_id: uuid.UUID | None,
        request_id: str | None,
        ip: str | None,
        metadatos: dict[str, Any] | None = None,
    ) -> None:
        """Anade un evento al historial.

        `entidad` no tiene valor por defecto. Hasta `Task/012` este metodo
        escribia siempre `administrator`, porque la autenticacion era su unico
        consumidor; ahora hay siete tipos. Un valor por defecto etiquetaria en
        silencio como administrador el evento de quien se olvidara de pasarlo, y
        ese defecto solo se veria al leer el historial.

        `metadatos` es **contexto adicional no sensible** (CONTENT_MODEL.md 3.9).
        La autenticacion **no lo usa**: lo unico que podria poner ahi —el correo
        intentado— es justamente lo que no debe guardarse. `Task/012` lo usa de
        forma minima (decision D-012-O): el `slug` del contenido, los dos estados
        de una transicion o el nombre original de un archivo. Nunca Markdown,
        contrasenas, credenciales ni cabeceras.
        """
        self._sesion.add(
            AuditEvent(
                actor_id=actor_id,
                action=accion,
                entity_type=entidad,
                entity_id=entidad_id,
                request_id=request_id,
                ip_address=ip,
                event_metadata=metadatos or {},
            )
        )
        self._sesion.flush()
