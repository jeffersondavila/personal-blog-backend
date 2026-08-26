"""Ciclo de vida de publicacion de un articulo (matriz A-01 a A-15).

Reglas de referencia: MVP_SCOPE.md seccion 3.2 y USER_FLOWS.md B.7 a B.9.

La regla que mas facilmente se implementa mal es la de `published_at`: es la
fecha de la **primera** publicacion y **sobrevive** a la despublicacion, asi que
un borrador puede tener fecha. Cada una de esas dos mitades tiene aqui su caso.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.posts.domain import InvalidPostStateError, PostPublication, PostStatus

PRIMERA_PUBLICACION = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
SEGUNDA_PUBLICACION = datetime(2026, 9, 15, 8, 30, tzinfo=UTC)


def _publicado() -> PostPublication:
    return PostPublication.restore(PostStatus.PUBLISHED, PRIMERA_PUBLICACION)


def _archivado() -> PostPublication:
    return PostPublication.restore(PostStatus.ARCHIVED, PRIMERA_PUBLICACION)


# --- A-01 ------------------------------------------------------------------
def test_un_articulo_nace_como_borrador_sin_fecha_de_publicacion() -> None:
    publicacion = PostPublication.draft()

    assert publicacion.status is PostStatus.DRAFT
    assert publicacion.published_at is None


# --- A-02 ------------------------------------------------------------------
def test_publicar_un_borrador_fija_la_fecha_de_publicacion() -> None:
    publicacion = PostPublication.draft().publish(now=PRIMERA_PUBLICACION)

    assert publicacion.status is PostStatus.PUBLISHED
    assert publicacion.published_at == PRIMERA_PUBLICACION


# --- A-03 ------------------------------------------------------------------
def test_republicar_conserva_la_fecha_de_la_primera_publicacion() -> None:
    """`published_at` es la fecha de la PRIMERA publicacion, no la de la ultima."""
    despublicado = PostPublication.restore(PostStatus.DRAFT, PRIMERA_PUBLICACION)

    republicado = despublicado.publish(now=SEGUNDA_PUBLICACION)

    assert republicado.status is PostStatus.PUBLISHED
    assert republicado.published_at == PRIMERA_PUBLICACION


# --- A-04 ------------------------------------------------------------------
def test_publicar_exige_una_fecha_con_zona_horaria() -> None:
    """Toda fecha se almacena en UTC (CONTENT_MODEL.md, invariante 10).

    Una fecha ingenua no dice en que instante ocurrio la publicacion.
    """
    ingenua = datetime(2026, 3, 1, 12, 0)  # sin zona horaria a proposito

    with pytest.raises(InvalidPostStateError):
        PostPublication.draft().publish(now=ingenua)


# --- A-05 ------------------------------------------------------------------
def test_publicar_un_articulo_ya_publicado_es_invalido() -> None:
    with pytest.raises(InvalidPostStateError):
        _publicado().publish(now=SEGUNDA_PUBLICACION)


# --- A-06 ------------------------------------------------------------------
def test_publicar_un_articulo_archivado_es_invalido() -> None:
    """Restaurar desde `archived` no pertenece al MVP (MVP_SCOPE.md seccion 3.2)."""
    with pytest.raises(InvalidPostStateError):
        _archivado().publish(now=SEGUNDA_PUBLICACION)


# --- A-07 ------------------------------------------------------------------
def test_despublicar_devuelve_a_borrador_y_conserva_la_fecha() -> None:
    """USER_FLOWS.md B.8: se conserva `published_at` como referencia historica."""
    borrador = _publicado().unpublish()

    assert borrador.status is PostStatus.DRAFT
    assert borrador.published_at == PRIMERA_PUBLICACION


# --- A-08 ------------------------------------------------------------------
def test_despublicar_un_borrador_es_invalido() -> None:
    with pytest.raises(InvalidPostStateError):
        PostPublication.draft().unpublish()


# --- A-09 ------------------------------------------------------------------
def test_despublicar_un_articulo_archivado_es_invalido() -> None:
    with pytest.raises(InvalidPostStateError):
        _archivado().unpublish()


# --- A-10 ------------------------------------------------------------------
def test_archivar_un_borrador_lo_retira_sin_inventar_una_fecha() -> None:
    archivado = PostPublication.draft().archive()

    assert archivado.status is PostStatus.ARCHIVED
    assert archivado.published_at is None


# --- A-11 ------------------------------------------------------------------
def test_archivar_un_articulo_publicado_conserva_la_fecha() -> None:
    archivado = _publicado().archive()

    assert archivado.status is PostStatus.ARCHIVED
    assert archivado.published_at == PRIMERA_PUBLICACION


# --- A-12 ------------------------------------------------------------------
def test_archivar_un_articulo_ya_archivado_es_invalido() -> None:
    with pytest.raises(InvalidPostStateError):
        _archivado().archive()


# --- A-13 ------------------------------------------------------------------
def test_un_articulo_publicado_sin_fecha_es_irrepresentable() -> None:
    """CONTENT_MODEL.md, invariante 1: un contenido `published` debe tener fecha."""
    with pytest.raises(InvalidPostStateError):
        PostPublication.restore(PostStatus.PUBLISHED, None)


# --- A-14 ------------------------------------------------------------------
def test_un_borrador_previamente_publicado_es_un_estado_valido() -> None:
    """La otra mitad de la reconciliacion: `draft` CON fecha es legitimo."""
    publicacion = PostPublication.restore(PostStatus.DRAFT, PRIMERA_PUBLICACION)

    assert publicacion.status is PostStatus.DRAFT
    assert publicacion.published_at == PRIMERA_PUBLICACION


# --- A-15 ------------------------------------------------------------------
def test_el_estado_de_publicacion_es_inmutable() -> None:
    """Cada transicion devuelve una instancia nueva; nadie muta el estado en sitio."""
    publicacion = PostPublication.draft()

    with pytest.raises(AttributeError):
        publicacion.status = PostStatus.PUBLISHED  # type: ignore[misc]
