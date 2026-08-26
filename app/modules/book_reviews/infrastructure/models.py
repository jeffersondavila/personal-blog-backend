"""Modelo ORM de las reviews de libros.

Traduce a PostgreSQL el tipo `BookReview` de CONTENT_MODEL.md seccion 3.3.

`title` es el titulo de la **review** y puede diferir de `book_title`, el titulo
del **libro**: son dos columnas distintas porque son dos cosas distintas.

Que puede exigir el esquema al crear
------------------------------------

**Solo `title` y `slug`.** USER_FLOWS.md B.2 es explicito: al crear un borrador
el administrador introduce el titulo, la aplicacion propone el slug, y no hay
nada mas. Los datos del libro llegan editando (B.3).

Por eso `book_title` y `book_author` **admiten nulo**, igual que `rating`.
Exigirlos al crear obligaria a inventar un autor que nadie ha escrito todavia, y
un valor inventado en la base es peor que un nulo: parece un dato.

Que una review **publicada** deba tenerlos es una validacion de **publicacion**
(B.7: "se validan los campos minimos") y pertenece a `Task/012`. El esquema tiene
que poder **representar** un borrador incompleto; impedir que se publique asi es
otra capa. Regresion: `tests/integration/test_borrador_minimo.py`.

`rating` es la escala que `Task/008` cierra: **entero de 1 a 5, ambos
inclusive**, con *check constraint* real. Admite nulo porque un borrador puede
existir antes de que su autor decida la nota; exigirla para **publicar** es una
validacion de publicacion y pertenece a `Task/012`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.book_reviews.domain import RATING_MAXIMO, RATING_MINIMO, BookReviewStatus
from app.modules.media.infrastructure.models import MediaAsset
from app.modules.tags.infrastructure.models import Tag, book_review_tags
from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UuidPrimaryKeyMixin
from app.shared.database.types import enum_column

LONGITUD_DE_SLUG = 160
LONGITUD_DE_TITULO = 200
LONGITUD_DE_RESUMEN = 500
LONGITUD_DE_AUTOR = 200
LONGITUD_DE_URL = 2048
LONGITUD_DE_TITULO_SEO = 70
LONGITUD_DE_DESCRIPCION_SEO = 160


class BookReview(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Review de un libro, con valoracion."""

    __tablename__ = "book_reviews"

    slug: Mapped[str] = mapped_column(String(LONGITUD_DE_SLUG), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(LONGITUD_DE_TITULO), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(LONGITUD_DE_RESUMEN))
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[BookReviewStatus] = mapped_column(
        enum_column(BookReviewStatus, name="book_review_status"),
        nullable=False,
        default=BookReviewStatus.DRAFT,
        server_default=BookReviewStatus.DRAFT.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

    #: Nulos mientras el borrador no los tenga: en B.2 todavia no se han escrito.
    book_title: Mapped[str | None] = mapped_column(String(LONGITUD_DE_TITULO))
    book_author: Mapped[str | None] = mapped_column(String(LONGITUD_DE_AUTOR))
    #: `SMALLINT` basta de sobra para 1..5 y deja explicito que no es un contador.
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    external_link: Mapped[str | None] = mapped_column(String(LONGITUD_DE_URL))

    #: Portada. `ON DELETE RESTRICT`: PostgreSQL se niega a borrar un medio que
    #: alguien esta usando (invariante 5 de CONTENT_MODEL.md). El mensaje amable
    #: que dice **donde** se usa lo construye `Task/010`; esto es la ultima
    #: linea de defensa, no la experiencia de usuario.
    #: Indexada porque la comprobacion de uso previa al borrado (USER_FLOWS.md
    #: B.5) consulta justo por esta columna.
    cover_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="RESTRICT"), index=True
    )
    cover: Mapped[MediaAsset | None] = relationship()

    #: Relacion unidireccional: el contenido conoce sus etiquetas.
    #: `Tag` no expone la lista inversa porque en el MVP nadie la pide;
    #: el filtro publico por etiqueta se resuelve con una consulta.
    tags: Mapped[list[Tag]] = relationship(secondary=book_review_tags)

    seo_title: Mapped[str | None] = mapped_column(String(LONGITUD_DE_TITULO_SEO))
    seo_description: Mapped[str | None] = mapped_column(String(LONGITUD_DE_DESCRIPCION_SEO))

    __table_args__ = (
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="publicado_exige_fecha",
        ),
        # Una comparacion con `NULL` da `NULL`, y un `CHECK` solo rechaza cuando
        # el resultado es `FALSE`: por eso esta restriccion acota la escala sin
        # necesidad de excluir el nulo a mano.
        CheckConstraint(
            f"rating >= {RATING_MINIMO} AND rating <= {RATING_MAXIMO}",
            name="valoracion_en_escala",
        ),
        Index("ix_book_reviews_status_published_at", "status", "published_at"),
    )
