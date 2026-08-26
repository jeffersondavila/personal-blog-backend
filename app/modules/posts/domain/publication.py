"""Ciclo de vida de publicacion de un articulo.

Dominio puro: **Python plano**. No importa FastAPI, SQLAlchemy ni Alembic
(ADR-004, software-architecture.md seccion 3.2).

Reglas vigentes (MVP_SCOPE.md seccion 3.2, USER_FLOWS.md B.7 a B.9):

- Un articulo nace en `draft` y sin fecha de publicacion.
- Publicarlo fija `published_at` **la primera vez** y la conserva despues: es la
  fecha de la **primera** publicacion, no la de la ultima.
- Despublicar devuelve el articulo a `draft` y **conserva** `published_at` como
  referencia historica (B.8). Por eso un borrador **puede** tener fecha.
- Archivar retira el articulo sin borrarlo. Restaurar desde `archived` no
  pertenece al MVP, asi que `archived` es terminal aqui: no se implementa
  comportamiento que nadie ha pedido.
- Un estado `published` sin `published_at` es irrepresentable.

Por que cada modulo tiene su propio ciclo de vida
-------------------------------------------------

`Post` y `BookReview` admiten `published -> draft`; `Video` y `Project` **no**
(MVP_SCOPE.md seccion 3.2). Las reglas son distintas, asi que cada modulo es
dueno de las suyas: ADR-004 exige que cada modulo posea su dominio completo y
prohibe alojar reglas de negocio en `app/shared`. Extraer una base comun
obligaria a crear un modulo transversal que la lista de modulos de ADR-004 no
contempla; esa seria una decision de arquitectura con su propio ADR, no un
detalle de esta tarea.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.shared.errors.exceptions import ConflictError


class PostStatus(StrEnum):
    """Estados de publicacion de un articulo.

    Los tres valores son un **contrato cerrado** de la API
    (api-contracts.md seccion 10, regla 5).
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class InvalidPostStateError(ConflictError):
    """La operacion solicitada no es valida para el estado actual del articulo."""

    code = "invalid_post_state"


@dataclass(frozen=True, slots=True)
class PostPublication:
    """Estado de publicacion de un articulo, inmutable.

    Cada transicion devuelve una **instancia nueva**: el objeto no se muta, asi
    que no existe un estado intermedio invalido observable por nadie.
    """

    status: PostStatus
    published_at: datetime | None

    def __post_init__(self) -> None:
        """Invariante 1 de CONTENT_MODEL.md: `published` exige `published_at`.

        La inversa **no** se comprueba: un `draft` con fecha es el resultado
        legitimo de despublicar (B.8).
        """
        if self.status is PostStatus.PUBLISHED and self.published_at is None:
            raise InvalidPostStateError(
                "Un articulo publicado debe tener fecha de publicacion.",
            )

    @classmethod
    def draft(cls) -> PostPublication:
        """Estado inicial de un articulo recien creado."""
        return cls(status=PostStatus.DRAFT, published_at=None)

    @classmethod
    def restore(cls, status: PostStatus, published_at: datetime | None) -> PostPublication:
        """Reconstruye el estado a partir de lo persistido."""
        return cls(status=status, published_at=published_at)

    def publish(self, *, now: datetime) -> PostPublication:
        """Publica un borrador.

        `published_at` solo se fija si el articulo no se habia publicado nunca:
        volver a publicar algo despublicado no reescribe su historia.
        """
        if self.status is not PostStatus.DRAFT:
            raise InvalidPostStateError(
                f"Solo se puede publicar un borrador; el articulo esta en '{self.status.value}'.",
            )
        if now.tzinfo is None:
            raise InvalidPostStateError(
                "La fecha de publicacion debe llevar zona horaria: el proyecto trabaja en UTC.",
            )
        return PostPublication(
            status=PostStatus.PUBLISHED,
            published_at=self.published_at if self.published_at is not None else now,
        )

    def unpublish(self) -> PostPublication:
        """Devuelve un articulo publicado a borrador, conservando la fecha."""
        if self.status is not PostStatus.PUBLISHED:
            raise InvalidPostStateError(
                "Solo se puede despublicar un articulo publicado; "
                f"el articulo esta en '{self.status.value}'.",
            )
        return PostPublication(status=PostStatus.DRAFT, published_at=self.published_at)

    def archive(self) -> PostPublication:
        """Archiva el articulo, conservando el registro y la fecha."""
        if self.status is PostStatus.ARCHIVED:
            raise InvalidPostStateError("El articulo ya esta archivado.")
        return PostPublication(status=PostStatus.ARCHIVED, published_at=self.published_at)
