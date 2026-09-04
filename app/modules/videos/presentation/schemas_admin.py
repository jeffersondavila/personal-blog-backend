"""Esquemas HTTP administrativos de un video (`Task/012`).

**Sin `content`, y la ausencia es el contrato.** CONTENT_MODEL.md seccion 2 y
ADR-005 decision 7: el contenido principal de un video es el video externo. Con
`extra="forbid"`, enviar `content` produce un `422` explicito en lugar de una
escritura silenciosamente ignorada — que es lo que haria un esquema permisivo, y
dejaria al panel creyendo que guardo algo.

Su imagen es `thumbnail`, no `cover` (`data-model.md` 4.7): son columnas
distintas y nombrarlas igual haria que el panel enviara la equivocada.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.media.presentation.acceso import AccesoAMedios
from app.modules.media.presentation.schemas_admin import MedioAdministrativo
from app.modules.tags.presentation.schemas import EtiquetaPublica
from app.modules.videos.application.administracion import DatosDelVideo
from app.modules.videos.domain import VideoStatus
from app.modules.videos.infrastructure.models import (
    LONGITUD_DE_DESCRIPCION_SEO,
    LONGITUD_DE_PROVEEDOR,
    LONGITUD_DE_REFERENCIA_DE_EMBED,
    LONGITUD_DE_RESUMEN,
    LONGITUD_DE_SLUG,
    LONGITUD_DE_TITULO,
    LONGITUD_DE_TITULO_SEO,
    LONGITUD_DE_URL,
    Video,
)

MAXIMO_DE_ETIQUETAS = 50

#: Longitud del texto alternativo, la de su columna (`data-model.md` 4.1).
LONGITUD_DE_TEXTO_ALTERNATIVO = 255


class VideoParaGuardar(BaseModel):
    """Cuerpo de `POST` y `PUT` sobre `/admin/videos`."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=LONGITUD_DE_TITULO)
    slug: str | None = Field(default=None, max_length=LONGITUD_DE_SLUG)
    summary: str | None = Field(default=None, max_length=LONGITUD_DE_RESUMEN)
    featured: bool = Field(default=False)
    seo_title: str | None = Field(default=None, max_length=LONGITUD_DE_TITULO_SEO)
    seo_description: str | None = Field(default=None, max_length=LONGITUD_DE_DESCRIPCION_SEO)
    thumbnail_id: uuid.UUID | None = Field(
        default=None, description="Identificador del `MediaAsset` usado como miniatura."
    )
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAXIMO_DE_ETIQUETAS)
    thumbnail_alt_text: str | None = Field(
        default=None,
        max_length=LONGITUD_DE_TEXTO_ALTERNATIVO,
        description=(
            "Texto alternativo de la miniatura (requisito A-04). Se escribe en el **primer "
            "uso** de la imagen: si el medio todavia no tiene texto, este lo fija. Si ya "
            "tiene uno distinto, la peticion se rechaza con `409`; no se sobrescribe."
        ),
    )
    provider: str | None = Field(
        default=None,
        max_length=LONGITUD_DE_PROVEEDOR,
        description=(
            "Proveedor del video. La **lista cerrada** de proveedores permitidos es de "
            "`Task/014`; aqui solo se exige que exista al publicar."
        ),
    )
    video_url: str | None = Field(default=None, max_length=LONGITUD_DE_URL)
    embed_reference: str | None = Field(default=None, max_length=LONGITUD_DE_REFERENCIA_DE_EMBED)
    duration_seconds: int | None = Field(
        default=None, gt=0, description="Duracion en segundos; `ck_videos_duracion_positiva`."
    )

    @model_validator(mode="after")
    def _el_texto_alternativo_necesita_su_imagen(self) -> Self:
        """Un texto alternativo sin imagen no describe nada.

        Se rechaza en lugar de ignorarse: un campo que no hace nada haria creer
        al panel que guardo algo. Misma postura estricta que `extra="forbid"`.
        """
        if self.thumbnail_alt_text is not None and self.thumbnail_id is None:
            raise ValueError("`thumbnail_alt_text` solo tiene sentido junto a `thumbnail_id`.")
        return self

    @field_validator("title")
    @classmethod
    def _titulo_no_en_blanco(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("El titulo no puede estar en blanco.")
        return valor.strip()

    def a_datos(self) -> DatosDelVideo:
        """Traduce el cuerpo HTTP al DTO de la capa de aplicacion."""
        return DatosDelVideo(
            title=self.title,
            slug=self.slug,
            summary=self.summary,
            featured=self.featured,
            seo_title=self.seo_title,
            seo_description=self.seo_description,
            thumbnail_id=self.thumbnail_id,
            tag_ids=tuple(self.tag_ids),
            imagen_alt_text=self.thumbnail_alt_text,
            provider=self.provider,
            video_url=self.video_url,
            embed_reference=self.embed_reference,
            duration_seconds=self.duration_seconds,
        )


class VideoAdministrativo(BaseModel):
    """Video completo tal como lo ve el panel."""

    id: uuid.UUID
    slug: str
    title: str
    summary: str | None = None
    status: VideoStatus
    published_at: datetime | None = None
    featured: bool
    seo_title: str | None = None
    seo_description: str | None = None
    thumbnail: MedioAdministrativo | None = None
    tags: list[EtiquetaPublica] = Field(default_factory=list)
    provider: str | None = None
    video_url: str | None = None
    embed_reference: str | None = None
    duration_seconds: int | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def de_modelo(cls, elemento: Video, acceso: AccesoAMedios) -> VideoAdministrativo:
        """Proyecta el modelo ORM sobre los campos administrativos."""
        return cls(
            id=elemento.id,
            slug=elemento.slug,
            title=elemento.title,
            summary=elemento.summary,
            status=elemento.status,
            published_at=elemento.published_at,
            featured=elemento.featured,
            seo_title=elemento.seo_title,
            seo_description=elemento.seo_description,
            thumbnail=MedioAdministrativo.opcional(elemento.thumbnail, acceso),
            tags=[EtiquetaPublica.de_modelo(etiqueta) for etiqueta in elemento.tags],
            provider=elemento.provider,
            video_url=elemento.video_url,
            embed_reference=elemento.embed_reference,
            duration_seconds=elemento.duration_seconds,
            created_at=elemento.created_at,
            updated_at=elemento.updated_at,
        )
