"""Errores de la aplicacion, independientes del framework.

Estas excepciones las lanza la logica de la aplicacion; **no conocen FastAPI**.
Su traduccion a codigos y cuerpos HTTP ocurre en un unico punto
(`app.shared.errors.handlers`), tal como exige software-architecture.md,
seccion 3.6.

`code` es un identificador **estable**, legible por maquina, al que el frontend
puede reaccionar; `message` es texto para humanos y puede cambiar de redaccion
(api-contracts.md, seccion 7).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class ApplicationError(Exception):
    """Error controlado de la aplicacion.

    Nunca transporta trazas, SQL, rutas de archivo ni nombres de clase: esa
    informacion no sale al cliente (requisito S-07).
    """

    code: str = "application_error"
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}


class ResourceNotFoundError(ApplicationError):
    """El recurso no existe **o no es visible** para quien pregunta.

    Un recurso inexistente y uno existente pero no publicado producen la misma
    respuesta: la API no revela la existencia de borradores (api-contracts.md,
    seccion 3).
    """

    code = "resource_not_found"
    status_code = HTTPStatus.NOT_FOUND


class ValidationFailedError(ApplicationError):
    """La peticion esta bien formada pero no supera las reglas de validacion."""

    code = "validation_error"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class ConflictError(ApplicationError):
    """La operacion choca con el estado actual del recurso."""

    code = "conflict"
    status_code = HTTPStatus.CONFLICT


class UnsupportedMediaTypeError(ApplicationError):
    """El tipo de contenido recibido no esta permitido.

    Distinto de `ValidationFailedError`: la peticion no es incorrecta, es que el
    formato no entra en la lista permitida (api-contracts.md, seccion 8).
    """

    code = "unsupported_media_type"
    status_code = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class PayloadTooLargeError(ApplicationError):
    """El contenido excede el limite permitido (api-contracts.md, seccion 8)."""

    code = "payload_too_large"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class DependencyUnavailableError(ApplicationError):
    """Una dependencia externa necesaria no esta disponible."""

    code = "dependency_unavailable"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
