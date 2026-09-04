"""Esquemas HTTP administrativos de una review (`Task/012`).

Todo lo del articulo, mas los cuatro campos del libro. La diferencia que importa
esta en `rating`: **la valida el dominio**, no un rango escrito otra vez aqui.

Por que `rating` pasa por `Rating.of` y no por `Field(ge=1, le=5)`
------------------------------------------------------------------

`Task/008` creo `Rating` precisamente como *"puerta de entrada para datos que
vienen de fuera del proceso"*, y rechaza ademas el caso que un rango de Pydantic
dejaria pasar: `True`, que en Python es un `int` y colaria como un 1. Repetir el
rango aqui crearia una segunda definicion de la escala que puede divergir de la
del dominio y de la del `CHECK`.

La conversion ocurre en `a_datos()` —es decir, en el cuerpo del endpoint— y no
en un validador de Pydantic, para que `InvalidRatingError` llegue al manejador
de errores con **su** codigo, `invalid_rating`, en lugar de quedar envuelto en
el `validation_error` generico.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.book_reviews.application.administracion import DatosDeLaReview
from app.modules.book_reviews.domain import BookReviewStatus, Rating
from app.modules.book_reviews.infrastructure.models import (
    LONGITUD_DE_AUTOR,
    LONGITUD_DE_DESCRIPCION_SEO,
    LONGITUD_DE_RESUMEN,
    LONGITUD_DE_SLUG,
    LONGITUD_DE_TITULO,
    LONGITUD_DE_TITULO_SEO,
    LONGITUD_DE_URL,
    BookReview,
)
from app.modules.media.presentation.acceso import AccesoAMedios
from app.modules.media.presentation.schemas_admin import MedioAdministrativo
from app.modules.tags.presentation.schemas import EtiquetaPublica

MAXIMO_DE_ETIQUETAS = 50

#: Longitud del texto alternativo, la de su columna (`data-model.md` 4.1).
LONGITUD_DE_TEXTO_ALTERNATIVO = 255


class ReviewParaGuardar(BaseModel):
    """Cuerpo de `POST` y `PUT` sobre `/admin/book-reviews`.

    Solo `title` es obligatorio: libro, autor y valoracion son nulos en un
    borrador recien creado (`data-model.md` 4.6) y se exigen **al publicar**.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=LONGITUD_DE_TITULO)
    slug: str | None = Field(default=None, max_length=LONGITUD_DE_SLUG)
    summary: str | None = Field(default=None, max_length=LONGITUD_DE_RESUMEN)
    content: str = Field(default="", description="Cuerpo en Markdown **fuente**.")
    featured: bool = Field(default=False)
    seo_title: str | None = Field(default=None, max_length=LONGITUD_DE_TITULO_SEO)
    seo_description: str | None = Field(default=None, max_length=LONGITUD_DE_DESCRIPCION_SEO)
    cover_id: uuid.UUID | None = Field(default=None)
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAXIMO_DE_ETIQUETAS)
    cover_alt_text: str | None = Field(
        default=None,
        max_length=LONGITUD_DE_TEXTO_ALTERNATIVO,
        description=(
            "Texto alternativo de la portada (requisito A-04). Se escribe en el **primer "
            "uso** de la imagen: si el medio todavia no tiene texto, este lo fija. Si ya "
            "tiene uno distinto, la peticion se rechaza con `409`; no se sobrescribe."
        ),
    )
    book_title: str | None = Field(default=None, max_length=LONGITUD_DE_TITULO)
    book_author: str | None = Field(default=None, max_length=LONGITUD_DE_AUTOR)
    rating: int | None = Field(
        default=None, description="Valoracion de 1 a 5, ambos inclusive (decision D-D)."
    )
    external_link: str | None = Field(default=None, max_length=LONGITUD_DE_URL)

    @model_validator(mode="after")
    def _el_texto_alternativo_necesita_su_imagen(self) -> Self:
        """Un texto alternativo sin imagen no describe nada.

        Se rechaza en lugar de ignorarse: un campo que no hace nada haria creer
        al panel que guardo algo. Misma postura estricta que `extra="forbid"`.
        """
        if self.cover_alt_text is not None and self.cover_id is None:
            raise ValueError("`cover_alt_text` solo tiene sentido junto a `cover_id`.")
        return self

    @field_validator("title")
    @classmethod
    def _titulo_no_en_blanco(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("El titulo no puede estar en blanco.")
        return valor.strip()

    def a_datos(self) -> DatosDeLaReview:
        """Traduce el cuerpo HTTP al DTO de la capa de aplicacion."""
        return DatosDeLaReview(
            title=self.title,
            slug=self.slug,
            summary=self.summary,
            content=self.content,
            featured=self.featured,
            seo_title=self.seo_title,
            seo_description=self.seo_description,
            cover_id=self.cover_id,
            tag_ids=tuple(self.tag_ids),
            imagen_alt_text=self.cover_alt_text,
            book_title=self.book_title,
            book_author=self.book_author,
            # La escala la decide el dominio, no un rango repetido aqui.
            rating=None if self.rating is None else Rating.of(self.rating).value,
            external_link=self.external_link,
        )


class ReviewAdministrativa(BaseModel):
    """Review completa tal como la ve el panel."""

    id: uuid.UUID
    slug: str
    title: str
    summary: str | None = None
    content: str
    status: BookReviewStatus
    published_at: datetime | None = None
    featured: bool
    seo_title: str | None = None
    seo_description: str | None = None
    cover: MedioAdministrativo | None = None
    tags: list[EtiquetaPublica] = Field(default_factory=list)
    book_title: str | None = None
    book_author: str | None = None
    rating: int | None = None
    external_link: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def de_modelo(cls, review: BookReview, acceso: AccesoAMedios) -> ReviewAdministrativa:
        """Proyecta el modelo ORM sobre los campos administrativos."""
        return cls(
            id=review.id,
            slug=review.slug,
            title=review.title,
            summary=review.summary,
            content=review.content,
            status=review.status,
            published_at=review.published_at,
            featured=review.featured,
            seo_title=review.seo_title,
            seo_description=review.seo_description,
            cover=MedioAdministrativo.opcional(review.cover, acceso),
            tags=[EtiquetaPublica.de_modelo(etiqueta) for etiqueta in review.tags],
            book_title=review.book_title,
            book_author=review.book_author,
            rating=review.rating,
            external_link=review.external_link,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )
