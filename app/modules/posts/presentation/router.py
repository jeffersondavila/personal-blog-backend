"""Endpoints publicos de articulos.

`GET /api/v1/posts` y `GET /api/v1/posts/{slug}` (api-contracts.md seccion 3).

**Endpoints delgados** (software-architecture.md seccion 3.5, regla 2): validan
la entrada —lo hace el propio tipado declarativo—, invocan la consulta y
serializan. No deciden que es visible: eso lo expresa la consulta.

Por que no hay capa `application` (decision D-009-Q)
----------------------------------------------------

software-architecture.md seccion 3.2 dice que **no** todos los modulos necesitan
las cuatro capas y que **crear capas vacias esta prohibido**. Un caso de uso de
solo lectura seria aqui una funcion que reenvia sus argumentos: no orquesta
nada, no protege ninguna invariante y no abre ningun limite transaccional. La
regla de negocio real —solo se publica lo publicado— vive dentro de la consulta,
que es donde no puede saltarsela nadie.

`Task/012` trae escritura, validacion de publicacion y auditoria. Ahi la capa
`application` deja de estar vacia y se crea entonces, con trabajo que hacer.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.filtros_publicos import FiltrosDeContenido, filtros_de_contenido
from app.api.query_params import rechazar_parametros_desconocidos
from app.modules.posts.infrastructure.queries import (
    contar_articulos_publicados,
    listar_articulos_publicados,
    obtener_articulo_publicado,
)
from app.modules.posts.presentation.schemas import PostDeListado, PostDetallado
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RESPUESTAS_DE_ERROR, RespuestaDeError
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina

router = APIRouter(
    tags=["posts"],
    dependencies=[Depends(rechazar_parametros_desconocidos)],
    # Sustituye la forma de `422` que FastAPI documenta por su cuenta por la
    # envoltura de error real del proyecto (api-contracts.md seccion 7).
    responses=RESPUESTAS_DE_ERROR,
)


@router.get(
    "/posts",
    response_model=Pagina[PostDeListado],
    summary="Listado de articulos publicados",
    description=(
        "Coleccion paginada de articulos en estado `published`. "
        "Los borradores y los archivados no aparecen en ningun caso."
    ),
)
def listar_articulos(
    sesion: Annotated[Session, Depends(get_session)],
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
    filtros: Annotated[FiltrosDeContenido, Depends(filtros_de_contenido)],
) -> Pagina[PostDeListado]:
    """Devuelve una pagina de articulos publicados."""
    total = contar_articulos_publicados(sesion, filtros=filtros)
    articulos = listar_articulos_publicados(sesion, parametros=parametros, filtros=filtros)
    return Pagina.crear(
        items=[PostDeListado.de_modelo(articulo) for articulo in articulos],
        parametros=parametros,
        total=total,
    )


@router.get(
    "/posts/{slug}",
    response_model=PostDetallado,
    summary="Articulo publicado",
    description=(
        "Devuelve un articulo publicado. Un slug inexistente y un slug existente "
        "pero no publicado producen exactamente el mismo `404`."
    ),
    responses={
        404: {
            "model": RespuestaDeError,
            "description": "El articulo no existe o no es visible.",
        }
    },
)
def obtener_articulo(
    slug: str,
    sesion: Annotated[Session, Depends(get_session)],
) -> PostDetallado:
    """Devuelve el articulo publicado con ese slug."""
    articulo = obtener_articulo_publicado(sesion, slug=slug)
    if articulo is None:
        # Mensaje deliberadamente generico y comun a los tres casos: inexistente,
        # borrador y archivado. Un texto distinto por caso permitiria enumerar
        # borradores probando slugs (api-contracts.md seccion 3).
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return PostDetallado.de_modelo(articulo)
