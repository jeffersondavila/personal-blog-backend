"""Tiempo de lectura estimado (matriz C-05).

`data-model.md` (decision D-O) es explicito: `reading_time` **no se persiste**,
porque seria un segundo estado que queda obsoleto en cuanto se edita el
contenido. Se calcula **al servir**, y esa responsabilidad esta asignada a
`Task/009` y `Task/014`. `Task/009` calcula el numero; `Task/014` decide como
se presenta.

Es logica pura sobre una cadena: ni base de datos, ni HTTP.
"""

from __future__ import annotations

import pytest

from app.shared.lectura import PALABRAS_POR_MINUTO, minutos_de_lectura


def test_un_contenido_vacio_no_tiene_tiempo_de_lectura() -> None:
    assert minutos_de_lectura("") == 0


def test_solo_espacios_equivale_a_contenido_vacio() -> None:
    assert minutos_de_lectura("   \n\t  ") == 0


def test_un_texto_muy_corto_se_redondea_a_un_minuto() -> None:
    """Nunca se anuncian "0 minutos" para algo que si hay que leer."""
    assert minutos_de_lectura("Una sola frase corta.") == 1


def test_el_calculo_usa_la_velocidad_declarada() -> None:
    texto = " ".join(["palabra"] * PALABRAS_POR_MINUTO)

    assert minutos_de_lectura(texto) == 1


def test_se_redondea_hacia_arriba() -> None:
    """Un minuto y un poco son dos minutos: quedarse corto enganaria al lector."""
    texto = " ".join(["palabra"] * (PALABRAS_POR_MINUTO + 1))

    assert minutos_de_lectura(texto) == 2


@pytest.mark.parametrize("factor", [2, 3, 10])
def test_el_tiempo_crece_de_forma_proporcional(factor: int) -> None:
    texto = " ".join(["palabra"] * (PALABRAS_POR_MINUTO * factor))

    assert minutos_de_lectura(texto) == factor


def test_los_saltos_de_linea_separan_palabras() -> None:
    """El Markdown llega con saltos de linea, no con espacios simples."""
    assert minutos_de_lectura("una\ndos\n\ntres\ttcuatro") == 1


def test_el_contenido_es_markdown_fuente_y_no_se_renderiza() -> None:
    """`Task/009` no es un renderer (ADR-005): cuenta lo que hay, sin interpretar.

    La sintaxis Markdown se cuenta como parte del texto. Interpretarla exigiria
    un renderer, que pertenece a `Task/014`, y el resultado apenas cambiaria: el
    tiempo de lectura es una estimacion, no una medida.
    """
    assert minutos_de_lectura("# Titulo\n\n- uno\n- dos\n") == 1
