"""Formato y generacion del `slug` (`Task/012`).

`data-model.md` seccion 6, invariante 8, y su deuda 7 asignan a esta tarea *"el
formato y la generacion del slug"*. La fuente del comportamiento es
USER_FLOWS.md B.2: *"Introduce titulo; el **slug se propone automaticamente** y
es editable"*.

Por que vive en `shared` y no en un modulo
-------------------------------------------

El slug lo usan **cinco** tipos —articulos, reviews, videos, proyectos y
etiquetas— con exactamente el mismo formato, y su derivacion no conoce ninguna
tabla, ninguna regla de publicacion ni ninguna relacion. Es una transformacion
de texto, del mismo orden que `app/shared/lectura.py`, que ya calcula el tiempo
de lectura desde `shared` sin que eso convierta al paquete en dueno de ninguna
regla de negocio.

Lo que **no** esta aqui es la unicidad: `slug` es `UNIQUE` por tabla
(`data-model.md` D-B), asi que "este slug ya existe" es una pregunta de
persistencia y la responde el repositorio de cada modulo.

Decisiones
----------

- **D-012-E.** El slug es **opcional** en la peticion. Si falta, se deriva del
  titulo; si viene, se usa el que viene.
- **D-012-G.** Formato: minusculas ASCII, digitos y guiones simples, sin guion
  inicial ni final, de 1 a 160 caracteres —el ancho de la columna—. Un slug
  explicito mal formado se **rechaza**; no se corrige en silencio, porque
  reescribir lo que el administrador escribio le daria una URL distinta de la
  que pidio y no se enteraria hasta verla publicada.
- Un titulo del que no sale ningun caracter util **no** produce slug: rellenarlo
  con un valor generado inventaria la identidad publica del contenido, que la
  invariante 4 de CONTENT_MODEL.md declara estable.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from app.shared.errors.exceptions import ConflictError, ValidationFailedError

#: Ancho de la columna `slug` en las cinco tablas que la tienen (D-B).
LONGITUD_MAXIMA_DE_SLUG: Final = 160

#: Un slug es uno o mas grupos alfanumericos separados por un unico guion. La
#: expresion rechaza por construccion el guion inicial, el final y el doble.
_FORMATO: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_NO_ALFANUMERICO: Final = re.compile(r"[^a-z0-9]+")


class SlugInvalidoError(ValidationFailedError):
    """El slug recibido no tiene el formato exigido, o no pudo derivarse."""

    code = "invalid_slug"


class SlugDuplicadoError(ConflictError):
    """Ya existe un contenido de ese tipo con ese slug.

    **`409` y no `422`**: la peticion es correcta; lo que choca es el estado
    actual de la coleccion (`api-contracts.md` seccion 8, que da el slug
    duplicado como su ejemplo textual de `409`).

    La unicidad es **por tipo** —cada tabla tiene su propio indice unico
    (`data-model.md` D-B)—, asi que `/articulos/docker` y `/videos/docker` son
    dos URL legitimas y este error solo compara dentro de un tipo.
    """

    code = "slug_already_exists"

    def __init__(self, slug: str) -> None:
        super().__init__(
            "Ya existe un contenido de este tipo con ese slug.",
            details={"slug": slug},
        )
        self.slug = slug


class SlugInmutableError(ConflictError):
    """El slug ya no puede cambiarse: el contenido se publico alguna vez.

    Decision **D-012-F**. `api-contracts.md` seccion 4 concede el cambio
    *"mientras se edita un borrador"*, y la invariante 4 de CONTENT_MODEL.md
    declara los slugs *"estables: cambiarlos rompe URLs y SEO"*. La frontera
    exacta no es el estado sino **haber sido publico alguna vez**: un borrador
    despublicado ya tuvo URL indexada, y `published_at` es la marca de que la
    tuvo.
    """

    code = "slug_is_immutable"

    def __init__(self, slug: str) -> None:
        super().__init__(
            "El slug no puede cambiarse: este contenido ya se publico y su URL es publica.",
            details={"slug": slug},
        )
        self.slug = slug


def _transliterar(texto: str) -> str:
    """Reduce el texto a ASCII conservando la letra base de cada caracter.

    `NFKD` separa la letra de su diacritico, y descartar los caracteres de la
    categoria `Mn` —marcas sin ancho— deja `produccion` a partir de
    `produccion` con tilde. La `n` con virgulilla sigue el mismo camino y
    termina en `n`, que es lo que un lector hispanohablante espera de una URL.
    """
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(caracter for caracter in descompuesto if not unicodedata.combining(caracter))


def _recortar(valor: str) -> str:
    """Recorta a la longitud maxima **por un separador**, no por el caracter.

    Cortar en seco partiria la ultima palabra por la mitad y dejaria un slug que
    no se lee. Si ni siquiera el primer grupo cabe, se corta donde toque: un
    slug largo es preferible a ninguno.
    """
    if len(valor) <= LONGITUD_MAXIMA_DE_SLUG:
        return valor
    recortado = valor[:LONGITUD_MAXIMA_DE_SLUG]
    if "-" in recortado:
        recortado = recortado.rsplit("-", 1)[0]
    return recortado.strip("-")


def derivar_slug(titulo: str) -> str:
    """Propone el slug de un titulo (USER_FLOWS.md B.2)."""
    candidato = _NO_ALFANUMERICO.sub("-", _transliterar(titulo).lower()).strip("-")
    candidato = _recortar(candidato)
    if not candidato:
        raise SlugInvalidoError(
            "No se puede proponer un slug a partir de este titulo. Indica uno explicito.",
            details={"campo": "title"},
        )
    return candidato


def validar_slug(valor: str) -> str:
    """Comprueba que un slug escrito a mano tiene el formato exigido."""
    if len(valor) > LONGITUD_MAXIMA_DE_SLUG or not _FORMATO.match(valor):
        raise SlugInvalidoError(
            "El slug solo admite minusculas, digitos y guiones simples, "
            f"sin guion inicial ni final, con un maximo de {LONGITUD_MAXIMA_DE_SLUG} caracteres.",
            details={"campo": "slug", "valor": valor},
        )
    return valor


def resolver_slug(*, slug: str | None, titulo: str) -> str:
    """Aplica la regla completa de B.2: propuesto desde el titulo, y editable.

    Un slug presente pero en blanco se trata como **ausente**: es lo que envia
    un formulario cuyo campo el administrador no ha tocado, y rechazarlo le
    obligaria a escribir a mano lo que la aplicacion se ofrece a proponer.
    """
    if slug is None or not slug.strip():
        return derivar_slug(titulo)
    return validar_slug(slug.strip())
