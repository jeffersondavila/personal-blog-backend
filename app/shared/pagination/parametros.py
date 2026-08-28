"""Parametros de una coleccion paginada y su traduccion a `LIMIT`/`OFFSET`.

Los valores concretos son **decisiones de `Task/009`**, no valores heredados del
framework (ficha de la tarea, D-009-A y D-009-B):

- **`page_size` por defecto: 12.** Es el que usan todos los ejemplos canonicos:
  USER_FLOWS.md A.2, A.4, A.6 y A.8, y la envoltura de api-contracts.md
  seccion 5.
- **`page_size` maximo: 50.** Ninguna fuente lo fijaba. Da holgura real a un
  cliente que quiera menos viajes y acota la consulta (requisitos P-02 y P-08).

**Recorte y no rechazo.** api-contracts.md seccion 5 es explicito: un
`page_size` por encima del maximo *"se recorta al maximo; no es un error"*. Lo
que si es error —`422`— es un valor que no sea un entero mayor o igual que 1, y
de eso se encarga la validacion declarativa de FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Query

#: Elementos por pagina cuando el cliente no pide un tamano (D-009-A).
PAGE_SIZE_POR_DEFECTO: Final[int] = 12

#: Tope duro de elementos por pagina (D-009-B). No existe forma de superarlo:
#: por encima se recorta, de modo que ningun endpoint puede devolver "todo"
#: (api-contracts.md seccion 5, requisito P-02).
PAGE_SIZE_MAXIMO: Final[int] = 50


@dataclass(frozen=True, slots=True)
class ParametrosDePagina:
    """Pagina solicitada, ya normalizada.

    `page_size` es el tamano **aplicado**, no el pedido: cuando el cliente pide
    mas del maximo, aqui ya viene recortado. Esa es la razon de que la clase
    exista en lugar de pasar dos enteros sueltos: el recorte tiene que ocurrir
    **antes** de calcular el desplazamiento. Si se recortara al servir, la
    pagina 2 de un `page_size` de 200 empezaria en el elemento 200 mientras la
    pagina 1 solo mostro 50, y se perderian 150 elementos sin que nadie lo
    notara.
    """

    page: int
    page_size: int

    @classmethod
    def de(cls, *, page: int, page_size: int) -> ParametrosDePagina:
        """Construye los parametros aplicando el recorte del maximo."""
        return cls(page=page, page_size=min(page_size, PAGE_SIZE_MAXIMO))

    @property
    def limit(self) -> int:
        """Elementos a pedir a la base de datos."""
        return self.page_size

    @property
    def offset(self) -> int:
        """Elementos a saltar. `page` empieza en 1 (api-contracts.md seccion 5)."""
        return (self.page - 1) * self.page_size


def parametros_de_pagina(
    page: Annotated[
        int,
        Query(ge=1, description="Pagina solicitada, comenzando en 1."),
    ] = 1,
    page_size: Annotated[
        int,
        Query(
            ge=1,
            description=(
                f"Elementos por pagina. Por defecto {PAGE_SIZE_POR_DEFECTO}; "
                f"por encima de {PAGE_SIZE_MAXIMO} se recorta a ese maximo."
            ),
        ),
    ] = PAGE_SIZE_POR_DEFECTO,
) -> ParametrosDePagina:
    """Dependencia de FastAPI que valida y normaliza la pagina pedida.

    `ge=1` y no un rango cerrado: un `page_size` grande **no** es invalido, se
    recorta. Declarar `le=PAGE_SIZE_MAXIMO` convertiria el recorte que exige
    api-contracts.md en un `422`, que es justo lo contrario.

    Una `page` fuera de rango tampoco es un error: produce una pagina vacia con
    `200`, y eso se resuelve solo, porque el `OFFSET` no encuentra filas.
    """
    return ParametrosDePagina.de(page=page, page_size=page_size)
