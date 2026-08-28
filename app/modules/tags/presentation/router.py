"""Endpoint del catalogo publico de etiquetas."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.query_params import rechazar_parametros_desconocidos
from app.modules.tags.infrastructure.queries import (
    contar_etiquetas_disponibles,
    listar_etiquetas_disponibles,
)
from app.modules.tags.presentation.schemas import EtiquetaPublica
from app.shared.database import get_session
from app.shared.errors.schemas import RESPUESTAS_DE_ERROR
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina

router = APIRouter(
    tags=["tags"],
    dependencies=[Depends(rechazar_parametros_desconocidos)],
    responses=RESPUESTAS_DE_ERROR,
)


@router.get("/tags", response_model=Pagina[EtiquetaPublica])
def listar_etiquetas(
    sesion: Annotated[Session, Depends(get_session)],
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
) -> Pagina[EtiquetaPublica]:
    total = contar_etiquetas_disponibles(sesion)
    tags = listar_etiquetas_disponibles(sesion, parametros=parametros)
    return Pagina.crear(
        items=[EtiquetaPublica.de_modelo(tag) for tag in tags],
        parametros=parametros,
        total=total,
    )
