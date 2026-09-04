"""Campos minimos para publicar una review (`Task/012`).

Todo lo del articulo, mas lo que solo tiene una review. Las tres adiciones estan
asignadas por fuente:

- **`rating`.** CONTENT_MODEL.md 3.3 es literal: *"Puede estar ausente mientras
  la review sea un borrador; exigirla para **publicar** es una validacion de
  publicacion y pertenece a `Task/012`"*. La escala 1..5 la garantizan el
  dominio (`Rating`) y el `CHECK` de la base; aqui solo se exige que **haya**
  valoracion.
- **`book_title` y `book_author`.** El listado publico (A.4) y el detalle (A.5)
  los muestran, y `data-model.md` 4.6 los declara nulos *"en un borrador recien
  creado"* — es decir, mientras se escribe.
- **`external_link` sigue siendo opcional**: CONTENT_MODEL.md 3.3 lo llama
  *"enlace opcional"* y A.5 lo muestra *"si existe"*.

Texto alternativo de la imagen — asignado a `Task/012` **antes** de `Task/012`
------------------------------------------------------------------------------

`data-model.md` seccion 4.1, fila `alt_text`: *"accesibilidad (A-04)…
**Exigirlo donde se usa es de `Task/012` y `Task/014`**"*. La ficha de
`Task/010`, decision **D-010-N**, dice lo mismo: *"la accesibilidad se garantiza
donde se **usa** el medio (`Task/012`, `Task/014`), no en el almacen"*.

Una imagen se **usa**, en la superficie de esta tarea, cuando un contenido la
referencia **y ese contenido pasa a ser visible**. Antes de eso no hay ningun
lector al que le falte nada, y bloquear la asociacion haria imposible el flujo
B.5 que la propia D-010-N describe —*"B.5 asocia despues"*—.

Por eso se exige **al publicar**, no al cargar ni al asociar. Exigirlo al cargar
seria revertir D-010-N, que es una decision aprobada.

Dominio puro (ADR-004).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.errors.exceptions import ConflictError


class ReviewIncompletaError(ConflictError):
    """La review no reune los campos minimos para publicarse (D-012-H)."""

    code = "cannot_publish_incomplete_draft"

    def __init__(self, *, campos: list[str]) -> None:
        super().__init__(
            "El borrador no reune los campos minimos para publicarse.",
            details={"campos": campos},
        )
        self.campos = campos


@dataclass(frozen=True, slots=True)
class ReviewPublicable:
    """Los campos de la review que deciden si puede publicarse."""

    title: str
    slug: str
    content: str
    summary: str | None
    seo_description: str | None
    book_title: str | None
    book_author: str | None
    rating: int | None

    #: Si el contenido referencia una imagen. Va aparte del texto porque "sin
    #: imagen" y "imagen sin texto alternativo" son dos cosas distintas, y solo
    #: la segunda impide publicar: la portada nunca ha sido obligatoria.
    tiene_imagen: bool = False
    #: Texto alternativo de esa imagen, tal como esta en `media_assets`.
    imagen_alt_text: str | None = None


def _vacio(valor: str | None) -> bool:
    return valor is None or not valor.strip()


def campos_que_faltan_en_la_review(review: ReviewPublicable) -> list[str]:
    """Enumera lo que le falta a la review para poder publicarse."""
    faltantes: list[str] = []
    if _vacio(review.title):
        faltantes.append("title")
    if _vacio(review.slug):
        faltantes.append("slug")
    if _vacio(review.content):
        faltantes.append("content")
    if _vacio(review.summary) and _vacio(review.seo_description):
        faltantes.append("summary")
    if _vacio(review.book_title):
        faltantes.append("book_title")
    if _vacio(review.book_author):
        faltantes.append("book_author")
    if review.rating is None:
        faltantes.append("rating")
    if review.tiene_imagen and _vacio(review.imagen_alt_text):
        # Requisito A-04, exigido **donde se usa** la imagen. Un `alt` en blanco
        # cuenta como ausente: para un lector de pantalla no describe nada.
        faltantes.append("cover_alt_text")
    return faltantes


def exigir_review_publicable(review: ReviewPublicable) -> None:
    """Lanza si la review no puede publicarse."""
    faltantes = campos_que_faltan_en_la_review(review)
    if faltantes:
        raise ReviewIncompletaError(campos=faltantes)
