"""Traduccion centralizada de errores a respuestas HTTP.

Toda respuesta de error del backend usa la misma forma (api-contracts.md,
seccion 7):

```json
{
  "error": {
    "code": "resource_not_found",
    "message": "...",
    "details": {},
    "request_id": "..."
  }
}
```

Reglas aplicadas aqui:

- **Nunca** se devuelven trazas de pila, sentencias SQL, rutas de archivo ni
  nombres de clase (requisito S-07). La traza va al log, no al cliente.
- Todo error lleva `request_id`, y ese mismo identificador aparece en el log
  del error. La propagacion completa del correlation ID —cabecera de entrada,
  respuesta y todos los logs de la peticion— corresponde a `Task/017`.
- Los codigos `code` son estables una vez publicados (api-contracts.md,
  seccion 10).
"""

from __future__ import annotations

import uuid
from http import HTTPStatus
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.errors.exceptions import ApplicationError
from app.shared.logging import get_logger

_logger = get_logger(__name__)

#: Codigo estable para cada estado HTTP que el framework genera por su cuenta.
ERROR_CODE_BY_STATUS: Final[dict[int, str]] = {
    HTTPStatus.BAD_REQUEST: "bad_request",
    HTTPStatus.UNAUTHORIZED: "unauthorized",
    HTTPStatus.FORBIDDEN: "forbidden",
    HTTPStatus.NOT_FOUND: "resource_not_found",
    HTTPStatus.METHOD_NOT_ALLOWED: "method_not_allowed",
    HTTPStatus.CONFLICT: "conflict",
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "payload_too_large",
    HTTPStatus.UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    HTTPStatus.UNPROCESSABLE_ENTITY: "validation_error",
    HTTPStatus.TOO_MANY_REQUESTS: "too_many_requests",
    HTTPStatus.INTERNAL_SERVER_ERROR: "internal_error",
    HTTPStatus.SERVICE_UNAVAILABLE: "service_unavailable",
}

_GENERIC_MESSAGE_BY_STATUS: Final[dict[int, str]] = {
    HTTPStatus.NOT_FOUND: "El recurso solicitado no existe.",
    HTTPStatus.INTERNAL_SERVER_ERROR: "Error interno del servidor.",
}


def new_request_id() -> str:
    """Genera el identificador de correlacion de una respuesta de error."""
    return str(uuid.uuid4())


def request_id_de(request: Request) -> str:
    """Identificador de correlacion **de la peticion**, creado una sola vez.

    Antes de `Task/011` cada manejador de error generaba el suyo. Bastaba,
    porque solo se ejecuta uno por peticion y nadie mas lo necesitaba. Ahora si:
    los eventos de auditoria de autenticacion deben llevar **el mismo**
    identificador que el cliente ve en el cuerpo de error, que es el objetivo
    declarado en api-contracts.md seccion 9 —rastrear un problema de extremo a
    extremo con un unico dato—. Con un identificador por manejador, el evento y
    la respuesta llevarian numeros distintos y no se podrian cruzar.

    Se memoriza en `request.state`, asi que la primera llamada lo crea y todas
    las demas de esa peticion devuelven el mismo.

    **No es un segundo sistema de correlacion**: reutiliza el generador que ya
    existia y lo convierte en el unico punto donde se decide. `Task/017` seguira
    siendo el propietario de la propagacion completa —aceptar el identificador
    que envie el cliente en una cabecera acordada, emitirlo en la respuesta y
    llevarlo a todos los logs de la peticion—: cambiara **el origen** del valor
    sin tocar a quien lo consume.
    """
    existente: str | None = getattr(request.state, "request_id", None)
    if existente is not None:
        return existente
    generado = new_request_id()
    request.state.request_id = generado
    return generado


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Construye la respuesta de error con la forma comun del proyecto."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
            }
        },
        headers=headers or None,
    )


async def handle_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
    """Traduce un error controlado de la aplicacion."""
    request_id = request_id_de(request)
    _logger.warning(
        "Error de aplicacion",
        extra={
            "request_id": request_id,
            "error_code": exc.code,
            "path": request.url.path,
            "method": request.method,
        },
    )
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
        headers=exc.headers,
    )


async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Traduce un fallo de validacion de entrada a `422` con los campos afectados."""
    request_id = request_id_de(request)
    fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "reason": error.get("msg", ""),
        }
        for error in exc.errors()
    ]
    _logger.info(
        "Peticion invalida",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "invalid_fields": [field["field"] for field in fields],
        },
    )
    return build_error_response(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        code="validation_error",
        message="La peticion no supera la validacion.",
        request_id=request_id,
        details={"fields": fields},
    )


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Traduce las excepciones HTTP del framework (404 de ruta, 405, etc.)."""
    request_id = request_id_de(request)
    status_code = exc.status_code
    code = ERROR_CODE_BY_STATUS.get(status_code, "http_error")
    message = _GENERIC_MESSAGE_BY_STATUS.get(status_code) or str(exc.detail)
    _logger.info(
        "Respuesta de error HTTP",
        extra={
            "request_id": request_id,
            "status_code": status_code,
            "path": request.url.path,
            "method": request.method,
        },
    )
    return build_error_response(
        status_code=status_code,
        code=code,
        message=message,
        request_id=request_id,
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Ultimo recurso: cualquier excepcion no prevista se convierte en `500` opaco.

    La excepcion completa —incluida su traza— se registra en el log asociada al
    `request_id`. Al cliente solo le llega un mensaje generico.
    """
    request_id = request_id_de(request)
    _logger.exception(
        "Error no controlado",
        exc_info=exc,
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
        },
    )
    return build_error_response(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        code="internal_error",
        message=_GENERIC_MESSAGE_BY_STATUS[HTTPStatus.INTERNAL_SERVER_ERROR],
        request_id=request_id,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Registra en la aplicacion todos los manejadores de error."""
    app.add_exception_handler(ApplicationError, handle_application_error)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        handle_request_validation_error,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        StarletteHTTPException,
        handle_http_exception,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, handle_unexpected_error)
