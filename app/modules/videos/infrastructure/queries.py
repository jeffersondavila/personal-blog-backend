"""Consultas del listado publico de videos."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.filtros_publicos import FiltrosDeContenido
from app.modules.tags.infrastructure.models import Tag, video_tags
from app.modules.videos.domain import VideoStatus
from app.modules.videos.infrastructure.models import Video
from app.shared.pagination import ParametrosDePagina, clausula_de_orden

COLUMNAS_ORDENABLES = {"published_at": Video.published_at, "title": Video.title}


def _condiciones(filtros: FiltrosDeContenido) -> list[ColumnElement[bool]]:
    condiciones: list[ColumnElement[bool]] = [Video.status == VideoStatus.PUBLISHED]
    if filtros.featured is not None:
        condiciones.append(Video.featured.is_(filtros.featured))
    if filtros.tag is not None:
        ids = (
            select(video_tags.c.video_id)
            .join(Tag, Tag.id == video_tags.c.tag_id)
            .where(Tag.slug == filtros.tag)
        )
        condiciones.append(Video.id.in_(ids))
    return condiciones


def contar_videos_publicados(sesion: Session, *, filtros: FiltrosDeContenido) -> int:
    consulta = select(func.count()).select_from(Video).where(*_condiciones(filtros))
    return sesion.execute(consulta).scalar_one()


def listar_videos_publicados(
    sesion: Session,
    *,
    parametros: ParametrosDePagina,
    filtros: FiltrosDeContenido,
) -> Sequence[Video]:
    consulta = (
        select(Video)
        .where(*_condiciones(filtros))
        .options(selectinload(Video.tags), joinedload(Video.thumbnail))
        .order_by(
            *clausula_de_orden(
                sort=filtros.sort,
                columnas=COLUMNAS_ORDENABLES,
                desempate=Video.slug,
            )
        )
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).scalars().unique().all()


# ---------------------------------------------------------------------------
# Consultas administrativas (`Task/012`)
# ---------------------------------------------------------------------------


def contar_videos_administrativos(sesion: Session, *, estado: VideoStatus | None) -> int:
    """Total de videos que cumplen el filtro administrativo."""
    consulta = select(func.count()).select_from(Video)
    if estado is not None:
        consulta = consulta.where(Video.status == estado)
    return sesion.execute(consulta).scalar_one()


def listar_videos_administrativos(
    sesion: Session, *, parametros: ParametrosDePagina, estado: VideoStatus | None
) -> Sequence[Video]:
    """Pagina de videos en **cualquier** estado, para el panel (D-012-L)."""
    consulta = select(Video).options(selectinload(Video.tags), joinedload(Video.thumbnail))
    if estado is not None:
        consulta = consulta.where(Video.status == estado)
    consulta = (
        consulta.order_by(Video.updated_at.desc(), Video.slug.asc())
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).scalars().unique().all()


def obtener_video_administrativo(sesion: Session, identificador: uuid.UUID) -> Video | None:
    """Video por identificador interno, en cualquier estado (decision D-012-I)."""
    consulta = (
        select(Video)
        .where(Video.id == identificador)
        .options(selectinload(Video.tags), joinedload(Video.thumbnail))
    )
    return sesion.execute(consulta).scalars().unique().one_or_none()
