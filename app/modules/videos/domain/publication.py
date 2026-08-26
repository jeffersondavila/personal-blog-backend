"""Ciclo de vida de publicacion de un video.

Dominio puro: **Python plano**, sin FastAPI, SQLAlchemy ni Alembic (ADR-004).

Diferencia deliberada con `Post` y `BookReview`
-----------------------------------------------

**Un video no se despublica.** MVP_SCOPE.md seccion 3.2 concede la transicion
`published -> draft` a articulos y reviews, y solo a ellos; los videos y los
proyectos se **archivan**. Aqui eso no se expresa con una comprobacion que
falla: se expresa con la **ausencia** del metodo. Una transicion que no existe
no puede invocarse por error ni habilitarse por descuido.

Si el producto llegara a pedirla, seria un cambio de alcance con su decision
registrada, no un detalle de implementacion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.shared.errors.exceptions import ConflictError


class VideoStatus(StrEnum):
    """Estados de publicacion de un video. Contrato cerrado de la API."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class InvalidVideoStateError(ConflictError):
    """La operacion solicitada no es valida para el estado actual del video."""

    code = "invalid_video_state"


@dataclass(frozen=True, slots=True)
class VideoPublication:
    """Estado de publicacion de un video, inmutable."""

    status: VideoStatus
    published_at: datetime | None

    def __post_init__(self) -> None:
        """Invariante 1 de CONTENT_MODEL.md: `published` exige `published_at`."""
        if self.status is VideoStatus.PUBLISHED and self.published_at is None:
            raise InvalidVideoStateError("Un video publicado debe tener fecha de publicacion.")

    @classmethod
    def draft(cls) -> VideoPublication:
        """Estado inicial de un video recien creado."""
        return cls(status=VideoStatus.DRAFT, published_at=None)

    @classmethod
    def restore(cls, status: VideoStatus, published_at: datetime | None) -> VideoPublication:
        """Reconstruye el estado a partir de lo persistido."""
        return cls(status=status, published_at=published_at)

    def publish(self, *, now: datetime) -> VideoPublication:
        """Publica un borrador, conservando la fecha de la primera publicacion."""
        if self.status is not VideoStatus.DRAFT:
            raise InvalidVideoStateError(
                f"Solo se puede publicar un borrador; el video esta en '{self.status.value}'.",
            )
        if now.tzinfo is None:
            raise InvalidVideoStateError(
                "La fecha de publicacion debe llevar zona horaria: el proyecto trabaja en UTC.",
            )
        return VideoPublication(
            status=VideoStatus.PUBLISHED,
            published_at=self.published_at if self.published_at is not None else now,
        )

    def archive(self) -> VideoPublication:
        """Archiva el video, conservando el registro y la fecha."""
        if self.status is VideoStatus.ARCHIVED:
            raise InvalidVideoStateError("El video ya esta archivado.")
        return VideoPublication(status=VideoStatus.ARCHIVED, published_at=self.published_at)
