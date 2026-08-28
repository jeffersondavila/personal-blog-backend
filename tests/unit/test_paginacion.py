"""Primitivas de paginacion compartidas (matriz I-08, I-03).

`shared/pagination` estuvo aplazado desde `Task/005` hasta que existiera una
necesidad real. `Task/009` la trae: diez endpoints publicos comparten la misma
envoltura y las mismas reglas de recorte.

Lo que se prueba aqui es **logica pura**: el calculo del numero de paginas y el
recorte de `page_size`. No necesita FastAPI, ni base de datos, ni HTTP. El
comportamiento HTTP de esos mismos valores se prueba en `tests/contract/`.
"""

from __future__ import annotations

import pytest

from app.shared.pagination import (
    PAGE_SIZE_MAXIMO,
    PAGE_SIZE_POR_DEFECTO,
    ParametrosDePagina,
    numero_de_paginas,
)


# --- I-08: numero de paginas -----------------------------------------------
@pytest.mark.parametrize(
    ("total", "page_size", "esperado"),
    [
        # El caso que mas facil es equivocar: sin contenido no hay ninguna
        # pagina, ni siquiera una vacia (api-contracts.md seccion 5).
        (0, 12, 0),
        (1, 12, 1),
        (12, 12, 1),
        (13, 12, 2),
        (5, 2, 3),
        (24, 12, 2),
        (25, 12, 3),
    ],
)
def test_el_numero_de_paginas_redondea_hacia_arriba(
    total: int, page_size: int, esperado: int
) -> None:
    assert numero_de_paginas(total=total, page_size=page_size) == esperado


# --- I-03: recorte de page_size --------------------------------------------
def test_page_size_por_encima_del_maximo_se_recorta() -> None:
    """No es un error: api-contracts.md seccion 5 lo declara recorte, no rechazo."""
    parametros = ParametrosDePagina.de(page=1, page_size=PAGE_SIZE_MAXIMO + 1)

    assert parametros.page_size == PAGE_SIZE_MAXIMO


def test_page_size_desmesurado_tambien_se_recorta() -> None:
    parametros = ParametrosDePagina.de(page=1, page_size=100_000)

    assert parametros.page_size == PAGE_SIZE_MAXIMO


def test_page_size_dentro_del_limite_se_respeta() -> None:
    parametros = ParametrosDePagina.de(page=1, page_size=5)

    assert parametros.page_size == 5


def test_los_valores_por_defecto_son_los_declarados_por_task_009() -> None:
    """D-009-A y D-009-B: elegidos y documentados, no heredados de FastAPI."""
    assert PAGE_SIZE_POR_DEFECTO == 12
    assert PAGE_SIZE_MAXIMO == 50


# --- Traduccion a LIMIT / OFFSET -------------------------------------------
@pytest.mark.parametrize(
    ("page", "page_size", "offset"),
    [(1, 12, 0), (2, 12, 12), (3, 2, 4), (99, 10, 980)],
)
def test_el_desplazamiento_corresponde_a_la_pagina_pedida(
    page: int, page_size: int, offset: int
) -> None:
    parametros = ParametrosDePagina.de(page=page, page_size=page_size)

    assert parametros.offset == offset
    assert parametros.limit == page_size


def test_el_recorte_afecta_tambien_al_desplazamiento() -> None:
    """El recorte ocurre antes de calcular el desplazamiento, no despues.

    Si se calculara con el tamano pedido y se recortara al servir, la pagina 2
    empezaria en un elemento que la pagina 1 nunca mostro: se perderian filas.
    """
    parametros = ParametrosDePagina.de(page=2, page_size=PAGE_SIZE_MAXIMO + 50)

    assert parametros.page_size == PAGE_SIZE_MAXIMO
    assert parametros.offset == PAGE_SIZE_MAXIMO
