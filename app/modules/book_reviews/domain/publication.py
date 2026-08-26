"""Ciclo de vida de publicacion de una review de libro.

Dominio puro: **Python plano**, sin FastAPI, SQLAlchemy ni Alembic (ADR-004).

Las reglas son las mismas que las de un articulo: MVP_SCOPE.md seccion 3.2
otorga la despublicacion (`published -> draft`) a **articulos y reviews**, y solo
a ellos. Cada modulo es dueno de su dominio completo (ADR-004, seccion 3), asi
que la regla vive aqui y no en un paquete comun: `app/shared` esta reservado a
capacidades tecnicas transversales y tiene prohibido alojar reglas de negocio
(software-architecture.md seccion 3.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.shared.errors.exceptions import ConflictError


class BookReviewStatus(StrEnum):
    """Estados de publicacion de una review. Contrato cerrado de la API."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class InvalidBookReviewStateError(ConflictError):
    """La operacion solicitada no es valida para el estado actual de la review."""

    code = "invalid_book_review_state"


@dataclass(frozen=True, slots=True)
class BookReviewPublication:
    """Estado de publicacion de una review, inmutable."""

    status: BookReviewStatus
    published_at: datetime | None

    def __post_init__(self) -> None:
        """Invariante 1 de CONTENT_MODEL.md: `published` exige `published_at`.

        La inversa **no** se comprueba: un `draft` con fecha es el resultado
        legitimo de despublicar (USER_FLOWS.md B.8).
        """
        if self.status is BookReviewStatus.PUBLISHED and self.published_at is None:
            raise InvalidBookReviewStateError(
                "Una review publicada debe tener fecha de publicacion.",
            )

    @classmethod
    def draft(cls) -> BookReviewPublication:
        """Estado inicial de una review recien creada."""
        return cls(status=BookReviewStatus.DRAFT, published_at=None)

    @classmethod
    def restore(
        cls, status: BookReviewStatus, published_at: datetime | None
    ) -> BookReviewPublication:
        """Reconstruye el estado a partir de lo persistido."""
        return cls(status=status, published_at=published_at)

    def publish(self, *, now: datetime) -> BookReviewPublication:
        """Publica un borrador, conservando la fecha de la primera publicacion."""
        if self.status is not BookReviewStatus.DRAFT:
            raise InvalidBookReviewStateError(
                f"Solo se puede publicar un borrador; la review esta en '{self.status.value}'.",
            )
        if now.tzinfo is None:
            raise InvalidBookReviewStateError(
                "La fecha de publicacion debe llevar zona horaria: el proyecto trabaja en UTC.",
            )
        return BookReviewPublication(
            status=BookReviewStatus.PUBLISHED,
            published_at=self.published_at if self.published_at is not None else now,
        )

    def unpublish(self) -> BookReviewPublication:
        """Devuelve una review publicada a borrador, conservando la fecha."""
        if self.status is not BookReviewStatus.PUBLISHED:
            raise InvalidBookReviewStateError(
                "Solo se puede despublicar una review publicada; "
                f"la review esta en '{self.status.value}'.",
            )
        return BookReviewPublication(status=BookReviewStatus.DRAFT, published_at=self.published_at)

    def archive(self) -> BookReviewPublication:
        """Archiva la review, conservando el registro y la fecha."""
        if self.status is BookReviewStatus.ARCHIVED:
            raise InvalidBookReviewStateError("La review ya esta archivada.")
        return BookReviewPublication(
            status=BookReviewStatus.ARCHIVED, published_at=self.published_at
        )
