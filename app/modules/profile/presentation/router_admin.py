"""Endpoints administrativos del perfil (`Task/012`, flujo B.10).

    GET /api/v1/admin/profile
    PUT /api/v1/admin/profile

**Dos operaciones y ninguna mas.** No hay `POST` ni `DELETE`: el perfil es un
*singleton* que *"existe exactamente uno y no se crea ni elimina"* (B.10), y
`data-model.md` seccion 5 asigna a esta tarea **solo** lectura y edicion
(decision D-012-U).

Endpoint delgado (software-architecture.md seccion 3.5, regla 2): valida la
entrada, invoca el caso de uso y serializa. La proteccion la trae el router.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, status
from sqlalchemy.orm import Session

from app.api.admin import router_administrativo
from app.modules.audit.infrastructure.registro import RegistroSqlDeAuditoria
from app.modules.authentication.presentation import AdministradorRequerido, ContextoRequerido
from app.modules.media.presentation.acceso import AccesoAMediosDependencia
from app.modules.profile.application.administracion import ActualizarPerfil
from app.modules.profile.infrastructure.queries import obtener_perfil
from app.modules.profile.infrastructure.repositorio import RepositorioSqlDelPerfil
from app.modules.profile.presentation.schemas_admin import (
    PerfilAdministrativo,
    PerfilParaGuardar,
)
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RespuestaDeError

router = router_administrativo(prefix="/admin/profile", tags=["administracion: perfil"])

SesionDeBaseDeDatos = Annotated[Session, Depends(get_session)]

_RESPUESTA_404: dict[int | str, dict[str, Any]] = {
    404: {
        "model": RespuestaDeError,
        "description": (
            "El perfil todavia no existe. **No se crea por API**: la semilla local es de "
            "`Task/022` y el perfil real de produccion, de `Task/036`."
        ),
    }
}


def _construir_actualizacion(sesion: SesionDeBaseDeDatos) -> ActualizarPerfil:
    """Ensambla el caso de uso con sus adaptadores reales.

    Es el unico punto que sabe a la vez que existe una sesion de SQLAlchemy y un
    registro de auditoria; el caso de uso sigue recibiendo puertos. Se usa la
    inyeccion del framework y nada mas (principio 6).
    """
    return ActualizarPerfil(
        repositorio=RepositorioSqlDelPerfil(sesion),
        auditoria=RegistroSqlDeAuditoria(sesion),
    )


CasoDeActualizacion = Annotated[ActualizarPerfil, Depends(_construir_actualizacion)]


@router.get(
    "",
    response_model=PerfilAdministrativo,
    summary="Consultar el perfil",
    description="Perfil completo, con sus enlaces sociales en su orden de presentacion.",
    responses=_RESPUESTA_404,
)
def leer_perfil_administrativo(
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
) -> PerfilAdministrativo:
    """Devuelve el perfil tal como lo edita el panel."""
    perfil = obtener_perfil(sesion)
    if perfil is None:
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return PerfilAdministrativo.de_modelo(perfil, acceso)


@router.put(
    "",
    response_model=PerfilAdministrativo,
    status_code=status.HTTP_200_OK,
    summary="Editar el perfil",
    description=(
        "Reemplaza el perfil por la representacion recibida (decision D-012-C: `PUT` es "
        "una representacion **completa**). Los enlaces sociales se reemplazan enteros y su "
        "orden de presentacion es la posicion en la lista."
    ),
    responses=_RESPUESTA_404,
)
def editar_perfil(
    cuerpo: PerfilParaGuardar,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: CasoDeActualizacion,
) -> PerfilAdministrativo:
    """Guarda el perfil y devuelve el resultado.

    Se relee con la consulta que ya existia en lugar de proyectar lo escrito:
    asi la respuesta sale de lo que **quedo en la base** —incluida la marca de
    actualizacion, que la escribe el ORM— y no de lo que el caso de uso creia
    haber guardado.
    """
    caso_de_uso(
        datos=cuerpo.a_datos(),
        actor_id=administrador.id,
        contexto=contexto,
    )
    perfil = obtener_perfil(sesion)
    if perfil is None:  # pragma: no cover - el caso de uso ya habria lanzado
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return PerfilAdministrativo.de_modelo(perfil, acceso)
