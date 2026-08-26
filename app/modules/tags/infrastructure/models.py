"""Modelo ORM de las etiquetas y de su asociacion con el contenido.

`tags` es el modulo transversal: es dueno de la etiqueta **y de su asociacion
con contenido** (software-architecture.md seccion 3.3). Por eso las cuatro
tablas puente viven aqui y no repartidas por cada tipo de contenido.

Las claves foraneas hacia `posts`, `book_reviews`, `videos` y `projects` se
declaran **por nombre de tabla**, no importando sus modelos: SQLAlchemy las
resuelve al compilar los metadatos. Asi este modulo no depende de los de
contenido, y son ellos los que dependen de el: una sola direccion, sin ciclo.

Regla de negocio que materializan estas tablas
----------------------------------------------

**Eliminar una etiqueta desasocia contenido; nunca lo elimina**
(CONTENT_MODEL.md seccion 3.6). El `ON DELETE CASCADE` de las tablas puente borra
**filas de asociacion**, que es exactamente lo que debe desaparecer; el contenido
cuelga de su propia tabla y no se ve afectado. La cascada aqui no es un atajo
peligroso: es la unica forma de que una etiqueta pueda borrarse sin dejar
referencias rotas.
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, String, Table, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UuidPrimaryKeyMixin

LONGITUD_DE_SLUG = 160
LONGITUD_DE_NOMBRE = 80
LONGITUD_DE_DESCRIPCION = 500


class Tag(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Etiqueta de clasificacion transversal."""

    __tablename__ = "tags"

    #: Identificador legible usado en las URL de filtro (`?tag={slug}`).
    #: Unico, y estable: cambiarlo rompe URLs y SEO (requisito E-01).
    slug: Mapped[str] = mapped_column(String(LONGITUD_DE_SLUG), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(LONGITUD_DE_NOMBRE), nullable=False)
    description: Mapped[str | None] = mapped_column(String(LONGITUD_DE_DESCRIPCION))


def _tabla_de_asociacion(nombre: str, columna_de_contenido: str, tabla_de_contenido: str) -> Table:
    """Construye una tabla puente entre un tipo de contenido y `tags`.

    Las cuatro son identicas salvo en los nombres, y se construyen desde una
    sola definicion para que no puedan divergir por descuido: el dia que cambie
    la politica de borrado, cambia en un sitio.

    Decisiones que aplica a las cuatro:

    - **Clave primaria compuesta** `(contenido, etiqueta)`. Es lo que rechaza una
      asociacion duplicada, y de paso da el indice de "las etiquetas de este
      contenido".
    - **`ON DELETE CASCADE` en ambos lados.** Borrar la etiqueta o el contenido
      retira la asociacion; ninguno de los dos arrastra al otro.
    - **Indice propio sobre `tag_id`.** El indice de la clave primaria empieza por
      la columna de contenido y no sirve para la consulta inversa —"que contenido
      lleva esta etiqueta"—, que es justo el filtro publico por etiqueta
      (USER_FLOWS.md A.9).
    """
    return Table(
        nombre,
        Base.metadata,
        Column(
            columna_de_contenido,
            Uuid,
            ForeignKey(f"{tabla_de_contenido}.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        Column(
            "tag_id",
            Uuid,
            ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        Index(f"ix_{nombre}_tag_id", "tag_id"),
    )


post_tags = _tabla_de_asociacion("post_tags", "post_id", "posts")
book_review_tags = _tabla_de_asociacion("book_review_tags", "book_review_id", "book_reviews")
video_tags = _tabla_de_asociacion("video_tags", "video_id", "videos")
project_tags = _tabla_de_asociacion("project_tags", "project_id", "projects")
