"""Endpoints administrativos de los articulos (`Task/012`).

    GET    /api/v1/admin/posts
    POST   /api/v1/admin/posts
    GET    /api/v1/admin/posts/{post_id}
    PUT    /api/v1/admin/posts/{post_id}
    POST   /api/v1/admin/posts/{post_id}/publish
    POST   /api/v1/admin/posts/{post_id}/unpublish
    POST   /api/v1/admin/posts/{post_id}/archive

**No hay `DELETE`** (decision D-012-D). `MVP_SCOPE.md` seccion 3.1 enumera las
capacidades sobre un articulo —*crear, editar, previsualizar, publicar,
despublicar, archivar*— y **eliminar no esta**. La invariante 3 de
CONTENT_MODEL.md dice ademas que lo archivado *"se conserva"*. El retiro es
`archive`, y no se introduce ningun `deleted_at`.

**Las transiciones son subrecursos** (decision D-012-A) y no un campo `status`
en el `PUT`: cada una tiene precondicion, validacion, error y accion de
auditoria propios, y la que `Video` y `Project` no tienen sencillamente **no
existe como ruta**.

Endpoints delgados (software-architecture.md seccion 3.5, regla 2): validan la
entrada, invocan el caso de uso y serializan. La proteccion, la validacion de
`Origin`, el `no-store` y el rechazo de parametros desconocidos los trae el
router (`app/api/admin.py`).
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
from app.modules.posts.application.administracion import (
    ActualizarArticulo,
    ArchivarArticulo,
    CrearArticulo,
    DespublicarArticulo,
    PublicarArticulo,
)
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.queries import (
    contar_articulos_administrativos,
    listar_articulos_administrativos,
    obtener_articulo_administrativo,
)
from app.modules.posts.infrastructure.repositorio import RepositorioSqlDeArticulos
from app.modules.posts.presentation.schemas_admin import (
    ArticuloAdministrativo,
    ArticuloParaGuardar,
)
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RespuestaDeError
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina
from app.shared.reloj import RelojDelSistema

router = router_administrativo(prefix="/admin/posts", tags=["administracion: articulos"])

SesionDeBaseDeDatos = Annotated[Session, Depends(get_session)]

_RESPUESTA_404: dict[int | str, dict[str, Any]] = {
    404: {"model": RespuestaDeError, "description": "El articulo no existe."}
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

#: Filtro administrativo (decision D-012-M). `status` es el **unico** filtro de
#: este lado: api-contracts.md seccion 6 lo marca como *"solo administrativo"* y
#: es la unica fuente que asigna un filtro al panel.
#: El parametro de Python se llama `status_filtro` porque `status` ya nombra al
#: modulo de codigos de FastAPI en este archivo; el **alias** es lo que ve el
#: cliente, y es `status` — el nombre que fija api-contracts.md seccion 6.
EstadoFiltrado = Annotated[
    PostStatus | None,
    Query(
        alias="status",
        description="Filtra por estado de publicacion. Ausente: los tres estados.",
    ),
]


def _repositorio(sesion: SesionDeBaseDeDatos) -> RepositorioSqlDeArticulos:
    return RepositorioSqlDeArticulos(sesion)


Repositorio = Annotated[RepositorioSqlDeArticulos, Depends(_repositorio)]


def _auditoria(sesion: SesionDeBaseDeDatos) -> RegistroSqlDeAuditoria:
    return RegistroSqlDeAuditoria(sesion)


Auditoria = Annotated[RegistroSqlDeAuditoria, Depends(_auditoria)]


def _crear(repositorio: Repositorio, auditoria: Auditoria) -> CrearArticulo:
    return CrearArticulo(repositorio=repositorio, auditoria=auditoria)


def _actualizar(repositorio: Repositorio, auditoria: Auditoria) -> ActualizarArticulo:
    return ActualizarArticulo(repositorio=repositorio, auditoria=auditoria)


def _publicar(repositorio: Repositorio, auditoria: Auditoria) -> PublicarArticulo:
    return PublicarArticulo(repositorio=repositorio, auditoria=auditoria, reloj=RelojDelSistema())


def _despublicar(repositorio: Repositorio, auditoria: Auditoria) -> DespublicarArticulo:
    return DespublicarArticulo(repositorio=repositorio, auditoria=auditoria)


def _archivar(repositorio: Repositorio, auditoria: Auditoria) -> ArchivarArticulo:
    return ArchivarArticulo(repositorio=repositorio, auditoria=auditoria)


def _serializar(
    sesion: Session, identificador: uuid.UUID, acceso: AccesoAMediosDependencia
) -> ArticuloAdministrativo:
    """Relee el articulo y lo proyecta.

    Se relee en lugar de proyectar lo que el caso de uso creia haber guardado:
    asi la respuesta sale de lo que **quedo en la base**, incluidas las marcas de
    tiempo y las etiquetas resueltas.
    """
    articulo = obtener_articulo_administrativo(sesion, identificador)
    if articulo is None:  # pragma: no cover - acaba de escribirse en esta transaccion
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return ArticuloAdministrativo.de_modelo(articulo, acceso)


@router.get(
    "",
    response_model=Pagina[ArticuloAdministrativo],
    summary="Listado administrativo de articulos",
    description=(
        "Coleccion paginada con los **tres** estados. Ordenada por fecha de "
        "modificacion descendente, con desempate por `slug`."
    ),
)
def listar_articulos(
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
    status_filtro: EstadoFiltrado = None,
) -> Pagina[ArticuloAdministrativo]:
    """Devuelve una pagina de articulos en cualquier estado."""
    total = contar_articulos_administrativos(sesion, estado=status_filtro)
    articulos = listar_articulos_administrativos(
        sesion, parametros=parametros, estado=status_filtro
    )
    return Pagina.crear(
        items=[ArticuloAdministrativo.de_modelo(item, acceso) for item in articulos],
        parametros=parametros,
        total=total,
    )


@router.post(
    "",
    response_model=ArticuloAdministrativo,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un borrador de articulo",
    description=(
        "Solo `title` es obligatorio. El contenido nace en `draft` y el slug se propone "
        "a partir del titulo si no se envia (USER_FLOWS.md B.2)."
    ),
    responses=_RESPUESTA_409,
)
def crear_articulo(
    cuerpo: ArticuloParaGuardar,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[CrearArticulo, Depends(_crear)],
) -> ArticuloAdministrativo:
    """Crea el borrador y devuelve su representacion completa."""
    identificador = caso_de_uso(
        datos=cuerpo.a_datos(), actor_id=administrador.id, contexto=contexto
    )
    return _serializar(sesion, identificador, acceso)


@router.get(
    "/{post_id}",
    response_model=ArticuloAdministrativo,
    summary="Consultar un articulo",
    description="Devuelve el articulo en **cualquier** estado, incluidos borradores.",
    responses=_RESPUESTA_404,
)
def obtener_articulo(
    post_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
) -> ArticuloAdministrativo:
    """Devuelve el articulo con ese identificador."""
    articulo = obtener_articulo_administrativo(sesion, post_id)
    if articulo is None:
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return ArticuloAdministrativo.de_modelo(articulo, acceso)


@router.put(
    "/{post_id}",
    response_model=ArticuloAdministrativo,
    summary="Editar un articulo",
    description=(
        "Reemplaza el articulo por la representacion recibida. **No cambia su estado de "
        "publicacion**: editar un publicado no lo despublica (USER_FLOWS.md B.3)."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def editar_articulo(
    post_id: uuid.UUID,
    cuerpo: ArticuloParaGuardar,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[ActualizarArticulo, Depends(_actualizar)],
) -> ArticuloAdministrativo:
    """Guarda el articulo y devuelve el resultado."""
    caso_de_uso(
        identificador=post_id,
        datos=cuerpo.a_datos(),
        actor_id=administrador.id,
        contexto=contexto,
    )
    return _serializar(sesion, post_id, acceso)


@router.post(
    "/{post_id}/publish",
    response_model=ArticuloAdministrativo,
    summary="Publicar un articulo",
    description=(
        "Pasa el borrador a `published` y fija `published_at` **la primera vez**. "
        "Rechaza con `409` si el borrador no reune los campos minimos, enumerandolos "
        "en `details.campos`."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def publicar_articulo(
    post_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[PublicarArticulo, Depends(_publicar)],
) -> ArticuloAdministrativo:
    """Publica el articulo (flujo B.7)."""
    caso_de_uso(identificador=post_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, post_id, acceso)


@router.post(
    "/{post_id}/unpublish",
    response_model=ArticuloAdministrativo,
    summary="Despublicar un articulo",
    description=(
        "Devuelve el articulo a `draft` **conservando** `published_at` como referencia "
        "historica (USER_FLOWS.md B.8). Existe en articulos y reviews; no en videos ni "
        "proyectos."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def despublicar_articulo(
    post_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[DespublicarArticulo, Depends(_despublicar)],
) -> ArticuloAdministrativo:
    """Despublica el articulo (flujo B.8)."""
    caso_de_uso(identificador=post_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, post_id, acceso)


@router.post(
    "/{post_id}/archive",
    response_model=ArticuloAdministrativo,
    summary="Archivar un articulo",
    description=(
        "Retira el articulo del sitio publico **sin eliminarlo** y conserva su fecha "
        "(USER_FLOWS.md B.9). `archived` es terminal en el MVP."
    ),
    responses={**_RESPUESTA_404, **_RESPUESTA_409},
)
def archivar_articulo(
    post_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[ArchivarArticulo, Depends(_archivar)],
) -> ArticuloAdministrativo:
    """Archiva el articulo (flujo B.9)."""
    caso_de_uso(identificador=post_id, actor_id=administrador.id, contexto=contexto)
    return _serializar(sesion, post_id, acceso)
