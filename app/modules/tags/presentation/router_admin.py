"""Endpoints administrativos de las etiquetas (`Task/012`, flujo B.11).

    GET    /api/v1/admin/tags
    POST   /api/v1/admin/tags
    PUT    /api/v1/admin/tags/{tag_id}
    DELETE /api/v1/admin/tags/{tag_id}

Los cuatro que USER_FLOWS.md B.11 asigna por nombre —*"consulta, crea, renombra
o elimina"*— y ninguno mas. **Si hay `DELETE`**, al contrario que en el
contenido: aqui una fuente canonica lo concede explicitamente.

No hay `GET /admin/tags/{tag_id}`: ningun flujo consulta una etiqueta suelta —se
eligen de la lista— y un endpoint que nadie usa es superficie que despues no
puede retirarse del contrato `v1`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, Response, status
from sqlalchemy.orm import Session

from app.api.admin import router_administrativo
from app.modules.audit.infrastructure.registro import RegistroSqlDeAuditoria
from app.modules.authentication.presentation import AdministradorRequerido, ContextoRequerido
from app.modules.tags.application.administracion import (
    CrearEtiqueta,
    EliminarEtiqueta,
    RenombrarEtiqueta,
)
from app.modules.tags.infrastructure.queries import (
    contar_etiquetas_administrativas,
    listar_etiquetas_administrativas,
    obtener_etiqueta_administrativa,
)
from app.modules.tags.infrastructure.repositorio import RepositorioSqlDeEtiquetas
from app.modules.tags.presentation.schemas_admin import (
    EtiquetaAdministrativa,
    EtiquetaParaCrear,
    EtiquetaParaRenombrar,
)
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RespuestaDeError
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina

router = router_administrativo(prefix="/admin/tags", tags=["administracion: etiquetas"])

SesionDeBaseDeDatos = Annotated[Session, Depends(get_session)]

_RESPUESTA_404: dict[int | str, dict[str, Any]] = {
    404: {"model": RespuestaDeError, "description": "La etiqueta no existe."}
}
_RESPUESTA_409: dict[int | str, dict[str, Any]] = {
    409: {"model": RespuestaDeError, "description": "Ya existe una etiqueta con ese slug."}
}


def _repositorio(sesion: SesionDeBaseDeDatos) -> RepositorioSqlDeEtiquetas:
    return RepositorioSqlDeEtiquetas(sesion)


Repositorio = Annotated[RepositorioSqlDeEtiquetas, Depends(_repositorio)]


def _auditoria(sesion: SesionDeBaseDeDatos) -> RegistroSqlDeAuditoria:
    return RegistroSqlDeAuditoria(sesion)


Auditoria = Annotated[RegistroSqlDeAuditoria, Depends(_auditoria)]


def _crear(repositorio: Repositorio, auditoria: Auditoria) -> CrearEtiqueta:
    return CrearEtiqueta(repositorio=repositorio, auditoria=auditoria)


def _renombrar(repositorio: Repositorio, auditoria: Auditoria) -> RenombrarEtiqueta:
    return RenombrarEtiqueta(repositorio=repositorio, auditoria=auditoria)


def _eliminar(repositorio: Repositorio, auditoria: Auditoria) -> EliminarEtiqueta:
    return EliminarEtiqueta(repositorio=repositorio, auditoria=auditoria)


def _serializar(sesion: Session, identificador: uuid.UUID) -> EtiquetaAdministrativa:
    """Relee la etiqueta para que la respuesta salga de lo que quedo en la base."""
    etiqueta = obtener_etiqueta_administrativa(sesion, identificador)
    if etiqueta is None:  # pragma: no cover - acaba de escribirse en esta transaccion
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return EtiquetaAdministrativa.de_modelo(etiqueta)


@router.get(
    "",
    response_model=Pagina[EtiquetaAdministrativa],
    summary="Listado administrativo de etiquetas",
    description=(
        "**Todas** las etiquetas, tengan contenido publicado o no. Es la diferencia con "
        "`GET /api/v1/tags`, que solo devuelve las que ofrecen un filtro util al visitante."
    ),
)
def listar_etiquetas(
    sesion: SesionDeBaseDeDatos,
    administrador: AdministradorRequerido,
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
) -> Pagina[EtiquetaAdministrativa]:
    """Devuelve una pagina de etiquetas, ordenada por nombre."""
    total = contar_etiquetas_administrativas(sesion)
    etiquetas = listar_etiquetas_administrativas(sesion, parametros=parametros)
    return Pagina.crear(
        items=[EtiquetaAdministrativa.de_modelo(item) for item in etiquetas],
        parametros=parametros,
        total=total,
    )


@router.post(
    "",
    response_model=EtiquetaAdministrativa,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una etiqueta",
    description="El slug se propone a partir del nombre si no se envia.",
    responses=_RESPUESTA_409,
)
def crear_etiqueta(
    cuerpo: EtiquetaParaCrear,
    sesion: SesionDeBaseDeDatos,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[CrearEtiqueta, Depends(_crear)],
) -> EtiquetaAdministrativa:
    """Crea la etiqueta y devuelve su representacion."""
    identificador = caso_de_uso(
        datos=cuerpo.a_datos(), actor_id=administrador.id, contexto=contexto
    )
    return _serializar(sesion, identificador)


@router.put(
    "/{tag_id}",
    response_model=EtiquetaAdministrativa,
    summary="Renombrar una etiqueta",
    description=(
        "Cambia el nombre visible y la descripcion. **El slug no se puede cambiar** "
        "(decision D-012-S): aparece en URL publicas compartibles."
    ),
    responses=_RESPUESTA_404,
)
def renombrar_etiqueta(
    tag_id: uuid.UUID,
    cuerpo: EtiquetaParaRenombrar,
    sesion: SesionDeBaseDeDatos,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[RenombrarEtiqueta, Depends(_renombrar)],
) -> EtiquetaAdministrativa:
    """Renombra la etiqueta y devuelve el resultado."""
    caso_de_uso(
        identificador=tag_id,
        datos=cuerpo.a_datos(),
        actor_id=administrador.id,
        contexto=contexto,
    )
    return _serializar(sesion, tag_id)


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una etiqueta",
    description=(
        "Elimina la etiqueta y **desasocia** el contenido que la usaba; no elimina "
        "contenido (USER_FLOWS.md B.11). La confirmacion previa es un paso de la "
        "interfaz (`Task/015`), no un parametro de esta API."
    ),
    responses=_RESPUESTA_404,
    response_class=Response,
)
def eliminar_etiqueta(
    tag_id: uuid.UUID,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[EliminarEtiqueta, Depends(_eliminar)],
) -> None:
    """Elimina la etiqueta (flujo B.11)."""
    caso_de_uso(identificador=tag_id, actor_id=administrador.id, contexto=contexto)
