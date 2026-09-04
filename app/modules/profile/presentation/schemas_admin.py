"""Esquemas HTTP del perfil administrativo (`Task/012`).

**No se devuelve el modelo ORM** (regla 9 de software-architecture.md seccion
3.5). Aqui esa separacion tiene un efecto concreto: `is_singleton` —el cerrojo
que garantiza que solo hay un perfil— y `photo_id` —una clave foranea— no tienen
ninguna ruta hacia una respuesta.

Que ve el administrador y el visitante no
------------------------------------------

| Campo | Publico | Admin | Por que |
| --- | :---: | :---: | --- |
| `id` | no | **si** | El panel opera sobre identificadores internos (D-012-I) |
| `created_at`, `updated_at` | no | **si** | MVP_SCOPE.md 3.1 las pide en el panel |
| `photo` | `MedioPublico` | `MedioAdministrativo` | El panel necesita **cual** imagen es |
| `is_singleton`, `photo_id` | no | **no** | Internos en los dos lados |
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.media.presentation.acceso import AccesoAMedios
from app.modules.media.presentation.schemas_admin import MedioAdministrativo
from app.modules.profile.application.administracion import (
    DatosDelPerfil,
    EnlaceSocialParaGuardar,
)
from app.modules.profile.infrastructure.models import Profile, ProfileSocialLink

LONGITUD_DE_NOMBRE = 120
LONGITUD_DE_TITULAR = 200
LONGITUD_DE_CORREO = 254
LONGITUD_DE_ETIQUETA = 60
LONGITUD_DE_URL = 2048
LONGITUD_DE_TITULO_SEO = 70
LONGITUD_DE_DESCRIPCION_SEO = 160

#: Longitud del texto alternativo, la de su columna (`data-model.md` 4.1).
LONGITUD_DE_TEXTO_ALTERNATIVO = 255

#: Tope de enlaces sociales aceptados en una peticion.
#:
#: No lo fija ninguna fuente: CONTENT_MODEL.md los describe como *"coleccion
#: configurable"*. Es una cota de tamano de peticion, no una regla de producto —
#: sin ella, un cuerpo con cien mil enlaces se aceptaria y se persistiria.
MAXIMO_DE_ENLACES = 20


class EnlaceSocialParaGuardarHTTP(BaseModel):
    """Un enlace social recibido del panel.

    **No lleva `display_order`** (decision D-012-Q): el orden es la posicion en
    la lista, asi que dos enlaces no pueden reclamar la misma posicion.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=LONGITUD_DE_ETIQUETA)
    url: str = Field(min_length=1, max_length=LONGITUD_DE_URL)


class PerfilParaGuardar(BaseModel):
    """Cuerpo de `PUT /admin/profile`.

    `extra="forbid"` mantiene la postura estricta del proyecto: una clave
    desconocida es una errata del cliente, y aceptarla en silencio hace que un
    campo que nadie implementa parezca que funciona.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=LONGITUD_DE_NOMBRE)
    headline: str | None = Field(default=None, max_length=LONGITUD_DE_TITULAR)
    biography: str = Field(default="", description="Biografia en Markdown **fuente**.")
    contact_email: str | None = Field(default=None, max_length=LONGITUD_DE_CORREO)
    photo_id: uuid.UUID | None = Field(
        default=None, description="Identificador del `MediaAsset` usado como foto."
    )
    photo_alt_text: str | None = Field(
        default=None,
        max_length=LONGITUD_DE_TEXTO_ALTERNATIVO,
        description=(
            "Texto alternativo de la foto (requisito A-04). El perfil siempre es "
            "visible, asi que la foto **debe** tener uno: si el medio todavia no lo "
            "tiene, este lo fija. Si ya tiene uno distinto, se rechaza con `409`."
        ),
    )
    seo_title: str | None = Field(default=None, max_length=LONGITUD_DE_TITULO_SEO)
    seo_description: str | None = Field(default=None, max_length=LONGITUD_DE_DESCRIPCION_SEO)
    social_links: list[EnlaceSocialParaGuardarHTTP] = Field(
        default_factory=list, max_length=MAXIMO_DE_ENLACES
    )

    @model_validator(mode="after")
    def _el_texto_alternativo_necesita_su_foto(self) -> Self:
        """Un texto alternativo sin foto no describe nada."""
        if self.photo_alt_text is not None and self.photo_id is None:
            raise ValueError("`photo_alt_text` solo tiene sentido junto a `photo_id`.")
        return self

    @field_validator("full_name")
    @classmethod
    def _nombre_no_en_blanco(cls, valor: str) -> str:
        """Un nombre de solo espacios satisface `min_length` y no es un nombre."""
        if not valor.strip():
            raise ValueError("El nombre no puede estar en blanco.")
        return valor.strip()

    def a_datos(self) -> DatosDelPerfil:
        """Traduce el cuerpo HTTP al DTO de la capa de aplicacion."""
        return DatosDelPerfil(
            full_name=self.full_name,
            headline=self.headline,
            biography=self.biography,
            contact_email=self.contact_email,
            photo_id=self.photo_id,
            photo_alt_text=self.photo_alt_text,
            seo_title=self.seo_title,
            seo_description=self.seo_description,
            social_links=tuple(
                EnlaceSocialParaGuardar(label=enlace.label, url=enlace.url)
                for enlace in self.social_links
            ),
        )


class EnlaceSocialAdministrativo(BaseModel):
    """Enlace social tal como lo devuelve el panel."""

    label: str
    url: str

    @classmethod
    def de_modelo(cls, enlace: ProfileSocialLink) -> EnlaceSocialAdministrativo:
        return cls(label=enlace.label, url=enlace.url)


class PerfilAdministrativo(BaseModel):
    """Perfil completo tal como lo ve el administrador."""

    id: uuid.UUID
    full_name: str
    headline: str | None = None
    biography: str
    contact_email: str | None = None
    photo: MedioAdministrativo | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    social_links: list[EnlaceSocialAdministrativo] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def de_modelo(cls, perfil: Profile, acceso: AccesoAMedios) -> PerfilAdministrativo:
        """Proyecta el modelo ORM sobre los campos administrativos."""
        return cls(
            id=perfil.id,
            full_name=perfil.full_name,
            headline=perfil.headline,
            biography=perfil.biography,
            contact_email=perfil.contact_email,
            photo=MedioAdministrativo.opcional(perfil.photo, acceso),
            seo_title=perfil.seo_title,
            seo_description=perfil.seo_description,
            social_links=[
                EnlaceSocialAdministrativo.de_modelo(enlace) for enlace in perfil.social_links
            ],
            created_at=perfil.created_at,
            updated_at=perfil.updated_at,
        )
