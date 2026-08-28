"""Busqueda publica transversal sobre PostgreSQL."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, literal, or_, select, union_all
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import Post
from app.modules.projects.domain import ProjectStatus
from app.modules.projects.infrastructure.models import Project
from app.modules.search.tipos import TipoDeContenido
from app.modules.videos.domain import VideoStatus
from app.modules.videos.infrastructure.models import Video
from app.shared.pagination import ParametrosDePagina


def patron_de_busqueda(termino: str) -> str:
    """Convierte texto literal en un patron ILIKE con escape explicito."""
    escapado = termino.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


def _rama(
    *,
    modelo: Any,
    tipo: TipoDeContenido,
    estado_publicado: Any,
    patron: str,
    campos_adicionales: Sequence[Any] = (),
) -> Select[Any]:
    campos = [modelo.title, modelo.summary, *campos_adicionales]
    coincidencia = or_(*(campo.ilike(patron, escape="\\") for campo in campos))
    return select(
        literal(tipo.value).label("type"),
        modelo.slug.label("slug"),
        modelo.title.label("title"),
        modelo.summary.label("summary"),
        modelo.published_at.label("published_at"),
    ).where(modelo.status == estado_publicado, coincidencia)


def _union_de_resultados(patron: str) -> Any:
    return union_all(
        _rama(
            modelo=Post,
            tipo=TipoDeContenido.POST,
            estado_publicado=PostStatus.PUBLISHED,
            patron=patron,
        ),
        _rama(
            modelo=BookReview,
            tipo=TipoDeContenido.BOOK_REVIEW,
            estado_publicado=BookReviewStatus.PUBLISHED,
            patron=patron,
            campos_adicionales=(BookReview.book_title, BookReview.book_author),
        ),
        _rama(
            modelo=Video,
            tipo=TipoDeContenido.VIDEO,
            estado_publicado=VideoStatus.PUBLISHED,
            patron=patron,
        ),
        _rama(
            modelo=Project,
            tipo=TipoDeContenido.PROJECT,
            estado_publicado=ProjectStatus.PUBLISHED,
            patron=patron,
        ),
    ).subquery("resultados_publicos")


def contar_resultados(sesion: Session, *, termino: str) -> int:
    resultados = _union_de_resultados(patron_de_busqueda(termino))
    return sesion.execute(select(func.count()).select_from(resultados)).scalar_one()


def buscar(
    sesion: Session,
    *,
    termino: str,
    parametros: ParametrosDePagina,
) -> Sequence[RowMapping]:
    resultados = _union_de_resultados(patron_de_busqueda(termino))
    consulta = (
        select(resultados)
        .order_by(
            resultados.c.published_at.desc(),
            resultados.c.type.asc(),
            resultados.c.slug.asc(),
        )
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).mappings().all()
