"""Endpoint de busqueda publica."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import StringConstraints
from sqlalchemy.orm import Session

from app.api.query_params import rechazar_parametros_desconocidos
from app.modules.search.infrastructure.queries import buscar, contar_resultados
from app.modules.search.presentation.schemas import ResultadoDeBusqueda
from app.shared.database import get_session
from app.shared.errors.schemas import RESPUESTAS_DE_ERROR
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina

TerminoDeBusqueda = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=100),
]

router = APIRouter(
    tags=["search"],
    dependencies=[Depends(rechazar_parametros_desconocidos)],
    responses=RESPUESTAS_DE_ERROR,
)


@router.get("/search", response_model=Pagina[ResultadoDeBusqueda])
def buscar_contenido(
    q: Annotated[TerminoDeBusqueda, Query(description="Termino de busqueda literal.")],
    sesion: Annotated[Session, Depends(get_session)],
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
) -> Pagina[ResultadoDeBusqueda]:
    total = contar_resultados(sesion, termino=q)
    filas = buscar(sesion, termino=q, parametros=parametros)
    return Pagina.crear(
        items=[ResultadoDeBusqueda.de_fila(fila) for fila in filas],
        parametros=parametros,
        total=total,
    )
