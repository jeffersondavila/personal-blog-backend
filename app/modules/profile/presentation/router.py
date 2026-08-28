"""Endpoint publico del perfil."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.query_params import rechazar_parametros_desconocidos
from app.modules.profile.infrastructure.queries import obtener_perfil
from app.modules.profile.presentation.schemas import ProfilePublico
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RESPUESTAS_DE_ERROR, RespuestaDeError

router = APIRouter(
    tags=["profile"],
    dependencies=[Depends(rechazar_parametros_desconocidos)],
    responses=RESPUESTAS_DE_ERROR,
)


@router.get(
    "/profile",
    response_model=ProfilePublico,
    summary="Perfil publico",
    responses={404: {"model": RespuestaDeError, "description": "El perfil aun no existe."}},
)
def leer_perfil(sesion: Annotated[Session, Depends(get_session)]) -> ProfilePublico:
    profile = obtener_perfil(sesion)
    if profile is None:
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return ProfilePublico.de_modelo(profile)
