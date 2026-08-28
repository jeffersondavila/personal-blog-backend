"""Envoltura comun de toda coleccion paginada.

Forma fijada por api-contracts.md seccion 5:

```json
{ "items": [], "page": 1, "page_size": 12, "total": 0, "pages": 0 }
```

Es **una sola** envoltura para los seis listados publicos y para la busqueda.
Que `/search` devuelva una coleccion plana con discriminador de tipo, y no
resultados agrupados, es precisamente lo que permite que no haya una segunda
forma de paginar en la API (decision D-009-J).
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from app.shared.pagination.parametros import ParametrosDePagina


def numero_de_paginas(*, total: int, page_size: int) -> int:
    """Numero de paginas que hacen falta para `total` elementos.

    Con `total = 0` el resultado es **0**, no 1: no hay ninguna pagina, ni
    siquiera una vacia. Devolver 1 haria que un cliente que recorre paginas
    pidiera una pagina que no existe.
    """
    return -(-total // page_size)


class Pagina[T](BaseModel):
    """Coleccion paginada de elementos ya serializados."""

    items: list[T] = Field(description="Elementos de la pagina actual.")
    page: int = Field(description="Pagina devuelta.")
    page_size: int = Field(
        description="Tamano de pagina **aplicado**; difiere del pedido si excedia el maximo."
    )
    total: int = Field(description="Total de elementos que cumplen el filtro.")
    pages: int = Field(description="Numero total de paginas.")

    @classmethod
    def crear(cls, *, items: Sequence[T], parametros: ParametrosDePagina, total: int) -> Pagina[T]:
        """Envuelve los elementos de una pagina con su metadato de paginacion."""
        return cls(
            items=list(items),
            page=parametros.page,
            page_size=parametros.page_size,
            total=total,
            pages=numero_de_paginas(total=total, page_size=parametros.page_size),
        )
