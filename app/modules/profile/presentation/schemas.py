"""DTO publicos del perfil."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.media.presentation.schemas import MedioPublico
from app.modules.profile.infrastructure.models import Profile, ProfileSocialLink


class EnlaceSocialPublico(BaseModel):
    """Enlace social sin identidad ni orden interno."""

    label: str = Field(description="Nombre visible del enlace.")
    url: str = Field(description="Destino del enlace.")

    @classmethod
    def de_modelo(cls, enlace: ProfileSocialLink) -> EnlaceSocialPublico:
        return cls(label=enlace.label, url=enlace.url)


class ProfilePublico(BaseModel):
    """Identidad publica del autor."""

    full_name: str
    headline: str | None = None
    biography: str
    contact_email: str | None = None
    photo: MedioPublico | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    social_links: list[EnlaceSocialPublico] = Field(default_factory=list)

    @classmethod
    def de_modelo(cls, profile: Profile) -> ProfilePublico:
        return cls(
            full_name=profile.full_name,
            headline=profile.headline,
            biography=profile.biography,
            contact_email=profile.contact_email,
            photo=MedioPublico.de_modelo(profile.photo),
            seo_title=profile.seo_title,
            seo_description=profile.seo_description,
            social_links=[EnlaceSocialPublico.de_modelo(item) for item in profile.social_links],
        )
