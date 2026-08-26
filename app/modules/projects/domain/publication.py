"""Ciclo de vida de un proyecto: publicacion y estado del trabajo.

Dominio puro: **Python plano**, sin FastAPI, SQLAlchemy ni Alembic (ADR-004).

Dos estados que no deben mezclarse
----------------------------------

| Concepto | Enumeracion | Columna | Responde a |
| --- | --- | --- | --- |
| Visibilidad publica | `ProjectStatus` | `status` | ¿lo ve un visitante? |
| Marcha del trabajo | `ProjectWorkStatus` | `project_status` | ¿sigue vivo el proyecto? |

CONTENT_MODEL.md seccion 3.5 lo advierte de forma explicita: son conceptos
distintos. Un proyecto **terminado** puede estar publicado, y uno **activo**
puede seguir en borrador.

**Un proyecto no se despublica**, igual que un video: MVP_SCOPE.md seccion 3.2
reserva `published -> draft` a articulos y reviews. La regla se expresa por
ausencia del metodo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.shared.errors.exceptions import ConflictError


class ProjectStatus(StrEnum):
    """Estados de **publicacion** de un proyecto. Contrato cerrado de la API."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ProjectWorkStatus(StrEnum):
    """Marcha del **trabajo** del proyecto. Nada que ver con su visibilidad.

    Conjunto minimo del MVP, tomado de los ejemplos de CONTENT_MODEL.md seccion
    3.5. No se construye aqui un flujo de trabajo que el producto no ha pedido.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class InvalidProjectStateError(ConflictError):
    """La operacion solicitada no es valida para el estado actual del proyecto."""

    code = "invalid_project_state"


@dataclass(frozen=True, slots=True)
class ProjectPublication:
    """Estado de publicacion de un proyecto, inmutable."""

    status: ProjectStatus
    published_at: datetime | None

    def __post_init__(self) -> None:
        """Invariante 1 de CONTENT_MODEL.md: `published` exige `published_at`."""
        if self.status is ProjectStatus.PUBLISHED and self.published_at is None:
            raise InvalidProjectStateError(
                "Un proyecto publicado debe tener fecha de publicacion.",
            )

    @classmethod
    def draft(cls) -> ProjectPublication:
        """Estado inicial de un proyecto recien creado."""
        return cls(status=ProjectStatus.DRAFT, published_at=None)

    @classmethod
    def restore(cls, status: ProjectStatus, published_at: datetime | None) -> ProjectPublication:
        """Reconstruye el estado a partir de lo persistido."""
        return cls(status=status, published_at=published_at)

    def publish(self, *, now: datetime) -> ProjectPublication:
        """Publica un borrador, conservando la fecha de la primera publicacion."""
        if self.status is not ProjectStatus.DRAFT:
            raise InvalidProjectStateError(
                f"Solo se puede publicar un borrador; el proyecto esta en '{self.status.value}'.",
            )
        if now.tzinfo is None:
            raise InvalidProjectStateError(
                "La fecha de publicacion debe llevar zona horaria: el proyecto trabaja en UTC.",
            )
        return ProjectPublication(
            status=ProjectStatus.PUBLISHED,
            published_at=self.published_at if self.published_at is not None else now,
        )

    def archive(self) -> ProjectPublication:
        """Archiva el proyecto, conservando el registro y la fecha."""
        if self.status is ProjectStatus.ARCHIVED:
            raise InvalidProjectStateError("El proyecto ya esta archivado.")
        return ProjectPublication(status=ProjectStatus.ARCHIVED, published_at=self.published_at)
