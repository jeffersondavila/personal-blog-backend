"""Formato y generacion del `slug` (`Task/012`, decisiones D-012-E a D-012-G).

`data-model.md` seccion 6, invariante 8, asigna a esta tarea *"el formato y la
generacion del slug"*, y su seccion 10 lo registra como deuda 7. La fuente del
comportamiento es USER_FLOWS.md B.2:

> *Introduce titulo; el **slug se propone automaticamente** y es editable.*

Estas pruebas fijan las tres piezas de esa frase: que se propone desde el titulo,
que lo propuesto es un identificador utilizable en una URL, y que un slug escrito
a mano se **valida** en lugar de reescribirse en silencio.
"""

from __future__ import annotations

import pytest

from app.shared.slug import (
    LONGITUD_MAXIMA_DE_SLUG,
    SlugInvalidoError,
    derivar_slug,
    resolver_slug,
    validar_slug,
)


# --- SL-01, SL-02: derivacion desde el titulo ------------------------------
@pytest.mark.parametrize(
    ("titulo", "esperado"),
    [
        ("Docker en Produccion", "docker-en-produccion"),
        ("Docker en Producción", "docker-en-produccion"),
        ("  ¡Hola,   Mundo!  ", "hola-mundo"),
        ("Café & Té", "cafe-te"),
        ("C++ y C#", "c-y-c"),
        ("2026: el año del blog", "2026-el-ano-del-blog"),
        ("ya-es-un-slug", "ya-es-un-slug"),
    ],
)
def test_el_slug_se_deriva_del_titulo(titulo: str, esperado: str) -> None:
    """Los diacriticos se transliteran y lo demas se colapsa en guiones."""
    assert derivar_slug(titulo) == esperado


# --- SL-03: un titulo del que no sale nada ---------------------------------
@pytest.mark.parametrize("titulo", ["★★★", "   ", "!!!", "—"])
def test_un_titulo_sin_caracteres_utiles_no_produce_slug(titulo: str) -> None:
    """No se inventa un identificador.

    El slug **es** la identidad publica del contenido. Rellenarlo con un valor
    generado —una marca de tiempo, un uuid— produciria una URL que su autor no
    ha elegido y que la invariante 4 de CONTENT_MODEL.md declara estable. Se
    rechaza y se pide uno explicito.
    """
    with pytest.raises(SlugInvalidoError):
        derivar_slug(titulo)


# --- SL-04: longitud -------------------------------------------------------
def test_el_slug_derivado_respeta_el_ancho_de_la_columna() -> None:
    """160 caracteres es el ancho de `VARCHAR(160)` (data-model.md D-B)."""
    derivado = derivar_slug("palabra " * 60)

    assert len(derivado) <= LONGITUD_MAXIMA_DE_SLUG
    assert not derivado.endswith("-")
    assert not derivado.startswith("-")


def test_una_sola_palabra_larguisima_se_corta_donde_toque() -> None:
    """Cuando ni el primer grupo cabe, no hay separador por el que cortar.

    Un slug largo es preferible a ninguno: la alternativa seria rechazar el
    titulo, y el administrador no tiene por que saber que su primera palabra
    mide mas de 160 caracteres.
    """
    derivado = derivar_slug("a" * 200)

    assert derivado == "a" * LONGITUD_MAXIMA_DE_SLUG


def test_el_recorte_no_parte_una_palabra_por_la_mitad() -> None:
    """Se recorta por el ultimo separador, no por el caracter 160."""
    derivado = derivar_slug("a" * 155 + " " + "b" * 20)

    assert derivado == "a" * 155


# --- SL-05: validacion de un slug explicito --------------------------------
@pytest.mark.parametrize("valor", ["docker", "docker-en-produccion", "a", "2026-01", "a1-b2-c3"])
def test_un_slug_bien_formado_se_acepta(valor: str) -> None:
    assert validar_slug(valor) == valor


@pytest.mark.parametrize(
    "valor",
    [
        "Mal Slug!",
        "MAYUSCULAS",
        "-empieza-con-guion",
        "acaba-con-guion-",
        "doble--guion",
        "con espacio",
        "acentós",
        "barra/dentro",
        "",
        "x" * (LONGITUD_MAXIMA_DE_SLUG + 1),
    ],
)
def test_un_slug_mal_formado_se_rechaza(valor: str) -> None:
    """Se rechaza, no se corrige.

    Reescribir en silencio lo que el administrador escribio le daria una URL
    distinta de la que pidio, y no se enteraria hasta verla publicada.
    """
    with pytest.raises(SlugInvalidoError):
        validar_slug(valor)


# --- Resolucion: la regla completa de B.2 ----------------------------------
def test_sin_slug_explicito_se_usa_el_derivado_del_titulo() -> None:
    assert resolver_slug(slug=None, titulo="Docker en Produccion") == "docker-en-produccion"


def test_con_slug_explicito_se_usa_ese_y_no_el_titulo() -> None:
    """*"y es editable"*: lo que escribe el administrador manda."""
    assert resolver_slug(slug="otro-slug", titulo="Docker en Produccion") == "otro-slug"


def test_un_slug_explicito_vacio_se_trata_como_ausente() -> None:
    """Un formulario que envia el campo vacio pide la propuesta automatica."""
    assert resolver_slug(slug="   ", titulo="Docker en Produccion") == "docker-en-produccion"


def test_el_error_de_slug_es_un_error_de_validacion_del_proyecto() -> None:
    """`422` con la envoltura comun, no una excepcion suelta."""
    from app.shared.errors.exceptions import ValidationFailedError

    assert issubclass(SlugInvalidoError, ValidationFailedError)
    assert SlugInvalidoError.code == "invalid_slug"
