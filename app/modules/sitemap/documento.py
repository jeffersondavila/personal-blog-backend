"""Construccion del documento `sitemap.xml`.

Mitad **pura** del sitemap: recibe el origen del sitio y las entradas, y
devuelve el XML. No conoce la base de datos, FastAPI ni la configuracion, y por
eso se puede probar sin ninguno de los tres.

El XML se construye con `xml.etree.ElementTree` y **no** concatenando cadenas:
un slug con `&`, `<` o `>` produciria un documento mal formado, y el escape
correcto no es algo que convenga reimplementar. La declaracion se escribe
aparte porque `tostring` con `encoding="unicode"` no la emite, y el protocolo
espera `UTF-8` en mayusculas como en los ejemplos de sitemaps.org.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from xml.etree import ElementTree

from app.modules.sitemap.tipos import RUTAS_ESTATICAS, EntradaDeSitemap

#: Espacio de nombres obligatorio del protocolo de sitemaps.
ESPACIO_DE_NOMBRES = "http://www.sitemaps.org/schemas/sitemap/0.9"

DECLARACION = '<?xml version="1.0" encoding="UTF-8"?>'

#: Tipo de contenido de la respuesta.
TIPO_DE_CONTENIDO = "application/xml"


def _instante_en_utc(momento: datetime) -> str:
    """Formatea un instante en UTC, de forma determinista.

    Se normaliza a UTC a proposito: PostgreSQL puede devolver el valor con el
    desplazamiento de la sesion, y un mismo instante escrito con dos
    desplazamientos distintos produciria dos fechas distintas en el documento.
    Un `TIMESTAMPTZ` sin zona no deberia existir; si apareciera, se interpreta
    como UTC en lugar de fallar al generar el sitemap entero.
    """
    if momento.tzinfo is None:
        return momento.replace(tzinfo=UTC).isoformat()
    return momento.astimezone(UTC).isoformat()


def construir_documento_de_sitemap(*, base_url: str, entradas: Iterable[EntradaDeSitemap]) -> str:
    """Devuelve el `sitemap.xml` del sitio.

    Primero las rutas estaticas, en el orden de la navegacion, y despues las de
    contenido. Las estaticas **no** declaran `lastmod`: ningun dato del contrato
    dice cuando cambio un listado, y una fecha inventada seria peor que ninguna.

    `base_url` se normaliza sin barra final para que unir origen y ruta no
    produzca `//`.
    """
    origen = base_url.rstrip("/")
    raiz = ElementTree.Element("urlset", {"xmlns": ESPACIO_DE_NOMBRES})

    for ruta in RUTAS_ESTATICAS:
        nodo = ElementTree.SubElement(raiz, "url")
        ElementTree.SubElement(nodo, "loc").text = f"{origen}{ruta}"

    for entrada in entradas:
        nodo = ElementTree.SubElement(raiz, "url")
        ElementTree.SubElement(nodo, "loc").text = f"{origen}{entrada.ruta}"
        if entrada.ultima_modificacion is not None:
            ElementTree.SubElement(nodo, "lastmod").text = _instante_en_utc(
                entrada.ultima_modificacion
            )

    cuerpo = ElementTree.tostring(raiz, encoding="unicode")
    return f"{DECLARACION}{cuerpo}"
