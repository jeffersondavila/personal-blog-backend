"""Endpoints administrativos de medios (`Task/012`, flujos B.4 y B.5).

    GET    /api/v1/admin/media
    POST   /api/v1/admin/media
    DELETE /api/v1/admin/media/{media_id}

Los **tres** que `api-contracts.md` seccion 4 concede a este recurso: *"carga,
listado y borrado controlado de imagenes"*. No hay `PUT` ni `PATCH`, y por eso
`alt_text` se envia **al cargar**: anadir una cuarta operacion seria ampliar el
contrato por encima de lo que ninguna fuente vigente pide (decision D-012-R).

El router **delega**: no toca Pillow, ni boto3, ni MinIO, ni SQLAlchemy. Todo el
comportamiento es de `Task/010`, invocado a traves de sus casos de uso.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.admin import router_administrativo
from app.modules.audit.infrastructure.registro import RegistroSqlDeAuditoria
from app.modules.authentication.presentation import AdministradorRequerido, ContextoRequerido
from app.modules.media.application.administracion import (
    ArchivoRecibido,
    EliminarMedioAdministrativo,
    SubirMedioAdministrativo,
)
from app.modules.media.application.eliminar_medio import EliminarMedio
from app.modules.media.application.subir_imagen import SubirImagen
from app.modules.media.domain.validacion import TAMANO_MAXIMO_BYTES
from app.modules.media.infrastructure.queries import contar_medios, listar_medios, obtener_medio
from app.modules.media.infrastructure.repositorio import RepositorioDeMediosSQL
from app.modules.media.presentation.acceso import AccesoAMediosDependencia
from app.modules.media.presentation.schemas_admin import MedioAdministrativo
from app.shared.configuration import Settings, get_settings
from app.shared.database import get_session
from app.shared.errors import ResourceNotFoundError
from app.shared.errors.schemas import RespuestaDeError
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina
from app.shared.storage import ObjectStorage
from app.shared.storage.fabrica import obtener_almacenamiento

router = router_administrativo(prefix="/admin/media", tags=["administracion: medios"])

SesionDeBaseDeDatos = Annotated[Session, Depends(get_session)]

#: Longitud maxima del texto alternativo, la de su columna (`data-model.md` 4.1).
LONGITUD_DE_TEXTO_ALTERNATIVO = 255

_RESPUESTA_404: dict[int | str, dict[str, Any]] = {
    404: {"model": RespuestaDeError, "description": "La imagen no existe."}
}
_RESPUESTAS_DE_CARGA: dict[int | str, dict[str, Any]] = {
    413: {
        "model": RespuestaDeError,
        "description": f"El archivo supera el limite de {TAMANO_MAXIMO_BYTES} bytes.",
    },
    415: {
        "model": RespuestaDeError,
        "description": "El formato no esta permitido. Se admiten JPEG, PNG y WebP.",
    },
}


def _almacenamiento(
    configuracion: Annotated[Settings, Depends(get_settings)],
) -> ObjectStorage:
    """Entrega el almacenamiento del proceso, memorizado por configuracion."""
    return obtener_almacenamiento(configuracion)


Almacenamiento = Annotated[ObjectStorage, Depends(_almacenamiento)]


def _repositorio(sesion: SesionDeBaseDeDatos) -> RepositorioDeMediosSQL:
    return RepositorioDeMediosSQL(sesion)


Repositorio = Annotated[RepositorioDeMediosSQL, Depends(_repositorio)]


def _auditoria(sesion: SesionDeBaseDeDatos) -> RegistroSqlDeAuditoria:
    return RegistroSqlDeAuditoria(sesion)


Auditoria = Annotated[RegistroSqlDeAuditoria, Depends(_auditoria)]


def _subir(
    almacenamiento: Almacenamiento, repositorio: Repositorio, auditoria: Auditoria
) -> SubirMedioAdministrativo:
    """Ensambla la carga: el caso de uso de `Task/010`, mas la auditoria."""
    return SubirMedioAdministrativo(
        caso_de_uso=SubirImagen(almacenamiento=almacenamiento, repositorio=repositorio),
        auditoria=auditoria,
    )


def _eliminar(
    almacenamiento: Almacenamiento, repositorio: Repositorio, auditoria: Auditoria
) -> EliminarMedioAdministrativo:
    """Ensambla el borrado: el caso de uso de `Task/010`, mas la auditoria."""
    return EliminarMedioAdministrativo(
        caso_de_uso=EliminarMedio(almacenamiento=almacenamiento, repositorio=repositorio),
        auditoria=auditoria,
    )


@router.get(
    "",
    response_model=Pagina[MedioAdministrativo],
    summary="Biblioteca de medios",
    description=(
        "Coleccion paginada de las imagenes cargadas, de la mas reciente a la mas "
        "antigua. Cada elemento trae un enlace **temporal** de lectura."
    ),
)
def listar_biblioteca(
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
) -> Pagina[MedioAdministrativo]:
    """Devuelve una pagina de la biblioteca (flujo B.5)."""
    total = contar_medios(sesion)
    medios = listar_medios(sesion, parametros=parametros)
    return Pagina.crear(
        items=[MedioAdministrativo.de_modelo(item, acceso) for item in medios],
        parametros=parametros,
        total=total,
    )


@router.post(
    "",
    response_model=MedioAdministrativo,
    status_code=status.HTTP_201_CREATED,
    summary="Cargar una imagen",
    description=(
        "El tipo se valida **decodificando** el archivo, no por su extension ni por el "
        "`Content-Type` declarado. Se almacenan el original y una miniatura derivada con "
        "una clave no predecible, y en la base quedan **metadatos y clave**, nunca el "
        "binario ni una URL (USER_FLOWS.md B.4)."
    ),
    responses=_RESPUESTAS_DE_CARGA,
)
async def cargar_imagen(
    sesion: SesionDeBaseDeDatos,
    acceso: AccesoAMediosDependencia,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[SubirMedioAdministrativo, Depends(_subir)],
    archivo: Annotated[UploadFile, File(description="Imagen JPEG, PNG o WebP.")],
    alt_text: Annotated[
        str | None,
        Form(
            max_length=LONGITUD_DE_TEXTO_ALTERNATIVO,
            description="Texto alternativo (A-04). Opcional al cargar (decision D-010-N).",
        ),
    ] = None,
) -> MedioAdministrativo:
    """Carga la imagen y devuelve sus metadatos.

    Es el unico endpoint `async` del backend, y lo es por una razon concreta:
    `UploadFile.read()` es una corrutina. El resto del cuerpo es sincrono, igual
    que todos los demas.
    """
    recibido = ArchivoRecibido(
        contenido=await archivo.read(),
        nombre=archivo.filename or "sin-nombre",
        alt_text=alt_text,
    )
    identificador = caso_de_uso(archivo=recibido, actor_id=administrador.id, contexto=contexto)
    medio = obtener_medio(sesion, identificador)
    if medio is None:  # pragma: no cover - acaba de escribirse en esta transaccion
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    return MedioAdministrativo.de_modelo(medio, acceso)


@router.delete(
    "/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una imagen",
    description=(
        "Comprueba **primero** que la imagen no este en uso. Si lo esta, responde `409` "
        "diciendo **donde** se usa, en `details.usos` (USER_FLOWS.md B.5, invariante 5 "
        "de CONTENT_MODEL.md)."
    ),
    responses={
        **_RESPUESTA_404,
        409: {
            "model": RespuestaDeError,
            "description": "La imagen esta en uso y no puede eliminarse.",
        },
    },
    response_class=Response,
)
def eliminar_imagen(
    media_id: uuid.UUID,
    sesion: SesionDeBaseDeDatos,
    administrador: AdministradorRequerido,
    contexto: ContextoRequerido,
    caso_de_uso: Annotated[EliminarMedioAdministrativo, Depends(_eliminar)],
) -> None:
    """Elimina la imagen si no esta en uso (flujo B.5).

    El nombre original se lee **antes** de borrar: despues ya no existe, y el
    evento de auditoria tiene que poder decir que se elimino.
    """
    medio = obtener_medio(sesion, media_id)
    if medio is None:
        raise ResourceNotFoundError("El recurso solicitado no existe.")
    caso_de_uso(
        identificador=media_id,
        nombre_original=medio.original_filename,
        actor_id=administrador.id,
        contexto=contexto,
    )
