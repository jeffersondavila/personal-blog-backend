"""Esquemas HTTP administrativos de un articulo (`Task/012`).

**No se devuelve el modelo ORM** (regla 9 de software-architecture.md seccion
3.5). Aqui se declara, campo a campo, lo que entra y lo que sale.

Que cambia respecto del contrato publico
-----------------------------------------

| Campo | Publico | Admin | Por que |
| --- | :---: | :---: | --- |
| `id` | no | **si** | El panel opera sobre identificadores internos (D-012-I) |
| `status` | no | **si** | Es lo que el panel muestra y lo que filtra |
| `created_at`, `updated_at` | no | **si** | MVP_SCOPE.md 3.1 las pide en el panel |
| `content` | solo en detalle | **siempre** | El panel edita el Markdown |
| `cover` | `MedioPublico` | `MedioAdministrativo` | El panel necesita **cual** imagen es |
| `cover_id` | no | **no** | Es una clave foranea; sale dentro de `cover` |

Lo que **no** es escribible
---------------------------

`status`, `published_at`, `created_at` y `updated_at`. Los dos primeros son del
ciclo de vida, que vive en los subrecursos (decision **D-012-A**); los dos
ultimos los escribe la base. `extra="forbid"` convierte enviarlos en un `422`
explicito en lugar de en una escritura silenciosamente ignorada.

El Markdown viaja **fuente**, sin renderizar ni sanitizar: eso es de `Task/014`
y `Task/015` (ADR-005), igual que en la API publica.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.media.presentation.acceso import AccesoAMedios
from app.modules.media.presentation.schemas_admin import MedioAdministrativo
from app.modules.posts.application.administracion import DatosDelArticulo
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import (
    LONGITUD_DE_DESCRIPCION_SEO,
    LONGITUD_DE_RESUMEN,
    LONGITUD_DE_SLUG,
    LONGITUD_DE_TITULO,
    LONGITUD_DE_TITULO_SEO,
    Post,
)
from app.modules.tags.presentation.schemas import EtiquetaPublica

#: Tope de etiquetas por contenido. No lo fija ninguna fuente: es una cota de
#: tamano de peticion, no una regla de producto.
MAXIMO_DE_ETIQUETAS = 50

#: Longitud del texto alternativo, la de su columna (`data-model.md` 4.1).
LONGITUD_DE_TEXTO_ALTERNATIVO = 255


class ArticuloParaGuardar(BaseModel):
    """Cuerpo de `POST` y `PUT` sobre `/admin/posts`.

    Solo `title` es obligatorio: USER_FLOWS.md B.2 dice que un borrador nace con
    el titulo y el slug propuesto, y `data-model.md` 4.4.1 razona que exigir
    cualquier otra columna obligaria a **inventar** un dato.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=LONGITUD_DE_TITULO)
    slug: str | None = Field(
        default=None,
        max_length=LONGITUD_DE_SLUG,
        description="Opcional: si falta, se propone a partir del titulo (B.2).",
    )
    summary: str | None = Field(default=None, max_length=LONGITUD_DE_RESUMEN)
    content: str = Field(default="", description="Cuerpo en Markdown **fuente**.")
    featured: bool = Field(default=False, description="Aparece destacado en Inicio.")
    seo_title: str | None = Field(default=None, max_length=LONGITUD_DE_TITULO_SEO)
    seo_description: str | None = Field(default=None, max_length=LONGITUD_DE_DESCRIPCION_SEO)
    cover_id: uuid.UUID | None = Field(
        default=None, description="Identificador del `MediaAsset` usado como portada."
    )
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAXIMO_DE_ETIQUETAS)
    cover_alt_text: str | None = Field(
        default=None,
        max_length=LONGITUD_DE_TEXTO_ALTERNATIVO,
        description=(
            "Texto alternativo de la portada (requisito A-04). Se escribe en el **primer "
            "uso** de la imagen: si el medio todavia no tiene texto, este lo fija. Si ya "
            "tiene uno distinto, la peticion se rechaza con `409`; no se sobrescribe."
        ),
    )

    @model_validator(mode="after")
    def _el_texto_alternativo_necesita_su_imagen(self) -> Self:
        """Un texto alternativo sin imagen no describe nada.

        Se rechaza en lugar de ignorarse: un campo que no hace nada haria creer
        al panel que guardo algo. Misma postura estricta que `extra="forbid"`.
        """
        if self.cover_alt_text is not None and self.cover_id is None:
            raise ValueError("`cover_alt_text` solo tiene sentido junto a `cover_id`.")
        return self

    @field_validator("title")
    @classmethod
    def _titulo_no_en_blanco(cls, valor: str) -> str:
        """Un titulo de solo espacios satisface `min_length` y no es un titulo."""
        if not valor.strip():
            raise ValueError("El titulo no puede estar en blanco.")
        return valor.strip()

    def a_datos(self) -> DatosDelArticulo:
        """Traduce el cuerpo HTTP al DTO de la capa de aplicacion."""
        return DatosDelArticulo(
            title=self.title,
            slug=self.slug,
            summary=self.summary,
            content=self.content,
            featured=self.featured,
            seo_title=self.seo_title,
            seo_description=self.seo_description,
            cover_id=self.cover_id,
            tag_ids=tuple(self.tag_ids),
            imagen_alt_text=self.cover_alt_text,
        )


class ArticuloAdministrativo(BaseModel):
    """Articulo completo tal como lo ve el panel."""

    id: uuid.UUID
    slug: str
    title: str
    summary: str | None = None
    content: str
    status: PostStatus
    published_at: datetime | None = None
    featured: bool
    seo_title: str | None = None
    seo_description: str | None = None
    cover: MedioAdministrativo | None = None
    tags: list[EtiquetaPublica] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def de_modelo(cls, articulo: Post, acceso: AccesoAMedios) -> ArticuloAdministrativo:
        """Proyecta el modelo ORM sobre los campos administrativos."""
        return cls(
            id=articulo.id,
            slug=articulo.slug,
            title=articulo.title,
            summary=articulo.summary,
            content=articulo.content,
            status=articulo.status,
            published_at=articulo.published_at,
            featured=articulo.featured,
            seo_title=articulo.seo_title,
            seo_description=articulo.seo_description,
            cover=MedioAdministrativo.opcional(articulo.cover, acceso),
            tags=[EtiquetaPublica.de_modelo(etiqueta) for etiqueta in articulo.tags],
            created_at=articulo.created_at,
            updated_at=articulo.updated_at,
        )
