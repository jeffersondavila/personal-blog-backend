"""Esquemas HTTP administrativos de un proyecto (`Task/012`).

**`status` y `project_status` son dos campos distintos y no se mezclan**
(CONTENT_MODEL.md 3.5, `data-model.md` D-E). El primero es la publicacion y
**no es escribible** —vive en los subrecursos, decision D-012-A—; el segundo es
la marcha del trabajo y si lo es, con sus tres valores.

`technologies` es una lista de cadenas que **solo se muestra** (decision D-G).
No se normaliza ni se deduplica: hacerlo cambiaria lo que el administrador
escribio, y ninguna fuente lo pide.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.media.presentation.acceso import AccesoAMedios
from app.modules.media.presentation.schemas_admin import MedioAdministrativo
from app.modules.projects.application.administracion import DatosDelProyecto
from app.modules.projects.domain import ProjectStatus, ProjectWorkStatus
from app.modules.projects.infrastructure.models import (
    LONGITUD_DE_DESCRIPCION_SEO,
    LONGITUD_DE_RESUMEN,
    LONGITUD_DE_SLUG,
    LONGITUD_DE_TITULO,
    LONGITUD_DE_TITULO_SEO,
    LONGITUD_DE_URL,
    Project,
)
from app.modules.tags.presentation.schemas import EtiquetaPublica

MAXIMO_DE_ETIQUETAS = 50

#: Longitud del texto alternativo, la de su columna (`data-model.md` 4.1).
LONGITUD_DE_TEXTO_ALTERNATIVO = 255

#: Tope de tecnologias por proyecto. Cota de tamano de peticion, no regla de
#: producto: la lista *"solo se muestra"* y nadie ha fijado un maximo.
MAXIMO_DE_TECNOLOGIAS = 50

#: Longitud maxima de cada tecnologia. `JSONB` no impone ninguna (D-G lo declara
#: como *trade-off* aceptado), asi que la impone el contrato de entrada.
LONGITUD_DE_TECNOLOGIA = 60


class ProyectoParaGuardar(BaseModel):
    """Cuerpo de `POST` y `PUT` sobre `/admin/projects`."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=LONGITUD_DE_TITULO)
    slug: str | None = Field(default=None, max_length=LONGITUD_DE_SLUG)
    summary: str | None = Field(default=None, max_length=LONGITUD_DE_RESUMEN)
    content: str = Field(default="", description="Cuerpo en Markdown **fuente**.")
    featured: bool = Field(default=False)
    seo_title: str | None = Field(default=None, max_length=LONGITUD_DE_TITULO_SEO)
    seo_description: str | None = Field(default=None, max_length=LONGITUD_DE_DESCRIPCION_SEO)
    cover_id: uuid.UUID | None = Field(default=None)
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
    project_status: ProjectWorkStatus = Field(
        default=ProjectWorkStatus.ACTIVE,
        description=(
            "Marcha del trabajo: `active`, `paused` o `completed`. **No es** el estado de "
            "publicacion; son conceptos ortogonales (CONTENT_MODEL.md 3.5)."
        ),
    )
    technologies: list[str] = Field(default_factory=list, max_length=MAXIMO_DE_TECNOLOGIAS)
    repository_url: str | None = Field(default=None, max_length=LONGITUD_DE_URL)
    demo_url: str | None = Field(default=None, max_length=LONGITUD_DE_URL)

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
        if not valor.strip():
            raise ValueError("El titulo no puede estar en blanco.")
        return valor.strip()

    @field_validator("technologies")
    @classmethod
    def _tecnologias_utiles(cls, valores: list[str]) -> list[str]:
        """Una entrada en blanco en la lista no es una tecnologia."""
        for valor in valores:
            if not valor.strip():
                raise ValueError("Una tecnologia no puede estar en blanco.")
            if len(valor) > LONGITUD_DE_TECNOLOGIA:
                raise ValueError(
                    f"Una tecnologia no puede superar {LONGITUD_DE_TECNOLOGIA} caracteres."
                )
        return [valor.strip() for valor in valores]

    def a_datos(self) -> DatosDelProyecto:
        """Traduce el cuerpo HTTP al DTO de la capa de aplicacion."""
        return DatosDelProyecto(
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
            project_status=self.project_status,
            technologies=tuple(self.technologies),
            repository_url=self.repository_url,
            demo_url=self.demo_url,
        )


class ProyectoAdministrativo(BaseModel):
    """Proyecto completo tal como lo ve el panel."""

    id: uuid.UUID
    slug: str
    title: str
    summary: str | None = None
    content: str
    status: ProjectStatus
    published_at: datetime | None = None
    featured: bool
    seo_title: str | None = None
    seo_description: str | None = None
    cover: MedioAdministrativo | None = None
    tags: list[EtiquetaPublica] = Field(default_factory=list)
    project_status: ProjectWorkStatus
    technologies: list[str] = Field(default_factory=list)
    repository_url: str | None = None
    demo_url: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def de_modelo(cls, elemento: Project, acceso: AccesoAMedios) -> ProyectoAdministrativo:
        """Proyecta el modelo ORM sobre los campos administrativos."""
        return cls(
            id=elemento.id,
            slug=elemento.slug,
            title=elemento.title,
            summary=elemento.summary,
            content=elemento.content,
            status=elemento.status,
            published_at=elemento.published_at,
            featured=elemento.featured,
            seo_title=elemento.seo_title,
            seo_description=elemento.seo_description,
            cover=MedioAdministrativo.opcional(elemento.cover, acceso),
            tags=[EtiquetaPublica.de_modelo(etiqueta) for etiqueta in elemento.tags],
            project_status=elemento.project_status,
            technologies=[str(tecnologia) for tecnologia in elemento.technologies],
            repository_url=elemento.repository_url,
            demo_url=elemento.demo_url,
            created_at=elemento.created_at,
            updated_at=elemento.updated_at,
        )
