"""Modelo ORM de los videos externos.

Traduce a PostgreSQL el tipo `Video` de CONTENT_MODEL.md seccion 3.4.

**El sistema nunca aloja archivos de video.** Se guardan URL, proveedor,
referencia de incrustacion y metadatos. No hay columna binaria, ni `content` en
Markdown: el contenido principal de un video es el video, no un texto
(ADR-005, decision 7).

`provider` es una cadena libre a este nivel. La **lista cerrada de proveedores
permitidos** —la que acota los `embed` por seguridad— se fija en `Task/014`;
congelarla hoy en un `CHECK` obligaria a migrar el esquema para tomar una
decision que corresponde a otra tarea.

Que puede exigir el esquema al crear
------------------------------------

**Solo `title` y `slug`.** Un video se crea desde el panel como cualquier otro
contenido: USER_FLOWS.md B.2 no distingue por tipo. La URL y el proveedor se
pegan despues, editando (B.3), asi que `provider` y `video_url` **admiten nulo**.
Exigirlos al crear obligaria a inventar una direccion que todavia no se conoce.

Que un video **publicado** deba tener URL y proveedor es una validacion de
**publicacion** (B.7) y pertenece a `Task/012`. Regresion:
`tests/integration/test_borrador_minimo.py`.

`duration_seconds` guarda enteros y no un `INTERVAL`: la duracion de un video es
un numero de segundos en todas las APIs de los proveedores, y un entero cruza sin
traduccion la frontera con JSON.

**No hay `thumbnail_url`.** CONTENT_MODEL.md admite miniatura propia "o URL del
proveedor"; la del proveedor se deriva de `provider` mas `embed_reference` al
renderizar (`Task/014`), asi que persistirla duplicaria estado derivable —el
mismo criterio que deja fuera `reading_time`—.
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
    Integer,
    String,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.media.infrastructure.models import MediaAsset
from app.modules.tags.infrastructure.models import Tag, video_tags
from app.modules.videos.domain import VideoStatus
from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UuidPrimaryKeyMixin
from app.shared.database.types import enum_column

LONGITUD_DE_SLUG = 160
LONGITUD_DE_TITULO = 200
LONGITUD_DE_RESUMEN = 500
LONGITUD_DE_PROVEEDOR = 32
LONGITUD_DE_URL = 2048
LONGITUD_DE_REFERENCIA_DE_EMBED = 255
LONGITUD_DE_TITULO_SEO = 70
LONGITUD_DE_DESCRIPCION_SEO = 160


class Video(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Referencia a un video alojado externamente."""

    __tablename__ = "videos"

    slug: Mapped[str] = mapped_column(String(LONGITUD_DE_SLUG), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(LONGITUD_DE_TITULO), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(LONGITUD_DE_RESUMEN))
    status: Mapped[VideoStatus] = mapped_column(
        enum_column(VideoStatus, name="video_status"),
        nullable=False,
        default=VideoStatus.DRAFT,
        server_default=VideoStatus.DRAFT.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

    #: Nulos mientras el borrador no los tenga: en B.2 todavia no se conocen.
    provider: Mapped[str | None] = mapped_column(String(LONGITUD_DE_PROVEEDOR))
    video_url: Mapped[str | None] = mapped_column(String(LONGITUD_DE_URL))
    embed_reference: Mapped[str | None] = mapped_column(String(LONGITUD_DE_REFERENCIA_DE_EMBED))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    #: Miniatura propia. `ON DELETE RESTRICT`, como el resto de referencias a
    #: medios: un medio en uso no se borra (invariante 5 de CONTENT_MODEL.md).
    thumbnail_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="RESTRICT"), index=True
    )
    thumbnail: Mapped[MediaAsset | None] = relationship()

    #: Relacion unidireccional: el contenido conoce sus etiquetas.
    #: `Tag` no expone la lista inversa porque en el MVP nadie la pide;
    #: el filtro publico por etiqueta se resuelve con una consulta.
    tags: Mapped[list[Tag]] = relationship(secondary=video_tags)

    seo_title: Mapped[str | None] = mapped_column(String(LONGITUD_DE_TITULO_SEO))
    seo_description: Mapped[str | None] = mapped_column(String(LONGITUD_DE_DESCRIPCION_SEO))

    __table_args__ = (
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="publicado_exige_fecha",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds > 0",
            name="duracion_positiva",
        ),
        Index("ix_videos_status_published_at", "status", "published_at"),
    )
