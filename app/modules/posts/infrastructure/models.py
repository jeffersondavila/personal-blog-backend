"""Modelo ORM de los articulos.

Traduce a PostgreSQL el tipo `Post` de CONTENT_MODEL.md seccion 3.2. Las reglas
de transicion viven en `app.modules.posts.domain`; aqui esta lo que la **base de
datos** puede garantizar por si sola.

Reparto de invariantes
----------------------

| Invariante | Quien la garantiza |
| --- | --- |
| `slug` unico entre articulos | PostgreSQL (`UNIQUE`) |
| `status` dentro del contrato cerrado | PostgreSQL (`CHECK`) |
| `published` exige `published_at` | PostgreSQL (`CHECK`) **y** dominio |
| `draft` **puede** tener `published_at` | ninguna restriccion: es legitimo (B.8) |
| Que transiciones son validas | dominio |
| Campos minimos para publicar | `Task/012` |
| Formato del `slug` y su generacion | `Task/012` |

`content` guarda **Markdown fuente**, tal como lo escribio el autor, sin HTML
pre-renderizado (ADR-005, decision 2). El render y la sanitizacion son del
frontend (`Task/014`, `Task/015`).

`reading_time` **no se persiste**: CONTENT_MODEL.md lo describe como derivado del
contenido. Guardarlo crearia un segundo estado que queda obsoleto en cuanto se
edita el articulo. Se calcula al servir, en `Task/009`.
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
    String,
    Text,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.media.infrastructure.models import MediaAsset
from app.modules.posts.domain import PostStatus
from app.modules.tags.infrastructure.models import Tag, post_tags
from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UuidPrimaryKeyMixin
from app.shared.database.types import enum_column

LONGITUD_DE_SLUG = 160
LONGITUD_DE_TITULO = 200
LONGITUD_DE_RESUMEN = 500
#: Longitudes alineadas con lo que los buscadores muestran sin recortar.
LONGITUD_DE_TITULO_SEO = 70
LONGITUD_DE_DESCRIPCION_SEO = 160


class Post(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Articulo tecnico o personal."""

    __tablename__ = "posts"

    slug: Mapped[str] = mapped_column(String(LONGITUD_DE_SLUG), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(LONGITUD_DE_TITULO), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(LONGITUD_DE_RESUMEN))
    #: Markdown fuente. `NOT NULL` con cadena vacia por defecto: un borrador
    #: recien creado todavia no tiene cuerpo (USER_FLOWS.md B.2), y distinguir
    #: "sin contenido" de "contenido vacio" no aporta nada al render.
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[PostStatus] = mapped_column(
        enum_column(PostStatus, name="post_status"),
        nullable=False,
        default=PostStatus.DRAFT,
        server_default=PostStatus.DRAFT.value,
    )
    #: Fecha de la **primera** publicacion. Nula mientras no se haya publicado
    #: nunca, y **conservada** al despublicar.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

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
    tags: Mapped[list[Tag]] = relationship(secondary=post_tags)

    seo_title: Mapped[str | None] = mapped_column(String(LONGITUD_DE_TITULO_SEO))
    seo_description: Mapped[str | None] = mapped_column(String(LONGITUD_DE_DESCRIPCION_SEO))

    __table_args__ = (
        # Invariante 1 de CONTENT_MODEL.md. Se escribe en un solo sentido a
        # proposito: la implicacion inversa —`draft` obliga a `published_at`
        # nulo— romperia la despublicacion, que conserva la fecha (B.8).
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="publicado_exige_fecha",
        ),
        # Listado publico: `status = 'published' ORDER BY published_at DESC`
        # (USER_FLOWS.md A.2, api-contracts.md seccion 6). Requisito P-08.
        Index("ix_posts_status_published_at", "status", "published_at"),
    )
