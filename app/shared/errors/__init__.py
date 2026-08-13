"""Jerarquia de errores de la aplicacion y su traduccion a HTTP."""

from app.shared.errors.exceptions import (
    ApplicationError,
    ConflictError,
    DependencyUnavailableError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.shared.errors.handlers import (
    ERROR_CODE_BY_STATUS,
    build_error_response,
    register_error_handlers,
)

__all__ = [
    "ERROR_CODE_BY_STATUS",
    "ApplicationError",
    "ConflictError",
    "DependencyUnavailableError",
    "ResourceNotFoundError",
    "ValidationFailedError",
    "build_error_response",
    "register_error_handlers",
]
