"""Campos minimos para publicar un articulo (`Task/012`).

Invariante 18 de `data-model.md`: *"Campos minimos para publicar — `Task/012`"*.
`Task/008` dejo el hueco a proposito: el esquema tiene que poder **representar**
un borrador incompleto (USER_FLOWS.md B.2 solo exige el titulo), e impedir que
se publique asi *"es otra capa"*.

La regla sale de USER_FLOWS.md B.7 —*"titulo, slug, contenido, y SEO si
corresponde"*— traducida campo a campo en la ficha de `Task/012`, seccion 7.0.3.

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

Dominio puro: Python plano, sin FastAPI ni SQLAlchemy (ADR-004).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.errors.exceptions import ConflictError


class ArticuloIncompletoError(ConflictError):
    """El articulo no reune los campos minimos para publicarse.

    **`409` y no `422`** (decision D-012-H): la peticion de publicar esta bien
    formada y vacia; lo que impide la operacion es el **estado del recurso**, que
    es lo que api-contracts.md seccion 8 reserva para `409`.

    Los campos que faltan viajan en `details`, la forma que api-contracts.md
    seccion 7 reserva para el contexto estructurado, y **todos a la vez**: que el
    administrador los descubra de uno en uno seria una sucesion de intentos
    fallidos evitable.
    """

    code = "cannot_publish_incomplete_draft"

    def __init__(self, *, campos: list[str]) -> None:
        super().__init__(
            "El borrador no reune los campos minimos para publicarse.",
            details={"campos": campos},
        )
        self.campos = campos


@dataclass(frozen=True, slots=True)
class ArticuloPublicable:
    """Los campos del articulo que deciden si puede publicarse, y ninguno mas.

    No es el articulo entero: un objeto con quince campos obligaria a las
    pruebas de esta regla a rellenar catorce que no participan en ella.
    """

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
    """Un campo en blanco es un campo ausente.

    `content` es `NOT NULL DEFAULT ''`: un borrador sin cuerpo **es** la cadena
    vacia (`data-model.md` seccion 4.4.1), asi que distinguirla de nula no
    aportaria nada aqui.
    """
    return valor is None or not valor.strip()


def campos_que_faltan_en_el_articulo(articulo: ArticuloPublicable) -> list[str]:
    """Enumera lo que le falta al articulo para poder publicarse.

    Devuelve una lista y no un booleano porque el mensaje de rechazo tiene que
    decir **que** falta (B.7 habla de campos, no de un estado global).
    """
    faltantes: list[str] = []
    if _vacio(articulo.title):
        faltantes.append("title")
    if _vacio(articulo.slug):
        faltantes.append("slug")
    if _vacio(articulo.content):
        faltantes.append("content")
    if _vacio(articulo.summary) and _vacio(articulo.seo_description):
        # "SEO si corresponde" no exige los campos SEO —contradiria el
        # *fallback* de CONTENT_MODEL.md seccion 2—: exige que la descripcion
        # **se pueda resolver**, y `seo_description` cae en `summary`.
        faltantes.append("summary")
    if articulo.tiene_imagen and _vacio(articulo.imagen_alt_text):
        # Requisito A-04, exigido **donde se usa** la imagen. Un `alt` en blanco
        # cuenta como ausente: para un lector de pantalla no describe nada.
        faltantes.append("cover_alt_text")
    return faltantes


def exigir_articulo_publicable(articulo: ArticuloPublicable) -> None:
    """Lanza si el articulo no puede publicarse."""
    faltantes = campos_que_faltan_en_el_articulo(articulo)
    if faltantes:
        raise ArticuloIncompletoError(campos=faltantes)
