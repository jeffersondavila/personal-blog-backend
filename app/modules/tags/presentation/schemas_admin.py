"""Esquemas HTTP administrativos de una etiqueta (`Task/012`).

**El cuerpo de edicion no tiene `slug`**, y esa ausencia es la decision
**D-012-S**: el slug de una etiqueta aparece en las URL de filtro que un
visitante puede compartir (USER_FLOWS.md A.9), y la invariante 4 de
CONTENT_MODEL.md declara los slugs *"estables: cambiarlos rompe URLs y SEO"*.
B.11 habla de *renombrar*, que es el nombre visible.

Con `extra="forbid"`, enviarlo produce un `422` explicito. Es mejor que
ignorarlo: un panel que enviara `slug` y viera un `200` creeria que lo cambio.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.tags.application.administracion import (
    DatosDeLaEtiqueta,
    RenombradoDeLaEtiqueta,
)
from app.modules.tags.infrastructure.models import (
    LONGITUD_DE_DESCRIPCION,
    LONGITUD_DE_NOMBRE,
    LONGITUD_DE_SLUG,
    Tag,
)


class EtiquetaParaCrear(BaseModel):
    """Cuerpo de `POST /admin/tags`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=LONGITUD_DE_NOMBRE)
    slug: str | None = Field(
        default=None,
        max_length=LONGITUD_DE_SLUG,
        description="Opcional: si falta, se propone a partir del nombre.",
    )
    description: str | None = Field(default=None, max_length=LONGITUD_DE_DESCRIPCION)

    @field_validator("name")
    @classmethod
    def _nombre_no_en_blanco(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("El nombre no puede estar en blanco.")
        return valor.strip()

    def a_datos(self) -> DatosDeLaEtiqueta:
        """Traduce el cuerpo HTTP al DTO de la capa de aplicacion."""
        return DatosDeLaEtiqueta(name=self.name, slug=self.slug, description=self.description)


class EtiquetaParaRenombrar(BaseModel):
    """Cuerpo de `PUT /admin/tags/{tag_id}`. **Sin `slug`** (decision D-012-S)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=LONGITUD_DE_NOMBRE)
    description: str | None = Field(default=None, max_length=LONGITUD_DE_DESCRIPCION)

    @field_validator("name")
    @classmethod
    def _nombre_no_en_blanco(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("El nombre no puede estar en blanco.")
        return valor.strip()

    def a_datos(self) -> RenombradoDeLaEtiqueta:
        """Traduce el cuerpo HTTP al DTO de la capa de aplicacion."""
        return RenombradoDeLaEtiqueta(name=self.name, description=self.description)


class EtiquetaAdministrativa(BaseModel):
    """Etiqueta tal como la ve el panel.

    Anade `id` —el panel opera sobre identificadores internos (D-012-I) y lo
    envia como `tag_ids`— y las fechas de gestion, sobre los tres campos que ya
    expone `EtiquetaPublica`.
    """

    id: uuid.UUID
    slug: str
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def de_modelo(cls, etiqueta: Tag) -> EtiquetaAdministrativa:
        """Proyecta el modelo ORM sobre los campos administrativos."""
        return cls(
            id=etiqueta.id,
            slug=etiqueta.slug,
            name=etiqueta.name,
            description=etiqueta.description,
            created_at=etiqueta.created_at,
            updated_at=etiqueta.updated_at,
        )
