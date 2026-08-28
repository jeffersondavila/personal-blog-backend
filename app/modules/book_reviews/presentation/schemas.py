"""DTO publicos de reviews de libros."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.media.presentation.schemas import MedioPublico
from app.modules.tags.presentation.schemas import EtiquetaPublica
from app.shared.lectura import minutos_de_lectura


class ReviewDeListado(BaseModel):
    slug: str
    title: str
    summary: str | None = None
    published_at: datetime | None = None
    tags: list[EtiquetaPublica] = Field(default_factory=list)
    cover: MedioPublico | None = None
    book_title: str | None = None
    book_author: str | None = None
    rating: int | None = None

    @classmethod
    def de_modelo(cls, review: BookReview) -> ReviewDeListado:
        return cls(
            slug=review.slug,
            title=review.title,
            summary=review.summary,
            published_at=review.published_at,
            tags=[EtiquetaPublica.de_modelo(tag) for tag in review.tags],
            cover=MedioPublico.de_modelo(review.cover),
            book_title=review.book_title,
            book_author=review.book_author,
            rating=review.rating,
        )


class ReviewDetallada(ReviewDeListado):
    content: str
    reading_time_minutes: int
    external_link: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None

    @classmethod
    def de_modelo(cls, review: BookReview) -> ReviewDetallada:
        base = ReviewDeListado.de_modelo(review)
        return cls(
            **base.model_dump(),
            content=review.content,
            reading_time_minutes=minutos_de_lectura(review.content),
            external_link=review.external_link,
            seo_title=review.seo_title,
            seo_description=review.seo_description,
        )
