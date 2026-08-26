"""Escala de valoracion de una review (matriz B-01 a B-09).

`Task/008` cierra la escala que CONTENT_MODEL.md dejaba abierta: **entero de 1 a
5, ambos inclusive**. Los dos extremos se comprueban explicitamente porque son
justo los valores que una comparacion mal escrita (`<` en lugar de `<=`)
rechazaria en silencio.
"""

from __future__ import annotations

import pytest

from app.modules.book_reviews.domain import (
    RATING_MAXIMO,
    RATING_MINIMO,
    InvalidRatingError,
    Rating,
)


def test_la_escala_declarada_es_de_uno_a_cinco() -> None:
    assert (RATING_MINIMO, RATING_MAXIMO) == (1, 5)


# --- B-01, B-02, B-03 ------------------------------------------------------
@pytest.mark.parametrize("valor", [1, 2, 3, 4, 5])
def test_los_valores_de_la_escala_se_aceptan(valor: int) -> None:
    assert Rating.of(valor).value == valor


# --- B-04, B-05, B-06 ------------------------------------------------------
@pytest.mark.parametrize("valor", [0, -1, 6, 10])
def test_los_valores_fuera_de_la_escala_se_rechazan(valor: int) -> None:
    with pytest.raises(InvalidRatingError):
        Rating.of(valor)


# --- B-07 ------------------------------------------------------------------
@pytest.mark.parametrize("valor", [3.5, "4", None, [4]])
def test_una_valoracion_que_no_es_entera_se_rechaza(valor: object) -> None:
    with pytest.raises(InvalidRatingError):
        Rating.of(valor)


# --- B-08 ------------------------------------------------------------------
def test_un_booleano_no_es_una_valoracion() -> None:
    """`True` es un `int` para Python y valdria 1: la escala no lo admite."""
    with pytest.raises(InvalidRatingError):
        Rating.of(True)


# --- B-09 ------------------------------------------------------------------
def test_la_valoracion_es_inmutable() -> None:
    valoracion = Rating.of(4)

    with pytest.raises(AttributeError):
        valoracion.value = 5  # type: ignore[misc]
