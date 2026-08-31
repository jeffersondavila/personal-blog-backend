"""Esquemas publicos de un articulo.

**No se devuelve el modelo ORM.** Es la regla 9 de software-architecture.md
seccion 3.5, y no es una formalidad: el modelo tiene `status`, `id`, `cover_id`
y las marcas de tiempo, y cualquiera de esos campos acabaria publicado por el
simple hecho de existir en la tabla. Aqui se declara, campo a campo, lo que sale.

Dos esquemas y no uno (decision D-009-P)
----------------------------------------

| | Listado | Detalle |
| --- | :---: | :---: |
| `content` (Markdown) | no | si |
| `reading_time_minutes` | no | si |
| SEO | no | si |

El listado **no carga el Markdown**: traer el cuerpo completo de doce articulos
para pintar sus resumenes contradice el requisito P-08. El SEO alimenta las
etiquetas `title`, `description` y Open Graph de una pagina propia
(USER_FLOWS.md A.3), y un elemento de listado no tiene pagina propia.

`Task/009` transporta el Markdown **fuente**. No lo renderiza ni lo sanitiza:
eso es de `Task/014` y `Task/015` (ADR-005).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.media.presentation.acceso import AccesoAMedios
from app.modules.media.presentation.schemas import MedioPublico
from app.modules.posts.infrastructure.models import Post
from app.modules.tags.presentation.schemas import EtiquetaPublica
from app.shared.lectura import minutos_de_lectura


class PostDeListado(BaseModel):
    """Articulo tal como aparece en un listado (USER_FLOWS.md A.2)."""

    slug: str = Field(description="Identificador legible y estable.")
    title: str = Field(description="Titulo del articulo.")
    summary: str | None = Field(default=None, description="Resumen breve.")
    published_at: datetime | None = Field(
        default=None, description="Fecha de la primera publicacion, en UTC."
    )
    tags: list[EtiquetaPublica] = Field(default_factory=list, description="Etiquetas asociadas.")
    cover: MedioPublico | None = Field(default=None, description="Portada, si tiene.")

    @classmethod
    def de_modelo(cls, articulo: Post, acceso: AccesoAMedios) -> PostDeListado:
        """Proyecta el modelo ORM sobre los campos publicos del listado."""
        return cls(
            slug=articulo.slug,
            title=articulo.title,
            summary=articulo.summary,
            published_at=articulo.published_at,
            tags=[EtiquetaPublica.de_modelo(etiqueta) for etiqueta in articulo.tags],
            cover=MedioPublico.de_modelo(articulo.cover, acceso),
        )


class PostDetallado(PostDeListado):
    """Articulo completo (USER_FLOWS.md A.3)."""

    content: str = Field(description="Cuerpo en Markdown **fuente**, sin renderizar.")
    reading_time_minutes: int = Field(
        description="Tiempo estimado de lectura. Derivado del contenido, no persistido."
    )
    seo_title: str | None = Field(default=None, description="Titulo para buscadores.")
    seo_description: str | None = Field(default=None, description="Descripcion para buscadores.")

    @classmethod
    def de_modelo(cls, articulo: Post, acceso: AccesoAMedios) -> PostDetallado:
        """Proyecta el modelo ORM sobre los campos publicos del detalle."""
        return cls(
            slug=articulo.slug,
            title=articulo.title,
            summary=articulo.summary,
            published_at=articulo.published_at,
            tags=[EtiquetaPublica.de_modelo(etiqueta) for etiqueta in articulo.tags],
            cover=MedioPublico.de_modelo(articulo.cover, acceso),
            content=articulo.content,
            reading_time_minutes=minutos_de_lectura(articulo.content),
            seo_title=articulo.seo_title,
            seo_description=articulo.seo_description,
        )
