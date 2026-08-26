"""Ciclo de vida de videos y proyectos (matriz A-01 a A-06, A-10 a A-17).

Estos dos tipos **no se despublican**: MVP_SCOPE.md seccion 3.2 reserva la
transicion `published -> draft` a articulos y reviews. Lo que se comprueba aqui,
ademas del ciclo comun, es justamente esa ausencia: A-16 y A-17.

Un solo modulo de pruebas para los dos tipos porque comparten la matriz, no la
implementacion: cada modulo de dominio sigue siendo dueno de sus reglas.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.projects.domain import (
    InvalidProjectStateError,
    ProjectPublication,
    ProjectStatus,
)
from app.modules.videos.domain import (
    InvalidVideoStateError,
    VideoPublication,
    VideoStatus,
)

PRIMERA_PUBLICACION = datetime(2026, 5, 11, 14, 0, tzinfo=UTC)
SEGUNDA_PUBLICACION = datetime(2026, 11, 3, 6, 15, tzinfo=UTC)

#: (nombre legible, clase de publicacion, enumeracion de estados, error esperado)
TIPOS = [
    pytest.param(VideoPublication, VideoStatus, InvalidVideoStateError, id="video"),
    pytest.param(ProjectPublication, ProjectStatus, InvalidProjectStateError, id="proyecto"),
]


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_nace_como_borrador_sin_fecha_de_publicacion(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    inicial = publicacion.draft()

    assert inicial.status is estados.DRAFT
    assert inicial.published_at is None


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_publicar_un_borrador_fija_la_fecha_de_publicacion(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    publicado = publicacion.draft().publish(now=PRIMERA_PUBLICACION)

    assert publicado.status is estados.PUBLISHED
    assert publicado.published_at == PRIMERA_PUBLICACION


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_publicar_exige_una_fecha_con_zona_horaria(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    ingenua = datetime(2026, 5, 11, 14, 0)

    with pytest.raises(error):
        publicacion.draft().publish(now=ingenua)


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_publicar_lo_ya_publicado_es_invalido(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    publicado = publicacion.restore(estados.PUBLISHED, PRIMERA_PUBLICACION)

    with pytest.raises(error):
        publicado.publish(now=SEGUNDA_PUBLICACION)


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_publicar_lo_archivado_es_invalido(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    archivado = publicacion.restore(estados.ARCHIVED, PRIMERA_PUBLICACION)

    with pytest.raises(error):
        archivado.publish(now=SEGUNDA_PUBLICACION)


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_archivar_un_borrador_lo_retira_sin_inventar_una_fecha(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    archivado = publicacion.draft().archive()

    assert archivado.status is estados.ARCHIVED
    assert archivado.published_at is None


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_archivar_lo_publicado_conserva_la_fecha(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    archivado = publicacion.restore(estados.PUBLISHED, PRIMERA_PUBLICACION).archive()

    assert archivado.status is estados.ARCHIVED
    assert archivado.published_at == PRIMERA_PUBLICACION


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_archivar_lo_ya_archivado_es_invalido(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    archivado = publicacion.restore(estados.ARCHIVED, PRIMERA_PUBLICACION)

    with pytest.raises(error):
        archivado.archive()


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_publicado_sin_fecha_es_irrepresentable(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    with pytest.raises(error):
        publicacion.restore(estados.PUBLISHED, None)


@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_el_estado_de_publicacion_es_inmutable(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    inicial = publicacion.draft()

    with pytest.raises(AttributeError):
        inicial.status = estados.PUBLISHED


# --- A-16, A-17 ------------------------------------------------------------
@pytest.mark.parametrize(("publicacion", "estados", "error"), TIPOS)
def test_no_existe_la_despublicacion(
    publicacion: Any, estados: Any, error: type[Exception]
) -> None:
    """MVP_SCOPE.md seccion 3.2: `published -> draft` es de articulos y reviews.

    La transicion no se prohibe con una comprobacion: **no existe**. Esta prueba
    fija ese contrato para que anadirla deje de ser un descuido posible y pase a
    ser un cambio visible.
    """
    assert not hasattr(publicacion, "unpublish")
    assert not hasattr(publicacion.draft(), "unpublish")
