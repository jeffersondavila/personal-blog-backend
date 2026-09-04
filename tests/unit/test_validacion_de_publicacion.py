"""Campos minimos para publicar (`Task/012`, invariante 18 de data-model.md).

`Task/008` dejo esto **explicitamente** abierto: el esquema tiene que poder
*representar* un borrador incompleto —USER_FLOWS.md B.2 solo exige el titulo—, y
*"impedir que se publique asi es otra capa"* (`data-model.md` seccion 4.4.1). Esa
capa es esta.

La fuente del contenido de la regla es USER_FLOWS.md B.7:

> *Se validan los campos minimos (titulo, slug, contenido, y SEO si corresponde).*

**"SEO si corresponde" no significa exigir los campos SEO**, que contradiria los
*fallbacks* de CONTENT_MODEL.md seccion 2 —`seo_title` cae en `title`,
`seo_description` cae en `summary`—. Significa que la descripcion SEO **se pueda
resolver**: o hay `seo_description`, o hay `summary`. Tabla completa por entidad
y campo en la ficha de la tarea, seccion 7.0.3.

Es dominio puro: Python plano, sin FastAPI ni SQLAlchemy.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.modules.book_reviews.domain.publicacion import (
    ReviewPublicable,
    campos_que_faltan_en_la_review,
)
from app.modules.posts.domain.publicacion import (
    ArticuloPublicable,
    campos_que_faltan_en_el_articulo,
)
from app.modules.projects.domain.publicacion import (
    ProyectoPublicable,
    campos_que_faltan_en_el_proyecto,
)
from app.modules.videos.domain.publicacion import VideoPublicable, campos_que_faltan_en_el_video
from app.shared.errors.exceptions import ConflictError


def _articulo(**cambios: object) -> ArticuloPublicable:
    valores: dict[str, object] = {
        "title": "Un titulo",
        "slug": "un-titulo",
        "content": "Cuerpo en Markdown.",
        "summary": "Un resumen.",
        "seo_description": None,
    }
    valores.update(cambios)
    return ArticuloPublicable(**valores)  # type: ignore[arg-type]


def _review(**cambios: object) -> ReviewPublicable:
    valores: dict[str, object] = {
        "title": "Una review",
        "slug": "una-review",
        "content": "Cuerpo en Markdown.",
        "summary": "Un resumen.",
        "seo_description": None,
        "book_title": "El libro",
        "book_author": "La autora",
        "rating": 4,
    }
    valores.update(cambios)
    return ReviewPublicable(**valores)  # type: ignore[arg-type]


def _video(**cambios: object) -> VideoPublicable:
    valores: dict[str, object] = {
        "title": "Un video",
        "slug": "un-video",
        "summary": "Un resumen.",
        "seo_description": None,
        "provider": "youtube",
        "video_url": "https://example.invalid/v/1",
    }
    valores.update(cambios)
    return VideoPublicable(**valores)  # type: ignore[arg-type]


def _proyecto(**cambios: object) -> ProyectoPublicable:
    valores: dict[str, object] = {
        "title": "Un proyecto",
        "slug": "un-proyecto",
        "content": "Cuerpo en Markdown.",
        "summary": "Un resumen.",
        "seo_description": None,
    }
    valores.update(cambios)
    return ProyectoPublicable(**valores)  # type: ignore[arg-type]


# --- Camino feliz: un borrador completo no tiene nada que reprochar --------
def test_un_articulo_completo_puede_publicarse() -> None:
    assert campos_que_faltan_en_el_articulo(_articulo()) == []


def test_una_review_completa_puede_publicarse() -> None:
    assert campos_que_faltan_en_la_review(_review()) == []


def test_un_video_completo_puede_publicarse() -> None:
    assert campos_que_faltan_en_el_video(_video()) == []


def test_un_proyecto_completo_puede_publicarse() -> None:
    assert campos_que_faltan_en_el_proyecto(_proyecto()) == []


# --- Reglas comunes a los cuatro ------------------------------------------
@pytest.mark.parametrize("vacio", ["", "   "])
def test_no_se_puede_publicar_un_articulo_sin_titulo(vacio: str) -> None:
    assert campos_que_faltan_en_el_articulo(_articulo(title=vacio)) == ["title"]


def test_no_se_puede_publicar_un_articulo_sin_contenido() -> None:
    """B.7 exige *contenido*, y el de un articulo es su Markdown."""
    assert campos_que_faltan_en_el_articulo(_articulo(content="")) == ["content"]


def test_un_contenido_de_solo_espacios_cuenta_como_ausente() -> None:
    assert campos_que_faltan_en_el_articulo(_articulo(content="   \n  ")) == ["content"]


def test_no_se_puede_publicar_sin_descripcion_seo_resoluble() -> None:
    """Ni `summary` ni `seo_description`: la descripcion SEO no se puede resolver."""
    assert campos_que_faltan_en_el_articulo(_articulo(summary=None, seo_description=None)) == [
        "summary"
    ]


def test_el_seo_description_hace_prescindible_el_resumen() -> None:
    """Es el *fallback* de CONTENT_MODEL.md seccion 2, leido al derecho."""
    completo = _articulo(summary=None, seo_description="Una descripcion para buscadores.")

    assert campos_que_faltan_en_el_articulo(completo) == []


def test_el_resumen_hace_prescindible_el_seo_description() -> None:
    assert campos_que_faltan_en_el_articulo(_articulo(seo_description=None)) == []


def test_faltan_varios_campos_y_se_devuelven_todos() -> None:
    """El administrador no debe descubrirlos de uno en uno."""
    incompleto = _articulo(content="", summary=None, seo_description=None)

    assert campos_que_faltan_en_el_articulo(incompleto) == ["content", "summary"]


# --- Reglas propias de la review ------------------------------------------
def test_no_se_puede_publicar_una_review_sin_valoracion() -> None:
    """CONTENT_MODEL.md 3.3: exigir `rating` **para publicar** es de `Task/012`."""
    assert campos_que_faltan_en_la_review(_review(rating=None)) == ["rating"]


def test_no_se_puede_publicar_una_review_sin_libro_ni_autor() -> None:
    """A.4 y A.5 muestran ambos en el sitio publico."""
    faltantes = campos_que_faltan_en_la_review(_review(book_title=None, book_author=None))

    assert faltantes == ["book_title", "book_author"]


def test_el_enlace_externo_de_la_review_sigue_siendo_opcional() -> None:
    """CONTENT_MODEL.md 3.3: *"enlace opcional"*; A.5: *"si existe"*."""
    assert campos_que_faltan_en_la_review(_review()) == []


# --- Reglas propias del video ---------------------------------------------
def test_no_se_puede_publicar_un_video_sin_url() -> None:
    """Es el equivalente de "contenido" para un tipo que no tiene Markdown."""
    assert campos_que_faltan_en_el_video(_video(video_url=None)) == ["video_url"]


def test_no_se_puede_publicar_un_video_sin_proveedor() -> None:
    """CONTENT_MODEL.md 3.4: *"solo se almacenan URL, **proveedor** y metadatos"*."""
    assert campos_que_faltan_en_el_video(_video(provider=None)) == ["provider"]


def test_del_video_solo_se_exige_que_el_proveedor_exista() -> None:
    """La **lista cerrada** de proveedores permitidos es de `Task/014`.

    Rechazar aqui un proveedor por no estar en una lista seria adelantar una
    decision que ninguna fuente vigente ha tomado, y `data-model.md` seccion 4.7
    deja la columna deliberadamente **sin `CHECK`** por esa misma razon.
    """
    assert campos_que_faltan_en_el_video(_video(provider="un-proveedor-cualquiera")) == []


def test_el_video_no_exige_referencia_de_embed_ni_duracion() -> None:
    assert campos_que_faltan_en_el_video(_video()) == []


# --- Reglas propias del proyecto ------------------------------------------
def test_no_se_puede_publicar_un_proyecto_sin_contenido() -> None:
    assert campos_que_faltan_en_el_proyecto(_proyecto(content="")) == ["content"]


def test_el_proyecto_no_exige_repositorio_ni_demo_ni_tecnologias() -> None:
    """CONTENT_MODEL.md 3.5 los declara opcionales y D-G describe la lista."""
    assert campos_que_faltan_en_el_proyecto(_proyecto()) == []


# --- Las reglas comunes, comprobadas en los CUATRO ------------------------
#
# Cada tipo tiene su propia funcion de validacion —es la postura de `D-P`: no
# hay base compartida—, asi que "funciona en articulos" no dice nada sobre los
# otros tres. Estas dos tablas recorren los cuatro.
_Constructor = Callable[..., Any]
_Validador = Callable[[Any], list[str]]

_COMPLETOS: dict[str, tuple[_Constructor, _Validador]] = {
    "articulo": (_articulo, campos_que_faltan_en_el_articulo),
    "review": (_review, campos_que_faltan_en_la_review),
    "video": (_video, campos_que_faltan_en_el_video),
    "proyecto": (_proyecto, campos_que_faltan_en_el_proyecto),
}


@pytest.mark.parametrize("tipo", sorted(_COMPLETOS), ids=sorted(_COMPLETOS))
def test_ningun_tipo_se_publica_sin_titulo(tipo: str) -> None:
    construir, faltantes = _COMPLETOS[tipo]

    assert "title" in faltantes(construir(title="   "))


@pytest.mark.parametrize("tipo", sorted(_COMPLETOS), ids=sorted(_COMPLETOS))
def test_ningun_tipo_se_publica_sin_slug(tipo: str) -> None:
    """El slug no puede faltar al publicar: **es** la URL publica del contenido.

    En la practica siempre existe —la creacion lo propone del titulo (B.2)—,
    pero la regla se comprueba igualmente: quien decide que un contenido es
    publicable no debe **suponer** que otra capa ya lo garantizo.
    """
    construir, faltantes = _COMPLETOS[tipo]

    assert "slug" in faltantes(construir(slug=""))


@pytest.mark.parametrize("tipo", sorted(_COMPLETOS), ids=sorted(_COMPLETOS))
def test_ningun_tipo_se_publica_sin_descripcion_resoluble(tipo: str) -> None:
    construir, faltantes = _COMPLETOS[tipo]

    assert "summary" in faltantes(construir(summary=None, seo_description=None))


@pytest.mark.parametrize("tipo", sorted(_COMPLETOS), ids=sorted(_COMPLETOS))
def test_en_los_cuatro_el_seo_description_sustituye_al_resumen(tipo: str) -> None:
    construir, faltantes = _COMPLETOS[tipo]

    assert faltantes(construir(summary=None, seo_description="Una descripcion.")) == []


# --- Texto alternativo de la imagen, en los cuatro ------------------------
#
# La obligacion no la crea `Task/012`: se la asignan `data-model.md` 4.1
# —*"Exigirlo donde se usa es de `Task/012` y `Task/014`"*— y la decision
# **D-010-N** de `Task/010`. Aqui esta el "donde se usa" que le toca al dominio.
_CAMPO_DE_LA_IMAGEN = {
    "articulo": "cover_alt_text",
    "review": "cover_alt_text",
    "video": "thumbnail_alt_text",
    "proyecto": "cover_alt_text",
}


@pytest.mark.parametrize("tipo", sorted(_COMPLETOS), ids=sorted(_COMPLETOS))
def test_ningun_tipo_se_publica_con_una_imagen_sin_texto_alternativo(tipo: str) -> None:
    """Requisito A-04. La imagen pasa a tener lectores justo al publicar."""
    construir, faltantes = _COMPLETOS[tipo]

    resultado = faltantes(construir(tiene_imagen=True, imagen_alt_text=None))

    assert _CAMPO_DE_LA_IMAGEN[tipo] in resultado


@pytest.mark.parametrize("tipo", sorted(_COMPLETOS), ids=sorted(_COMPLETOS))
def test_un_texto_alternativo_en_blanco_no_describe_nada(tipo: str) -> None:
    """Para un lector de pantalla, `"   "` y la ausencia son lo mismo."""
    construir, faltantes = _COMPLETOS[tipo]

    resultado = faltantes(construir(tiene_imagen=True, imagen_alt_text="   "))

    assert _CAMPO_DE_LA_IMAGEN[tipo] in resultado


@pytest.mark.parametrize("tipo", sorted(_COMPLETOS), ids=sorted(_COMPLETOS))
def test_con_texto_alternativo_la_imagen_no_impide_publicar(tipo: str) -> None:
    construir, faltantes = _COMPLETOS[tipo]

    assert faltantes(construir(tiene_imagen=True, imagen_alt_text="Un retrato")) == []


@pytest.mark.parametrize("tipo", sorted(_COMPLETOS), ids=sorted(_COMPLETOS))
def test_sin_imagen_no_se_exige_texto_alternativo(tipo: str) -> None:
    """La portada nunca ha sido obligatoria: ninguna fuente la exige."""
    construir, faltantes = _COMPLETOS[tipo]

    assert faltantes(construir(tiene_imagen=False, imagen_alt_text=None)) == []


# --- El error que produce el rechazo --------------------------------------
def test_el_rechazo_es_un_conflicto_y_enumera_los_campos() -> None:
    """D-012-H: `409`, porque lo que falla es el **estado del recurso**.

    La peticion de publicar esta bien formada y vacia; lo que no se puede es la
    operacion sobre el contenido tal como esta. api-contracts.md seccion 8
    reserva `409` para el conflicto de estado.
    """
    from app.modules.posts.domain.publicacion import ArticuloIncompletoError

    error = ArticuloIncompletoError(campos=["content", "summary"])

    assert issubclass(ArticuloIncompletoError, ConflictError)
    assert error.status_code == 409
    assert error.code == "cannot_publish_incomplete_draft"
    assert error.details == {"campos": ["content", "summary"]}


def test_los_cuatro_tipos_comparten_el_codigo_del_rechazo() -> None:
    """El cliente reacciona igual en los cuatro: mostrar lo que falta.

    Los codigos de transicion invalida **si** son distintos por tipo
    (`invalid_post_state`, `invalid_video_state`…), porque los estados de cada
    tipo son distintos. Aqui el hecho es el mismo, asi que el codigo tambien.
    """
    from app.modules.book_reviews.domain.publicacion import ReviewIncompletaError
    from app.modules.posts.domain.publicacion import ArticuloIncompletoError
    from app.modules.projects.domain.publicacion import ProyectoIncompletoError
    from app.modules.videos.domain.publicacion import VideoIncompletoError

    codigos = {
        ArticuloIncompletoError.code,
        ReviewIncompletaError.code,
        VideoIncompletoError.code,
        ProyectoIncompletoError.code,
    }

    assert codigos == {"cannot_publish_incomplete_draft"}
