"""DTO publicos de proyectos."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.media.presentation.acceso import AccesoAMedios
from app.modules.media.presentation.schemas import MedioPublico
from app.modules.projects.domain import ProjectWorkStatus
from app.modules.projects.infrastructure.models import Project
from app.modules.tags.presentation.schemas import EtiquetaPublica
from app.shared.lectura import minutos_de_lectura


class ProyectoDeListado(BaseModel):
    slug: str
    title: str
    summary: str | None = None
    published_at: datetime | None = None
    tags: list[EtiquetaPublica] = Field(default_factory=list)
    cover: MedioPublico | None = None
    technologies: list[str] = Field(default_factory=list)
    repository_url: str | None = None
    demo_url: str | None = None
    project_status: ProjectWorkStatus

    @classmethod
    def de_modelo(cls, project: Project, acceso: AccesoAMedios) -> ProyectoDeListado:
        return cls(
            slug=project.slug,
            title=project.title,
            summary=project.summary,
            published_at=project.published_at,
            tags=[EtiquetaPublica.de_modelo(tag) for tag in project.tags],
            cover=MedioPublico.de_modelo(project.cover, acceso),
            technologies=[str(item) for item in project.technologies],
            repository_url=project.repository_url,
            demo_url=project.demo_url,
            project_status=project.project_status,
        )


class ProyectoDetallado(ProyectoDeListado):
    content: str
    reading_time_minutes: int
    seo_title: str | None = None
    seo_description: str | None = None

    @classmethod
    def de_modelo(cls, project: Project, acceso: AccesoAMedios) -> ProyectoDetallado:
        base = ProyectoDeListado.de_modelo(project, acceso)
        return cls(
            **base.model_dump(),
            content=project.content,
            reading_time_minutes=minutos_de_lectura(project.content),
            seo_title=project.seo_title,
            seo_description=project.seo_description,
        )
