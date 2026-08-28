"""Filtros de los listados publicos de contenido.

Son **declaraciones de parametros de consulta**: nombres, tipos y validacion, es
decir, transporte HTTP. Lo que cada filtro significa en la base de datos lo
resuelve la consulta de su modulo. Por eso viven aqui, en la capa de transporte
transversal, y no en `app/shared`, que tiene prohibido contener vocabulario de
negocio, ni duplicados cuatro veces en cuatro routers que declararian
exactamente lo mismo.

Los cuatro listados de contenido —articulos, reviews, videos y proyectos—
comparten estos tres filtros (api-contracts.md seccion 6).

`featured`: por que un literal y no un `bool`
---------------------------------------------

**Decision D-009-G.** api-contracts.md describe el caso verdadero —*"solo
contenido destacado"*— y no define el falso. Se cierra como filtro booleano
completo: `true` devuelve solo destacados, `false` solo los no destacados, y su
ausencia no filtra. Un parametro cuyo `false` no hiciera nada seria una trampa
para quien lo escriba.

El tipo es `Literal["true", "false"]` y no `bool` a proposito: Pydantic aceptaria
`1`, `yes`, `on` y `True`, y esas coerciones son exactamente las que el contrato
no debe heredar sin declararlas. Con el literal, OpenAPI documenta los dos
unicos valores admitidos y cualquier otro produce `422`.

`status` **no aparece aqui**, y no por olvido: no existe como parametro publico
(api-contracts.md seccion 6). Al no estar declarado, la politica de parametros
desconocidos lo rechaza con `422`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Query

from app.shared.pagination import OrdenPublico

#: Longitud maxima de un slug de etiqueta, igual que la columna `tags.slug`.
LONGITUD_MAXIMA_DE_SLUG = 160


@dataclass(frozen=True, slots=True)
class FiltrosDeContenido:
    """Filtros publicos ya validados de un listado de contenido."""

    tag: str | None
    featured: bool | None
    sort: OrdenPublico | None


def filtros_de_contenido(
    tag: Annotated[
        str | None,
        Query(
            max_length=LONGITUD_MAXIMA_DE_SLUG,
            description=(
                "Slug de etiqueta. Una etiqueta inexistente no es un error: "
                "devuelve una coleccion vacia."
            ),
        ),
    ] = None,
    featured: Annotated[
        Literal["true", "false"] | None,
        Query(
            description=(
                "`true` devuelve solo contenido destacado; `false`, solo el no "
                "destacado. Omitirlo no filtra."
            ),
        ),
    ] = None,
    sort: Annotated[
        OrdenPublico | None,
        Query(
            description=(
                "Orden alternativo. Lista cerrada; el prefijo `-` invierte la "
                "direccion. Por defecto `-published_at`."
            ),
        ),
    ] = None,
) -> FiltrosDeContenido:
    """Dependencia de FastAPI con los filtros comunes de un listado publico."""
    return FiltrosDeContenido(
        tag=tag,
        featured=None if featured is None else featured == "true",
        sort=sort,
    )
