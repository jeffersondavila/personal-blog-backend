"""Consulta publica del perfil singleton."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.modules.profile.infrastructure.models import Profile


def obtener_perfil(sesion: Session) -> Profile | None:
    """Obtiene el unico perfil con sus relaciones publicas cargadas."""
    sentencia = (
        select(Profile)
        .options(joinedload(Profile.photo), selectinload(Profile.social_links))
        .limit(1)
    )
    return sesion.execute(sentencia).scalar_one_or_none()
