"""Tipos y rutas del sitemap publico."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Rutas publicas que existen siempre, con contenido o sin el.
#:
#: Son las once superficies publicas de `Task/016` menos las que **no** deben
#: indexarse: `/buscar` es `noindex` —una pagina de resultados por termino
#: generaria infinitas URL de contenido duplicado— y la 404 tampoco se enumera.
#: `/videos` aparece como listado; **no existe** `/videos/{slug}` porque el
#: contrato no tiene detalle de video (api-contracts.md seccion 3).
RUTAS_ESTATICAS: tuple[str, ...] = (
    "/",
    "/quien-soy",
    "/articulos",
    "/reviews",
    "/videos",
    "/proyectos",
    "/contacto",
)

#: Prefijo de ruta publica de cada tipo con pagina de detalle.
#:
#: Debe coincidir con la tabla de rutas del frontend (`src/lib/rutas.ts`,
#: decision D-014-A). Los videos no estan porque no tienen detalle.
PREFIJO_DE_ARTICULOS = "/articulos"
PREFIJO_DE_REVIEWS = "/reviews"
PREFIJO_DE_PROYECTOS = "/proyectos"


@dataclass(frozen=True, slots=True)
class EntradaDeSitemap:
    """Una URL del sitemap, ya resuelta a ruta del sitio.

    `ultima_modificacion` sale de `published_at`, que es lo unico que el
    contrato publico expone. **No** se usa `updated_at`: no esta en el DTO
    publico, y `Task/016` no amplia el contrato para un dato que ninguna fuente
    canonica pide. `None` significa que no se declara `lastmod`, en lugar de
    inventar una fecha.
    """

    ruta: str
    ultima_modificacion: datetime | None
