"""Consulta de etiquetas disponibles para contenido publico."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import Post
from app.modules.projects.domain import ProjectStatus
from app.modules.projects.infrastructure.models import Project
from app.modules.tags.infrastructure.models import (
    Tag,
    book_review_tags,
    post_tags,
    project_tags,
    video_tags,
)
from app.modules.videos.domain import VideoStatus
from app.modules.videos.infrastructure.models import Video
from app.shared.pagination import ParametrosDePagina


def _con_contenido_publicado() -> Select[tuple[Tag]]:
    post_publicado = exists(
        select(1)
        .select_from(post_tags.join(Post, Post.id == post_tags.c.post_id))
        .where(post_tags.c.tag_id == Tag.id, Post.status == PostStatus.PUBLISHED)
    )
    review_publicada = exists(
        select(1)
        .select_from(
            book_review_tags.join(
                BookReview,
                BookReview.id == book_review_tags.c.book_review_id,
            )
        )
        .where(
            book_review_tags.c.tag_id == Tag.id,
            BookReview.status == BookReviewStatus.PUBLISHED,
        )
    )
    video_publicado = exists(
        select(1)
        .select_from(video_tags.join(Video, Video.id == video_tags.c.video_id))
        .where(video_tags.c.tag_id == Tag.id, Video.status == VideoStatus.PUBLISHED)
    )
    project_publicado = exists(
        select(1)
        .select_from(project_tags.join(Project, Project.id == project_tags.c.project_id))
        .where(
            project_tags.c.tag_id == Tag.id,
            Project.status == ProjectStatus.PUBLISHED,
        )
    )
    return select(Tag).where(
        or_(post_publicado, review_publicada, video_publicado, project_publicado)
    )


def contar_etiquetas_disponibles(sesion: Session) -> int:
    disponibles = _con_contenido_publicado().subquery()
    return sesion.execute(select(func.count()).select_from(disponibles)).scalar_one()


def listar_etiquetas_disponibles(
    sesion: Session,
    *,
    parametros: ParametrosDePagina,
) -> Sequence[Tag]:
    consulta = (
        _con_contenido_publicado()
        .order_by(Tag.name.asc(), Tag.slug.asc())
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).scalars().all()
