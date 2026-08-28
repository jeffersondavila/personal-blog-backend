"""Orden de los listados publicos: lista cerrada y desempate total.

Dos decisiones de `Task/009` viven aqui.

**D-009-E — sintaxis.** api-contracts.md seccion 6 declara `sort` como **un**
parametro, asi que la direccion viaja en el propio valor con el prefijo `-`:
`sort=title` ascendente, `sort=-title` descendente. Un segundo parametro
`order` admitiria el estado invalido "direccion sin campo".

**D-009-F — desempate.** El orden por defecto es `published_at DESC`
(api-contracts.md seccion 6), y dos filas **pueden** compartir esa fecha. Un
`LIMIT`/`OFFSET` sobre un orden que no es total puede devolver la misma fila en
dos paginas y omitir otra, sin ningun error visible. El desempate es `slug`
ascendente: es `UNIQUE NOT NULL` en las cuatro tablas de contenido, asi que
convierte cualquier orden en total, y ademas es la identidad publica, de modo
que el resultado es explicable y no un orden aparentemente aleatorio.

Por que la lista es un `Literal` y no una comprobacion escrita a mano
--------------------------------------------------------------------

El valor de `sort` **nunca** se interpola en SQL. Declararlo como `Literal`
consigue tres cosas de una vez: FastAPI rechaza cualquier otro valor con el
`422` del contrato comun, OpenAPI lo documenta como enumeracion, y el codigo de
esta funcion solo puede recibir una de las cuatro cadenas admitidas. Una
comprobacion manual dejaria la puerta abierta a que alguien pasara el valor
crudo a un `text()`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sqlalchemy import UnaryExpression
from sqlalchemy.orm import InstrumentedAttribute

#: Lista **cerrada** de ordenaciones publicas (D-009-D). Cualquier otro valor
#: produce `422` (api-contracts.md seccion 6).
OrdenPublico = Literal["published_at", "-published_at", "title", "-title"]

#: Orden aplicado cuando el cliente no pide ninguno (api-contracts.md seccion 6).
ORDEN_POR_DEFECTO: OrdenPublico = "-published_at"


def clausula_de_orden(
    *,
    sort: OrdenPublico | None,
    columnas: Mapping[str, InstrumentedAttribute[Any]],
    desempate: InstrumentedAttribute[Any],
) -> Sequence[UnaryExpression[Any]]:
    """Traduce un valor de `sort` ya validado a clausulas `ORDER BY`.

    `columnas` lo aporta cada modulo con sus propias columnas: esta funcion es
    agnostica del modelo y por eso puede vivir en `shared` sin arrastrar ninguna
    regla de negocio (software-architecture.md seccion 3.4).

    El desempate se anade **siempre**, tambien cuando se ordena por `title`:
    dos titulos pueden repetirse igual que dos fechas.
    """
    clave = sort if sort is not None else ORDEN_POR_DEFECTO
    descendente = clave.startswith("-")
    columna = columnas[clave.removeprefix("-")]
    return [columna.desc() if descendente else columna.asc(), desempate.asc()]
