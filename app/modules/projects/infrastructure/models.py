"""Modelo ORM de los proyectos.

Traduce a PostgreSQL el tipo `Project` de CONTENT_MODEL.md seccion 3.5.

Las dos columnas de estado no se mezclan:

- `status` — visibilidad publica (`draft`, `published`, `archived`).
- `project_status` — marcha del trabajo (`active`, `paused`, `completed`).

`technologies` se guarda como **`JSONB` con una lista de cadenas**, no como tabla
normalizada. Motivo: es una lista ordenada de etiquetas que solo se muestra
(USER_FLOWS.md A.7); en el MVP **nadie consulta por tecnologia** —el filtro
publico es por `Tag` (A.9)—, asi que una tabla puente anadiria una tabla, una
clave foranea y una union para algo que jamas se une. El orden se conserva sin
una columna extra. Si algun dia aparece "filtrar por tecnologia", `Tag` ya lo
cubre, y normalizar despues es una migracion sencilla.

`JSONB` es un tipo del **nucleo** de PostgreSQL, no una extension: no ata el
proyecto a ningun proveedor (requisito T-02).

A diferencia de `technologies`, los enlaces sociales del perfil **si** llevan
tabla propia: cada enlace es un registro con campos obligatorios distintos y un
orden que debe poder restringirse. La forma del dato decide la representacion,
no la costumbre.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.media.infrastructure.models import MediaAsset
from app.modules.projects.domain import ProjectStatus, ProjectWorkStatus
from app.modules.tags.infrastructure.models import Tag, project_tags
from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UuidPrimaryKeyMixin
from app.shared.database.types import enum_column

LONGITUD_DE_SLUG = 160
LONGITUD_DE_TITULO = 200
LONGITUD_DE_RESUMEN = 500
LONGITUD_DE_URL = 2048
LONGITUD_DE_TITULO_SEO = 70
LONGITUD_DE_DESCRIPCION_SEO = 160


class Project(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Proyecto o experimento de laboratorio."""

    __tablename__ = "projects"

    slug: Mapped[str] = mapped_column(String(LONGITUD_DE_SLUG), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(LONGITUD_DE_TITULO), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(LONGITUD_DE_RESUMEN))
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[ProjectStatus] = mapped_column(
        enum_column(ProjectStatus, name="project_publication_status"),
        nullable=False,
        default=ProjectStatus.DRAFT,
        server_default=ProjectStatus.DRAFT.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

    #: Estado del **trabajo**, no de la publicacion.
    project_status: Mapped[ProjectWorkStatus] = mapped_column(
        enum_column(ProjectWorkStatus, name="project_work_status"),
        nullable=False,
        default=ProjectWorkStatus.ACTIVE,
        server_default=ProjectWorkStatus.ACTIVE.value,
    )
    #: Lista ordenada de nombres de tecnologia. SQLAlchemy no detecta mutaciones
    #: en sitio de un `JSONB`: se asigna una lista nueva, no se modifica la
    #: existente.
    technologies: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    repository_url: Mapped[str | None] = mapped_column(String(LONGITUD_DE_URL))
    demo_url: Mapped[str | None] = mapped_column(String(LONGITUD_DE_URL))

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
    tags: Mapped[list[Tag]] = relationship(secondary=project_tags)

    seo_title: Mapped[str | None] = mapped_column(String(LONGITUD_DE_TITULO_SEO))
    seo_description: Mapped[str | None] = mapped_column(String(LONGITUD_DE_DESCRIPCION_SEO))

    __table_args__ = (
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="publicado_exige_fecha",
        ),
        Index("ix_projects_status_published_at", "status", "published_at"),
    )
