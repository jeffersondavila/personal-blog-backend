"""Endpoints publicos de proyectos."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.filtros_publicos import FiltrosDeContenido, filtros_de_contenido
from app.api.query_params import rechazar_parametros_desconocidos
from app.modules.projects.infrastructure.queries import (
    contar_proyectos_publicados,
    listar_proyectos_publicados,
    obtener_proyecto_publicado,
)
from app.modules.projects.presentation.schemas import ProyectoDeListado, ProyectoDetallado
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RESPUESTAS_DE_ERROR, RespuestaDeError
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina

router = APIRouter(
    tags=["projects"],
    dependencies=[Depends(rechazar_parametros_desconocidos)],
    responses=RESPUESTAS_DE_ERROR,
)


@router.get("/projects", response_model=Pagina[ProyectoDeListado])
def listar_proyectos(
    sesion: Annotated[Session, Depends(get_session)],
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
    filtros: Annotated[FiltrosDeContenido, Depends(filtros_de_contenido)],
) -> Pagina[ProyectoDeListado]:
    total = contar_proyectos_publicados(sesion, filtros=filtros)
    projects = listar_proyectos_publicados(sesion, parametros=parametros, filtros=filtros)
    return Pagina.crear(
        items=[ProyectoDeListado.de_modelo(project) for project in projects],
        parametros=parametros,
        total=total,
    )


@router.get(
    "/projects/{slug}",
    response_model=ProyectoDetallado,
    responses={404: {"model": RespuestaDeError, "description": "Proyecto no visible."}},
)
def obtener_proyecto(
    slug: str,
    sesion: Annotated[Session, Depends(get_session)],
) -> ProyectoDetallado:
    project = obtener_proyecto_publicado(sesion, slug=slug)
    if project is None:
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return ProyectoDetallado.de_modelo(project)
