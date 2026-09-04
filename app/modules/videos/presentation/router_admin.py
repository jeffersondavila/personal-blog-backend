"""Endpoints administrativos de los videos (`Task/012`).

    GET    /api/v1/admin/videos
    POST   /api/v1/admin/videos
    GET    /api/v1/admin/videos/{video_id}
    PUT    /api/v1/admin/videos/{video_id}
    POST   /api/v1/admin/videos/{video_id}/publish
    POST   /api/v1/admin/videos/{video_id}/archive

**Seis rutas, no siete: no existe `/unpublish`.** `MVP_SCOPE.md` seccion 3.2
concede `published -> draft` a articulos y reviews **y solo a ellos**, y los
videos *"se archivan"*. `Task/008` expreso esa diferencia por **ausencia del
metodo** en el dominio; aqui se expresa por ausencia de la ruta, de modo que la
especificacion OpenAPI tampoco la anuncia. Una transicion que no existe no puede
invocarse por error ni habilitarse por descuido.

Sin `DELETE` (decision D-012-D).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, Query, status
from sqlalchemy.orm import Session

from app.api.admin import router_administrativo
from app.modules.audit.infrastructure.registro import RegistroSqlDeAuditoria
from app.modules.authentication.presentation import AdministradorRequerido, ContextoRequerido
from app.modules.media.presentation.acceso import AccesoAMediosDependencia
from app.modules.videos.application.administracion import (
    ActualizarVideo,
    ArchivarVideo,
    CrearVideo,
    PublicarVideo,
)
from app.modules.videos.domain import VideoStatus
from app.modules.videos.infrastructure.queries import (
    contar_videos_administrativos,
    listar_videos_administrativos,
    obtener_video_administrativo,
)
from app.modules.videos.infrastructure.repositorio import RepositorioSqlDeVideos
from app.modules.videos.presentation.schemas_admin import VideoAdministrativo, VideoParaGuardar
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RespuestaDeError
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina
from app.shared.reloj import RelojDelSistema

router = router_administrativo(prefix="/admin/videos", tags=["administracion: videos"])

SesionDeBaseDeDatos = Annotated[Session, Depends(get_session)]

_RESPUESTA_404: dict[int | str, dict[str, Any]] = {
    404: {"model": RespuestaDeError, "description": "El video no existe."}
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
    VideoStatus | None,
    Query(
        alias="status",
        description="Filtra por estado de publicacion. Ausente: los tres estados.",
    ),
]


def _repositorio(sesion: SesionDeBaseDeDatos) -> RepositorioSqlDeVideos:
    return RepositorioSqlDeVideos(sesion)


Repositorio = Annotated[RepositorioSqlDeVideos, Depends(_repositorio)]


def _auditoria(sesion: SesionDeBaseDeDatos) -> RegistroSqlDeAuditoria:
    return RegistroSqlDeAuditoria(sesion)


Auditoria = Annotated[RegistroSqlDeAuditoria, Depends(_auditoria)]


def _crear(repositorio: Repositorio, auditoria: Auditoria) -> CrearVideo:
    return CrearVideo(repositorio=repositorio, auditoria=auditoria)


def _actualizar(repositorio: Repositorio, auditoria: Auditoria) -> ActualizarVideo:
    return ActualizarVideo(repositorio=repositorio, auditoria=auditoria)


def _publicar(repositorio: Repositorio, auditoria: Auditoria) -> PublicarVideo:
    return PublicarVideo(repositorio=repositorio, auditoria=auditoria, reloj=RelojDelSistema())


def _archivar(repositorio: Repositorio, auditoria: Auditoria) -> ArchivarVideo:
    return ArchivarVideo(repositorio=repositorio, auditoria=auditoria)


def _serializar(
    sesion: Session, identificador: uuid.UUID, acceso: AccesoAMediosDependencia
) -> VideoAdministrativo:
    """Relee el video para que la respuesta salga de lo que quedo en la base."""
    elemento = obtener_video_administrativo(sesion, identificador)
    if elemento is None:  # pragma: no cover - acaba de escribirse en esta transaccion
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return VideoAdministrativo.de_modelo(elemento, acceso)


@router.get(
    "",
    response_model=Pagina[VideoAdministrativo],
    summary="Listado administrativo de videos",
    description="Coleccion paginada con los **tres** estados, por fecha de modificacion.",
)
def listar_videos(
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
    status_filtro: EstadoFiltrado = None,
) -> Pagina[VideoAdministrativo]:
    """Devuelve una pagina de videos en cualquier estado."""
    total = contar_videos_administrativos(sesion, estado=status_filtro)
    elementos = listar_videos_administrativos(sesion, parametros=parametros, estado=status_filtro)
    return Pagina.crear(
        items=[VideoAdministrativo.de_modelo(item, acceso) for item in elementos],
        parametros=parametros,
        total=total,
    )


@router.post(
    "",
    response_model=VideoAdministrativo,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un borrador de video",
    description=(
        "Solo `title` es obligatorio. **No admite `content`**: el contenido principal de "
        "un video es el video externo (ADR-005)."
    ),
    responses=_RESPUESTA_409,
)
def crear_video(
    cuerpo: VideoParaGuardar,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[CrearVideo, Depends(_crear)],
) -> VideoAdministrativo:
    """Crea el borrador y devuelve su representacion completa."""
    identificador = caso_de_uso(
        datos=cuerpo.a_datos(), actor_id=administrador.id, contexto=contexto
    )
    return _serializar(sesion, identificador, acceso)


@router.get(
    "/{video_id}",
    response_model=VideoAdministrativo,
    summary="Consultar un video",
    responses=_RESPUESTA_404,
)
def obtener_video(
    video_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
) -> VideoAdministrativo:
    """Devuelve el video con ese identificador, en cualquier estado."""
    elemento = obtener_video_administrativo(sesion, video_id)
    if elemento is None:
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return VideoAdministrativo.de_modelo(elemento, acceso)


@router.put(
    "/{video_id}",
    response_model=VideoAdministrativo,
    summary="Editar un video",
    description="Reemplaza el video. **No cambia su estado de publicacion** (B.3).",
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def editar_video(
    video_id: uuid.UUID,
    cuerpo: VideoParaGuardar,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[ActualizarVideo, Depends(_actualizar)],
) -> VideoAdministrativo:
    """Guarda el video y devuelve el resultado."""
    caso_de_uso(
        identificador=video_id,
        datos=cuerpo.a_datos(),
        actor_id=administrador.id,
        contexto=contexto,
    )
    return _serializar(sesion, video_id, acceso)


@router.post(
    "/{video_id}/publish",
    response_model=VideoAdministrativo,
    summary="Publicar un video",
    description=(
        "Exige `provider` y `video_url`: son el equivalente del *contenido* para un tipo "
        "que no tiene Markdown. La pertenencia a una lista de proveedores es de `Task/014`."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def publicar_video(
    video_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[PublicarVideo, Depends(_publicar)],
) -> VideoAdministrativo:
    """Publica el video (flujo B.7)."""
    caso_de_uso(identificador=video_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, video_id, acceso)


@router.post(
    "/{video_id}/archive",
    response_model=VideoAdministrativo,
    summary="Archivar un video",
    description=(
        "Retira el video **sin eliminarlo** (USER_FLOWS.md B.9). Es la unica forma de "
        "retirar un video: no se despublica."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def archivar_video(
    video_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[ArchivarVideo, Depends(_archivar)],
) -> VideoAdministrativo:
    """Archiva el video (flujo B.9)."""
    caso_de_uso(identificador=video_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, video_id, acceso)
