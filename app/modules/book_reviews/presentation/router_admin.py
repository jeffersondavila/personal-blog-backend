"""Endpoints administrativos de las reviews (`Task/012`).

    GET    /api/v1/admin/book-reviews
    POST   /api/v1/admin/book-reviews
    GET    /api/v1/admin/book-reviews/{review_id}
    PUT    /api/v1/admin/book-reviews/{review_id}
    POST   /api/v1/admin/book-reviews/{review_id}/publish
    POST   /api/v1/admin/book-reviews/{review_id}/unpublish
    POST   /api/v1/admin/book-reviews/{review_id}/archive

Siete rutas, como los articulos: `MVP_SCOPE.md` seccion 3.2 concede
`published -> draft` a **articulos y reviews**, y solo a ellos. Sin `DELETE`
(decision D-012-D).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, Query, status
from sqlalchemy.orm import Session

from app.api.admin import router_administrativo
from app.modules.audit.infrastructure.registro import RegistroSqlDeAuditoria
from app.modules.authentication.presentation import AdministradorRequerido, ContextoRequerido
from app.modules.book_reviews.application.administracion import (
    ActualizarReview,
    ArchivarReview,
    CrearReview,
    DespublicarReview,
    PublicarReview,
)
from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.book_reviews.infrastructure.queries import (
    contar_reviews_administrativas,
    listar_reviews_administrativas,
    obtener_review_administrativa,
)
from app.modules.book_reviews.infrastructure.repositorio import RepositorioSqlDeReviews
from app.modules.book_reviews.presentation.schemas_admin import (
    ReviewAdministrativa,
    ReviewParaGuardar,
)
from app.modules.media.presentation.acceso import AccesoAMediosDependencia
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RespuestaDeError
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina
from app.shared.reloj import RelojDelSistema

router = router_administrativo(prefix="/admin/book-reviews", tags=["administracion: reviews"])

SesionDeBaseDeDatos = Annotated[Session, Depends(get_session)]

_RESPUESTA_404: dict[int | str, dict[str, Any]] = {
    404: {"model": RespuestaDeError, "description": "La review no existe."}
}
_RESPUESTA_409: dict[int | str, dict[str, Any]] = {
    409: {
        "model": RespuestaDeError,
        "description": (
            "Conflicto de estado: slug duplicado, slug ya inmutable, transicion no "
            "permitida o borrador incompleto."
        ),
    }
}

EstadoFiltrado = Annotated[
    BookReviewStatus | None,
    Query(
        alias="status",
        description="Filtra por estado de publicacion. Ausente: los tres estados.",
    ),
]


def _repositorio(sesion: SesionDeBaseDeDatos) -> RepositorioSqlDeReviews:
    return RepositorioSqlDeReviews(sesion)


Repositorio = Annotated[RepositorioSqlDeReviews, Depends(_repositorio)]


def _auditoria(sesion: SesionDeBaseDeDatos) -> RegistroSqlDeAuditoria:
    return RegistroSqlDeAuditoria(sesion)


Auditoria = Annotated[RegistroSqlDeAuditoria, Depends(_auditoria)]


def _crear(repositorio: Repositorio, auditoria: Auditoria) -> CrearReview:
    return CrearReview(repositorio=repositorio, auditoria=auditoria)


def _actualizar(repositorio: Repositorio, auditoria: Auditoria) -> ActualizarReview:
    return ActualizarReview(repositorio=repositorio, auditoria=auditoria)


def _publicar(repositorio: Repositorio, auditoria: Auditoria) -> PublicarReview:
    return PublicarReview(repositorio=repositorio, auditoria=auditoria, reloj=RelojDelSistema())


def _despublicar(repositorio: Repositorio, auditoria: Auditoria) -> DespublicarReview:
    return DespublicarReview(repositorio=repositorio, auditoria=auditoria)


def _archivar(repositorio: Repositorio, auditoria: Auditoria) -> ArchivarReview:
    return ArchivarReview(repositorio=repositorio, auditoria=auditoria)


def _serializar(
    sesion: Session, identificador: uuid.UUID, acceso: AccesoAMediosDependencia
) -> ReviewAdministrativa:
    """Relee la review para que la respuesta salga de lo que quedo en la base."""
    review = obtener_review_administrativa(sesion, identificador)
    if review is None:  # pragma: no cover - acaba de escribirse en esta transaccion
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return ReviewAdministrativa.de_modelo(review, acceso)


@router.get(
    "",
    response_model=Pagina[ReviewAdministrativa],
    summary="Listado administrativo de reviews",
    description="Coleccion paginada con los **tres** estados, por fecha de modificacion.",
)
def listar_reviews(
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
    status_filtro: EstadoFiltrado = None,
) -> Pagina[ReviewAdministrativa]:
    """Devuelve una pagina de reviews en cualquier estado."""
    total = contar_reviews_administrativas(sesion, estado=status_filtro)
    reviews = listar_reviews_administrativas(sesion, parametros=parametros, estado=status_filtro)
    return Pagina.crear(
        items=[ReviewAdministrativa.de_modelo(item, acceso) for item in reviews],
        parametros=parametros,
        total=total,
    )


@router.post(
    "",
    response_model=ReviewAdministrativa,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un borrador de review",
    description=(
        "Solo `title` es obligatorio. Libro, autor y valoracion pueden quedar en blanco "
        "mientras la review sea un borrador (CONTENT_MODEL.md 3.3)."
    ),
    responses=_RESPUESTA_409,
)
def crear_review(
    cuerpo: ReviewParaGuardar,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[CrearReview, Depends(_crear)],
) -> ReviewAdministrativa:
    """Crea el borrador y devuelve su representacion completa."""
    identificador = caso_de_uso(
        datos=cuerpo.a_datos(), actor_id=administrador.id, contexto=contexto
    )
    return _serializar(sesion, identificador, acceso)


@router.get(
    "/{review_id}",
    response_model=ReviewAdministrativa,
    summary="Consultar una review",
    responses=_RESPUESTA_404,
)
def obtener_review(
    review_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
) -> ReviewAdministrativa:
    """Devuelve la review con ese identificador, en cualquier estado."""
    review = obtener_review_administrativa(sesion, review_id)
    if review is None:
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return ReviewAdministrativa.de_modelo(review, acceso)


@router.put(
    "/{review_id}",
    response_model=ReviewAdministrativa,
    summary="Editar una review",
    description="Reemplaza la review. **No cambia su estado de publicacion** (B.3).",
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def editar_review(
    review_id: uuid.UUID,
    cuerpo: ReviewParaGuardar,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[ActualizarReview, Depends(_actualizar)],
) -> ReviewAdministrativa:
    """Guarda la review y devuelve el resultado."""
    caso_de_uso(
        identificador=review_id,
        datos=cuerpo.a_datos(),
        actor_id=administrador.id,
        contexto=contexto,
    )
    return _serializar(sesion, review_id, acceso)


@router.post(
    "/{review_id}/publish",
    response_model=ReviewAdministrativa,
    summary="Publicar una review",
    description=(
        "Exige ademas `book_title`, `book_author` y `rating`: la valoracion puede faltar "
        "en un borrador, pero no en una review publicada (CONTENT_MODEL.md 3.3)."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def publicar_review(
    review_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[PublicarReview, Depends(_publicar)],
) -> ReviewAdministrativa:
    """Publica la review (flujo B.7)."""
    caso_de_uso(identificador=review_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, review_id, acceso)


@router.post(
    "/{review_id}/unpublish",
    response_model=ReviewAdministrativa,
    summary="Despublicar una review",
    description="Vuelve a `draft` conservando `published_at` (USER_FLOWS.md B.8).",
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def despublicar_review(
    review_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[DespublicarReview, Depends(_despublicar)],
) -> ReviewAdministrativa:
    """Despublica la review (flujo B.8)."""
    caso_de_uso(identificador=review_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, review_id, acceso)


@router.post(
    "/{review_id}/archive",
    response_model=ReviewAdministrativa,
    summary="Archivar una review",
    description="Retira la review **sin eliminarla** (USER_FLOWS.md B.9).",
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def archivar_review(
    review_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[ArchivarReview, Depends(_archivar)],
) -> ReviewAdministrativa:
    """Archiva la review (flujo B.9)."""
    caso_de_uso(identificador=review_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, review_id, acceso)
