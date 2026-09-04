"""Endpoints administrativos de los proyectos (`Task/012`).

    GET    /api/v1/admin/projects
    POST   /api/v1/admin/projects
    GET    /api/v1/admin/projects/{project_id}
    PUT    /api/v1/admin/projects/{project_id}
    POST   /api/v1/admin/projects/{project_id}/publish
    POST   /api/v1/admin/projects/{project_id}/archive

**Seis rutas: tampoco hay `/unpublish`.** `MVP_SCOPE.md` seccion 3.2 concede
`published -> draft` a articulos y reviews y solo a ellos. Sin `DELETE`
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
from app.modules.media.presentation.acceso import AccesoAMediosDependencia
from app.modules.projects.application.administracion import (
    ActualizarProyecto,
    ArchivarProyecto,
    CrearProyecto,
    PublicarProyecto,
)
from app.modules.projects.domain import ProjectStatus
from app.modules.projects.infrastructure.queries import (
    contar_proyectos_administrativos,
    listar_proyectos_administrativos,
    obtener_proyecto_administrativo,
)
from app.modules.projects.infrastructure.repositorio import RepositorioSqlDeProyectos
from app.modules.projects.presentation.schemas_admin import (
    ProyectoAdministrativo,
    ProyectoParaGuardar,
)
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RespuestaDeError
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina
from app.shared.reloj import RelojDelSistema

router = router_administrativo(prefix="/admin/projects", tags=["administracion: proyectos"])

SesionDeBaseDeDatos = Annotated[Session, Depends(get_session)]

_RESPUESTA_404: dict[int | str, dict[str, Any]] = {
    404: {"model": RespuestaDeError, "description": "El proyecto no existe."}
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
    ProjectStatus | None,
    Query(
        alias="status",
        description=(
            "Filtra por estado de **publicacion**. No confundir con `project_status`, "
            "que es la marcha del trabajo."
        ),
    ),
]


def _repositorio(sesion: SesionDeBaseDeDatos) -> RepositorioSqlDeProyectos:
    return RepositorioSqlDeProyectos(sesion)


Repositorio = Annotated[RepositorioSqlDeProyectos, Depends(_repositorio)]


def _auditoria(sesion: SesionDeBaseDeDatos) -> RegistroSqlDeAuditoria:
    return RegistroSqlDeAuditoria(sesion)


Auditoria = Annotated[RegistroSqlDeAuditoria, Depends(_auditoria)]


def _crear(repositorio: Repositorio, auditoria: Auditoria) -> CrearProyecto:
    return CrearProyecto(repositorio=repositorio, auditoria=auditoria)


def _actualizar(repositorio: Repositorio, auditoria: Auditoria) -> ActualizarProyecto:
    return ActualizarProyecto(repositorio=repositorio, auditoria=auditoria)


def _publicar(repositorio: Repositorio, auditoria: Auditoria) -> PublicarProyecto:
    return PublicarProyecto(repositorio=repositorio, auditoria=auditoria, reloj=RelojDelSistema())


def _archivar(repositorio: Repositorio, auditoria: Auditoria) -> ArchivarProyecto:
    return ArchivarProyecto(repositorio=repositorio, auditoria=auditoria)


def _serializar(
    sesion: Session, identificador: uuid.UUID, acceso: AccesoAMediosDependencia
) -> ProyectoAdministrativo:
    """Relee el proyecto para que la respuesta salga de lo que quedo en la base."""
    elemento = obtener_proyecto_administrativo(sesion, identificador)
    if elemento is None:  # pragma: no cover - acaba de escribirse en esta transaccion
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return ProyectoAdministrativo.de_modelo(elemento, acceso)


@router.get(
    "",
    response_model=Pagina[ProyectoAdministrativo],
    summary="Listado administrativo de proyectos",
    description="Coleccion paginada con los **tres** estados, por fecha de modificacion.",
)
def listar_proyectos(
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
    status_filtro: EstadoFiltrado = None,
) -> Pagina[ProyectoAdministrativo]:
    """Devuelve una pagina de proyectos en cualquier estado."""
    total = contar_proyectos_administrativos(sesion, estado=status_filtro)
    elementos = listar_proyectos_administrativos(
        sesion, parametros=parametros, estado=status_filtro
    )
    return Pagina.crear(
        items=[ProyectoAdministrativo.de_modelo(item, acceso) for item in elementos],
        parametros=parametros,
        total=total,
    )


@router.post(
    "",
    response_model=ProyectoAdministrativo,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un borrador de proyecto",
    description=(
        "Solo `title` es obligatorio. `project_status` nace en `active` y `technologies` "
        "en la lista vacia: son valores **semanticamente reales**, no rellenos."
    ),
    responses=_RESPUESTA_409,
)
def crear_proyecto(
    cuerpo: ProyectoParaGuardar,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[CrearProyecto, Depends(_crear)],
) -> ProyectoAdministrativo:
    """Crea el borrador y devuelve su representacion completa."""
    identificador = caso_de_uso(
        datos=cuerpo.a_datos(), actor_id=administrador.id, contexto=contexto
    )
    return _serializar(sesion, identificador, acceso)


@router.get(
    "/{project_id}",
    response_model=ProyectoAdministrativo,
    summary="Consultar un proyecto",
    responses=_RESPUESTA_404,
)
def obtener_proyecto(
    project_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
) -> ProyectoAdministrativo:
    """Devuelve el proyecto con ese identificador, en cualquier estado."""
    elemento = obtener_proyecto_administrativo(sesion, project_id)
    if elemento is None:
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return ProyectoAdministrativo.de_modelo(elemento, acceso)


@router.put(
    "/{project_id}",
    response_model=ProyectoAdministrativo,
    summary="Editar un proyecto",
    description=(
        "Reemplaza el proyecto. **No cambia su estado de publicacion** (B.3); si puede "
        "cambiar `project_status`, que es la marcha del trabajo."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def editar_proyecto(
    project_id: uuid.UUID,
    cuerpo: ProyectoParaGuardar,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[ActualizarProyecto, Depends(_actualizar)],
) -> ProyectoAdministrativo:
    """Guarda el proyecto y devuelve el resultado."""
    caso_de_uso(
        identificador=project_id,
        datos=cuerpo.a_datos(),
        actor_id=administrador.id,
        contexto=contexto,
    )
    return _serializar(sesion, project_id, acceso)


@router.post(
    "/{project_id}/publish",
    response_model=ProyectoAdministrativo,
    summary="Publicar un proyecto",
    description=(
        "Exige titulo, slug, contenido y una descripcion SEO resoluble. **No** exige "
        "repositorio ni demo: CONTENT_MODEL.md 3.5 los declara opcionales."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def publicar_proyecto(
    project_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[PublicarProyecto, Depends(_publicar)],
) -> ProyectoAdministrativo:
    """Publica el proyecto (flujo B.7)."""
    caso_de_uso(identificador=project_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, project_id, acceso)


@router.post(
    "/{project_id}/archive",
    response_model=ProyectoAdministrativo,
    summary="Archivar un proyecto",
    description=(
        "Retira el proyecto **sin eliminarlo** (USER_FLOWS.md B.9). Es la unica forma de "
        "retirarlo: no se despublica."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def archivar_proyecto(
    project_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[ArchivarProyecto, Depends(_archivar)],
) -> ProyectoAdministrativo:
    """Archiva el proyecto (flujo B.9)."""
    caso_de_uso(identificador=project_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, project_id, acceso)
