"""Consultas publicas de reviews de libros."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.filtros_publicos import FiltrosDeContenido
from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.tags.infrastructure.models import Tag, book_review_tags
from app.shared.pagination import ParametrosDePagina, clausula_de_orden

COLUMNAS_ORDENABLES = {
    "published_at": BookReview.published_at,
    "title": BookReview.title,
}


def _condiciones(filtros: FiltrosDeContenido) -> list[ColumnElement[bool]]:
    condiciones: list[ColumnElement[bool]] = [BookReview.status == BookReviewStatus.PUBLISHED]
    if filtros.featured is not None:
        condiciones.append(BookReview.featured.is_(filtros.featured))
    if filtros.tag is not None:
        ids = (
            select(book_review_tags.c.book_review_id)
            .join(Tag, Tag.id == book_review_tags.c.tag_id)
            .where(Tag.slug == filtros.tag)
        )
        condiciones.append(BookReview.id.in_(ids))
    return condiciones


def contar_reviews_publicadas(sesion: Session, *, filtros: FiltrosDeContenido) -> int:
    consulta = select(func.count()).select_from(BookReview).where(*_condiciones(filtros))
    return sesion.execute(consulta).scalar_one()


def listar_reviews_publicadas(
    sesion: Session,
    *,
    parametros: ParametrosDePagina,
    filtros: FiltrosDeContenido,
) -> Sequence[BookReview]:
    consulta = (
        select(BookReview)
        .where(*_condiciones(filtros))
        .options(selectinload(BookReview.tags), joinedload(BookReview.cover))
        .order_by(
            *clausula_de_orden(
                sort=filtros.sort,
                columnas=COLUMNAS_ORDENABLES,
                desempate=BookReview.slug,
            )
        )
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).scalars().unique().all()


def obtener_review_publicada(sesion: Session, *, slug: str) -> BookReview | None:
    consulta = (
        select(BookReview)
        .where(BookReview.status == BookReviewStatus.PUBLISHED, BookReview.slug == slug)
        .options(selectinload(BookReview.tags), joinedload(BookReview.cover))
    )
    return sesion.execute(consulta).scalars().unique().one_or_none()


# ---------------------------------------------------------------------------
# Consultas administrativas (`Task/012`)
# ---------------------------------------------------------------------------
#
# Sin filtro de estado obligatorio —el panel ve borradores y archivados— y con
# el orden administrativo: `updated_at` descendente, desempate por `slug`
# (decision D-012-L).


def contar_reviews_administrativas(sesion: Session, *, estado: BookReviewStatus | None) -> int:
    """Total de reviews que cumplen el filtro administrativo."""
    consulta = select(func.count()).select_from(BookReview)
    if estado is not None:
        consulta = consulta.where(BookReview.status == estado)
    return sesion.execute(consulta).scalar_one()


def listar_reviews_administrativas(
    sesion: Session, *, parametros: ParametrosDePagina, estado: BookReviewStatus | None
) -> Sequence[BookReview]:
    """Pagina de reviews en **cualquier** estado, para el panel."""
    consulta = select(BookReview).options(
        selectinload(BookReview.tags), joinedload(BookReview.cover)
    )
    if estado is not None:
        consulta = consulta.where(BookReview.status == estado)
    consulta = (
        consulta.order_by(BookReview.updated_at.desc(), BookReview.slug.asc())
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).scalars().unique().all()


def obtener_review_administrativa(sesion: Session, identificador: uuid.UUID) -> BookReview | None:
    """Review por identificador interno, en cualquier estado (decision D-012-I)."""
    consulta = (
        select(BookReview)
        .where(BookReview.id == identificador)
        .options(selectinload(BookReview.tags), joinedload(BookReview.cover))
    )
    return sesion.execute(consulta).scalars().unique().one_or_none()
