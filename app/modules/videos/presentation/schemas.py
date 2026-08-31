"""DTO del listado publico de videos."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.media.presentation.acceso import AccesoAMedios
from app.modules.media.presentation.schemas import MedioPublico
from app.modules.tags.presentation.schemas import EtiquetaPublica
from app.modules.videos.infrastructure.models import Video


class VideoDeListado(BaseModel):
    slug: str
    title: str
    summary: str | None = None
    published_at: datetime | None = None
    tags: list[EtiquetaPublica] = Field(default_factory=list)
    thumbnail: MedioPublico | None = None
    provider: str | None = None
    video_url: str | None = None
    embed_reference: str | None = None
    duration_seconds: int | None = None

    @classmethod
    def de_modelo(cls, video: Video, acceso: AccesoAMedios) -> VideoDeListado:
        return cls(
            slug=video.slug,
            title=video.title,
            summary=video.summary,
            published_at=video.published_at,
            tags=[EtiquetaPublica.de_modelo(tag) for tag in video.tags],
            thumbnail=MedioPublico.de_modelo(video.thumbnail, acceso),
            provider=video.provider,
            video_url=video.video_url,
            embed_reference=video.embed_reference,
            duration_seconds=video.duration_seconds,
        )
