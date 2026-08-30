"""Endpoint del listado publico de videos."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.filtros_publicos import FiltrosDeContenido, filtros_de_contenido
from app.api.query_params import rechazar_parametros_desconocidos
from app.modules.media.presentation.acceso import AccesoAMediosDependencia
from app.modules.videos.infrastructure.queries import (
    contar_videos_publicados,
    listar_videos_publicados,
)
from app.modules.videos.presentation.schemas import VideoDeListado
from app.shared.database import get_session
from app.shared.errors.schemas import RESPUESTAS_DE_ERROR
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina

router = APIRouter(
    tags=["videos"],
    dependencies=[Depends(rechazar_parametros_desconocidos)],
    responses=RESPUESTAS_DE_ERROR,
)


@router.get("/videos", response_model=Pagina[VideoDeListado])
def listar_videos(
    sesion: Annotated[Session, Depends(get_session)],
    acceso: AccesoAMediosDependencia,
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
    filtros: Annotated[FiltrosDeContenido, Depends(filtros_de_contenido)],
) -> Pagina[VideoDeListado]:
    total = contar_videos_publicados(sesion, filtros=filtros)
    videos = listar_videos_publicados(sesion, parametros=parametros, filtros=filtros)
    return Pagina.crear(
        items=[VideoDeListado.de_modelo(video, acceso) for video in videos],
        parametros=parametros,
        total=total,
    )
