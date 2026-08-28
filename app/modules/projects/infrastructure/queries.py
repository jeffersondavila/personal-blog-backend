"""Consultas publicas de proyectos."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.filtros_publicos import FiltrosDeContenido
from app.modules.projects.domain import ProjectStatus
from app.modules.projects.infrastructure.models import Project
from app.modules.tags.infrastructure.models import Tag, project_tags
from app.shared.pagination import ParametrosDePagina, clausula_de_orden

COLUMNAS_ORDENABLES = {"published_at": Project.published_at, "title": Project.title}


def _condiciones(filtros: FiltrosDeContenido) -> list[ColumnElement[bool]]:
    condiciones: list[ColumnElement[bool]] = [Project.status == ProjectStatus.PUBLISHED]
    if filtros.featured is not None:
        condiciones.append(Project.featured.is_(filtros.featured))
    if filtros.tag is not None:
        ids = (
            select(project_tags.c.project_id)
            .join(Tag, Tag.id == project_tags.c.tag_id)
            .where(Tag.slug == filtros.tag)
        )
        condiciones.append(Project.id.in_(ids))
    return condiciones


def contar_proyectos_publicados(sesion: Session, *, filtros: FiltrosDeContenido) -> int:
    consulta = select(func.count()).select_from(Project).where(*_condiciones(filtros))
    return sesion.execute(consulta).scalar_one()


def listar_proyectos_publicados(
    sesion: Session,
    *,
    parametros: ParametrosDePagina,
    filtros: FiltrosDeContenido,
) -> Sequence[Project]:
    consulta = (
        select(Project)
        .where(*_condiciones(filtros))
        .options(selectinload(Project.tags), joinedload(Project.cover))
        .order_by(
            *clausula_de_orden(
                sort=filtros.sort,
                columnas=COLUMNAS_ORDENABLES,
                desempate=Project.slug,
            )
        )
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).scalars().unique().all()


def obtener_proyecto_publicado(sesion: Session, *, slug: str) -> Project | None:
    consulta = (
        select(Project)
        .where(Project.status == ProjectStatus.PUBLISHED, Project.slug == slug)
        .options(selectinload(Project.tags), joinedload(Project.cover))
    )
    return sesion.execute(consulta).scalars().unique().one_or_none()
