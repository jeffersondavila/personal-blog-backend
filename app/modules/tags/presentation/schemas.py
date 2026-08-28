"""Representacion publica de una etiqueta.

El modulo `tags` es dueno de la etiqueta y de su asociacion con el contenido
(software-architecture.md seccion 3.3), asi que este esquema vive aqui y los
cuatro tipos de contenido lo reutilizan en lugar de definir cada uno el suyo.

No se expone `id`: el filtro publico se hace por `slug` (`?tag={slug}`,
USER_FLOWS.md A.9) y el identificador interno pertenece a la API administrativa.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.tags.infrastructure.models import Tag


class EtiquetaPublica(BaseModel):
    """Etiqueta tal como la ve un visitante."""

    slug: str = Field(description="Identificador legible usado en las URL de filtro.")
    name: str = Field(description="Nombre visible.")
    description: str | None = Field(default=None, description="Descripcion opcional.")

    @classmethod
    def de_modelo(cls, etiqueta: Tag) -> EtiquetaPublica:
        """Construye la representacion publica de una etiqueta."""
        return cls(slug=etiqueta.slug, name=etiqueta.name, description=etiqueta.description)
