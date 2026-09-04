"""Campos minimos para publicar un video (`Task/012`).

**Un video no tiene `content`.** CONTENT_MODEL.md seccion 2 y ADR-005 decision 7
lo dicen: su contenido principal es el video externo, no Markdown. Asi que el
"contenido" del que habla USER_FLOWS.md B.7 se materializa aqui en la URL y el
proveedor:

- **`video_url`.** A.6 reproduce el video *"mediante embed o enlace externo"*;
  `data-model.md` 4.7 declara la columna nula *"hasta que se pegue la URL"*. Un
  video publicado sin URL es un elemento roto en el sitio.
- **`provider`.** CONTENT_MODEL.md 3.4: *"solo se almacenan URL, proveedor y
  metadatos"*. Se exige que **exista**, no que pertenezca a ninguna lista: la
  lista cerrada de proveedores permitidos es de `Task/014`, y por eso
  `data-model.md` 4.7 dejo la columna sin `CHECK`.
- **`embed_reference` y `duration_seconds` siguen siendo opcionales**: el modelo
  los declara asi y ningun flujo los exige.

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


class VideoIncompletoError(ConflictError):
    """El video no reune los campos minimos para publicarse (D-012-H)."""

    code = "cannot_publish_incomplete_draft"

    def __init__(self, *, campos: list[str]) -> None:
        super().__init__(
            "El borrador no reune los campos minimos para publicarse.",
            details={"campos": campos},
        )
        self.campos = campos


@dataclass(frozen=True, slots=True)
class VideoPublicable:
    """Los campos del video que deciden si puede publicarse."""

    title: str
    slug: str
    summary: str | None
    seo_description: str | None
    provider: str | None
    video_url: str | None

    #: Si el contenido referencia una imagen. Va aparte del texto porque "sin
    #: imagen" y "imagen sin texto alternativo" son dos cosas distintas, y solo
    #: la segunda impide publicar: la portada nunca ha sido obligatoria.
    tiene_imagen: bool = False
    #: Texto alternativo de esa imagen, tal como esta en `media_assets`.
    imagen_alt_text: str | None = None


def _vacio(valor: str | None) -> bool:
    return valor is None or not valor.strip()


def campos_que_faltan_en_el_video(video: VideoPublicable) -> list[str]:
    """Enumera lo que le falta al video para poder publicarse."""
    faltantes: list[str] = []
    if _vacio(video.title):
        faltantes.append("title")
    if _vacio(video.slug):
        faltantes.append("slug")
    if _vacio(video.summary) and _vacio(video.seo_description):
        faltantes.append("summary")
    if _vacio(video.provider):
        faltantes.append("provider")
    if _vacio(video.video_url):
        faltantes.append("video_url")
    if video.tiene_imagen and _vacio(video.imagen_alt_text):
        # Requisito A-04, exigido **donde se usa** la imagen. Un `alt` en blanco
        # cuenta como ausente: para un lector de pantalla no describe nada.
        faltantes.append("thumbnail_alt_text")
    return faltantes


def exigir_video_publicable(video: VideoPublicable) -> None:
    """Lanza si el video no puede publicarse."""
    faltantes = campos_que_faltan_en_el_video(video)
    if faltantes:
        raise VideoIncompletoError(campos=faltantes)
