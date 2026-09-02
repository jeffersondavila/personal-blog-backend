"""Escritura de eventos de auditoria (`Task/011`).

Implementa el puerto `RegistroDeAuditoria` que declara el modulo de
autenticacion. Solo **crea**: la auditoria no se modifica ni se borra, y las
guardas que lo garantizan viven en el modelo desde `Task/008`. Esta tarea no las
toca ni las necesita relajar.

No confirma la transaccion: el evento se hace duradero con el resto de la
operacion que lo produjo, que es lo correcto. Un intento fallido cuyo contador se
persistiera pero cuyo evento se perdiera contaria una historia incompleta.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import ENTIDAD_ADMINISTRADOR
from app.modules.audit.infrastructure.models import AuditEvent


class RegistroSqlDeAuditoria:
    """Escribe eventos de auditoria en PostgreSQL."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def registrar(
        self,
        accion: str,
        *,
        actor_id: uuid.UUID | None,
        entidad_id: uuid.UUID | None,
        request_id: str | None,
        ip: str | None,
        metadatos: dict[str, Any] | None = None,
    ) -> None:
        """Anade un evento al historial.

        `metadatos` existe en la firma porque el modelo lo tiene, pero la
        autenticacion **no lo usa**: lo unico que podria poner ahi —el correo
        intentado— es justamente lo que no debe guardarse. Quien actuo lo dice
        `actor_id`; desde donde, `ip_address`; y con que peticion, `request_id`.
        Eso ya permite correlacionar sin recolectar datos personales de terceros
        (requisitos O-08 y O-09).
        """
        self._sesion.add(
            AuditEvent(
                actor_id=actor_id,
                action=accion,
                entity_type=ENTIDAD_ADMINISTRADOR,
                entity_id=entidad_id,
                request_id=request_id,
                ip_address=ip,
                event_metadata=metadatos or {},
            )
        )
        self._sesion.flush()
