"""Campos minimos para publicar un proyecto (`Task/012`).

Mismas reglas que el articulo: `Project` tiene `content` en Markdown
(CONTENT_MODEL.md seccion 2). Lo que **no** se exige, y por que:

- **`repository_url` y `demo_url`.** CONTENT_MODEL.md 3.5 los llama *"opcional"*
  a los dos. Un proyecto puede no tener repositorio publico ni demo desplegada.
- **`technologies`.** Es una lista que solo se muestra (decision D-G) y su
  *default* real es la lista vacia (`data-model.md` 4.4.1).
- **`project_status`.** Tiene *default* `active`, que es cierto para un proyecto
  recien creado. Es ademas ortogonal a la publicacion: CONTENT_MODEL.md 3.5
  advierte de no mezclar los dos estados.

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


class ProyectoIncompletoError(ConflictError):
    """El proyecto no reune los campos minimos para publicarse (D-012-H)."""

    code = "cannot_publish_incomplete_draft"

    def __init__(self, *, campos: list[str]) -> None:
        super().__init__(
            "El borrador no reune los campos minimos para publicarse.",
            details={"campos": campos},
        )
        self.campos = campos


@dataclass(frozen=True, slots=True)
class ProyectoPublicable:
    """Los campos del proyecto que deciden si puede publicarse."""

    title: str
    slug: str
    content: str
    summary: str | None
    seo_description: str | None

    #: Si el contenido referencia una imagen. Va aparte del texto porque "sin
    #: imagen" y "imagen sin texto alternativo" son dos cosas distintas, y solo
    #: la segunda impide publicar: la portada nunca ha sido obligatoria.
    tiene_imagen: bool = False
    #: Texto alternativo de esa imagen, tal como esta en `media_assets`.
    imagen_alt_text: str | None = None


def _vacio(valor: str | None) -> bool:
    return valor is None or not valor.strip()


def campos_que_faltan_en_el_proyecto(proyecto: ProyectoPublicable) -> list[str]:
    """Enumera lo que le falta al proyecto para poder publicarse."""
    faltantes: list[str] = []
    if _vacio(proyecto.title):
        faltantes.append("title")
    if _vacio(proyecto.slug):
        faltantes.append("slug")
    if _vacio(proyecto.content):
        faltantes.append("content")
    if _vacio(proyecto.summary) and _vacio(proyecto.seo_description):
        faltantes.append("summary")
    if proyecto.tiene_imagen and _vacio(proyecto.imagen_alt_text):
        # Requisito A-04, exigido **donde se usa** la imagen. Un `alt` en blanco
        # cuenta como ausente: para un lector de pantalla no describe nada.
        faltantes.append("cover_alt_text")
    return faltantes


def exigir_proyecto_publicable(proyecto: ProyectoPublicable) -> None:
    """Lanza si el proyecto no puede publicarse."""
    faltantes = campos_que_faltan_en_el_proyecto(proyecto)
    if faltantes:
        raise ProyectoIncompletoError(campos=faltantes)
