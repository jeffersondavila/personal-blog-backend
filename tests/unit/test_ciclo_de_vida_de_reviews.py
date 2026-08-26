"""Ciclo de vida de publicacion de una review de libro (matriz A-01 a A-15).

Las reviews comparten con los articulos el derecho a despublicarse
(MVP_SCOPE.md seccion 3.2). Es una regla propia de cada tipo, no una casualidad,
y por eso se comprueba tambien aqui: si manana `Task/012` la cambiara para uno
de los dos, la suite lo diria.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.book_reviews.domain import (
    BookReviewPublication,
    BookReviewStatus,
    InvalidBookReviewStateError,
)

PRIMERA_PUBLICACION = datetime(2026, 4, 2, 9, 0, tzinfo=UTC)
SEGUNDA_PUBLICACION = datetime(2026, 10, 20, 17, 45, tzinfo=UTC)


def _publicada() -> BookReviewPublication:
    return BookReviewPublication.restore(BookReviewStatus.PUBLISHED, PRIMERA_PUBLICACION)


def _archivada() -> BookReviewPublication:
    return BookReviewPublication.restore(BookReviewStatus.ARCHIVED, PRIMERA_PUBLICACION)


def test_una_review_nace_como_borrador_sin_fecha_de_publicacion() -> None:
    publicacion = BookReviewPublication.draft()

    assert publicacion.status is BookReviewStatus.DRAFT
    assert publicacion.published_at is None


def test_publicar_un_borrador_fija_la_fecha_de_publicacion() -> None:
    publicacion = BookReviewPublication.draft().publish(now=PRIMERA_PUBLICACION)

    assert publicacion.status is BookReviewStatus.PUBLISHED
    assert publicacion.published_at == PRIMERA_PUBLICACION


def test_republicar_conserva_la_fecha_de_la_primera_publicacion() -> None:
    despublicada = BookReviewPublication.restore(BookReviewStatus.DRAFT, PRIMERA_PUBLICACION)

    republicada = despublicada.publish(now=SEGUNDA_PUBLICACION)

    assert republicada.published_at == PRIMERA_PUBLICACION


def test_publicar_exige_una_fecha_con_zona_horaria() -> None:
    ingenua = datetime(2026, 4, 2, 9, 0)

    with pytest.raises(InvalidBookReviewStateError):
        BookReviewPublication.draft().publish(now=ingenua)


def test_publicar_una_review_ya_publicada_es_invalido() -> None:
    with pytest.raises(InvalidBookReviewStateError):
        _publicada().publish(now=SEGUNDA_PUBLICACION)


def test_publicar_una_review_archivada_es_invalido() -> None:
    with pytest.raises(InvalidBookReviewStateError):
        _archivada().publish(now=SEGUNDA_PUBLICACION)


def test_despublicar_devuelve_a_borrador_y_conserva_la_fecha() -> None:
    borrador = _publicada().unpublish()

    assert borrador.status is BookReviewStatus.DRAFT
    assert borrador.published_at == PRIMERA_PUBLICACION


def test_despublicar_un_borrador_es_invalido() -> None:
    with pytest.raises(InvalidBookReviewStateError):
        BookReviewPublication.draft().unpublish()


def test_despublicar_una_review_archivada_es_invalido() -> None:
    with pytest.raises(InvalidBookReviewStateError):
        _archivada().unpublish()


def test_archivar_un_borrador_lo_retira_sin_inventar_una_fecha() -> None:
    archivada = BookReviewPublication.draft().archive()

    assert archivada.status is BookReviewStatus.ARCHIVED
    assert archivada.published_at is None


def test_archivar_una_review_publicada_conserva_la_fecha() -> None:
    archivada = _publicada().archive()

    assert archivada.status is BookReviewStatus.ARCHIVED
    assert archivada.published_at == PRIMERA_PUBLICACION


def test_archivar_una_review_ya_archivada_es_invalido() -> None:
    with pytest.raises(InvalidBookReviewStateError):
        _archivada().archive()


def test_una_review_publicada_sin_fecha_es_irrepresentable() -> None:
    with pytest.raises(InvalidBookReviewStateError):
        BookReviewPublication.restore(BookReviewStatus.PUBLISHED, None)


def test_un_borrador_previamente_publicado_es_un_estado_valido() -> None:
    publicacion = BookReviewPublication.restore(BookReviewStatus.DRAFT, PRIMERA_PUBLICACION)

    assert publicacion.status is BookReviewStatus.DRAFT
    assert publicacion.published_at == PRIMERA_PUBLICACION


def test_el_estado_de_publicacion_es_inmutable() -> None:
    publicacion = BookReviewPublication.draft()

    with pytest.raises(AttributeError):
        publicacion.status = BookReviewStatus.PUBLISHED  # type: ignore[misc]
