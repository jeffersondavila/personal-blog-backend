"""Endpoints publicos de reviews de libros."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.filtros_publicos import FiltrosDeContenido, filtros_de_contenido
from app.api.query_params import rechazar_parametros_desconocidos
from app.modules.book_reviews.infrastructure.queries import (
    contar_reviews_publicadas,
    listar_reviews_publicadas,
    obtener_review_publicada,
)
from app.modules.book_reviews.presentation.schemas import ReviewDeListado, ReviewDetallada
from app.modules.media.presentation.acceso import AccesoAMediosDependencia
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RESPUESTAS_DE_ERROR, RespuestaDeError
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina

router = APIRouter(
    tags=["book-reviews"],
    dependencies=[Depends(rechazar_parametros_desconocidos)],
    responses=RESPUESTAS_DE_ERROR,
)


@router.get("/book-reviews", response_model=Pagina[ReviewDeListado])
def listar_reviews(
    sesion: Annotated[Session, Depends(get_session)],
    acceso: AccesoAMediosDependencia,
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
    filtros: Annotated[FiltrosDeContenido, Depends(filtros_de_contenido)],
) -> Pagina[ReviewDeListado]:
    total = contar_reviews_publicadas(sesion, filtros=filtros)
    reviews = listar_reviews_publicadas(sesion, parametros=parametros, filtros=filtros)
    return Pagina.crear(
        items=[ReviewDeListado.de_modelo(review, acceso) for review in reviews],
        parametros=parametros,
        total=total,
    )


@router.get(
    "/book-reviews/{slug}",
    response_model=ReviewDetallada,
    responses={404: {"model": RespuestaDeError, "description": "Review no visible."}},
)
def obtener_review(
    slug: str,
    sesion: Annotated[Session, Depends(get_session)],
    acceso: AccesoAMediosDependencia,
) -> ReviewDetallada:
    review = obtener_review_publicada(sesion, slug=slug)
    if review is None:
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return ReviewDetallada.de_modelo(review, acceso)
