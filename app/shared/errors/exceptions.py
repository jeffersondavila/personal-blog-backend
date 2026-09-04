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

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        #: Cabeceras que la respuesta de error debe llevar.
        #:
        #: Existe porque algunos codigos del contrato **son** su cabecera:
        #: `429 Too Many Requests` sin `Retry-After` obliga al cliente a adivinar
        #: cuando puede volver (api-contracts.md seccion 8). Anadida en
        #: `Task/011`; sigue sin transportar nada interno, solo protocolo.
        self.headers: dict[str, str] = headers or {}


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


class ReferenciaDesconocidaError(ValidationFailedError):
    """La peticion referencia una entidad que no existe.

    Distinto de `ResourceNotFoundError` (`Task/012`, decision D-012-J): lo que
    no existe **no es el recurso de la ruta**, sino algo que el cuerpo nombra
    —una etiqueta, una portada—. Devolver `404` seria ambiguo: el cliente no
    sabria cual de los dos recursos falta. La peticion esta bien formada y lo
    que falla es su contenido, que es lo que api-contracts.md seccion 8 reserva
    para `422`.

    Los identificadores desconocidos viajan en `details` para que el
    administrador sepa **cual** quitar, no solo que hay uno malo.
    """

    code = "unknown_reference"

    def __init__(self, mensaje: str, *, campo: str, valores: list[str]) -> None:
        super().__init__(mensaje, details={"campo": campo, "valores": valores})
        self.campo = campo
        self.valores = valores


class MedioSinTextoAlternativoError(ValidationFailedError):
    """La imagen referenciada no tiene texto alternativo (requisito A-04).

    `data-model.md` seccion 4.1 asigna a `Task/012` y `Task/014` **exigirlo donde
    se usa** la imagen; `Task/010` decidio deliberadamente no exigirlo al cargar
    (D-010-N), porque *"se escribe al usar la imagen, no al cargarla"*.

    Es `422` y no `409` porque lo que falla es el **contenido de la peticion**:
    referencia una imagen que todavia no puede usarse en algo visible. Los cuatro
    tipos publicables no llegan aqui —alli la exigencia es del **estado**, al
    publicar, y usa `cannot_publish_incomplete_draft`—; el perfil si, porque no
    tiene estado: *"siempre existe y siempre esta visible"*.
    """

    code = "media_without_alt_text"

    def __init__(self, mensaje: str, *, campo: str, valor: str) -> None:
        super().__init__(mensaje, details={"campo": campo, "valor": valor})
        self.campo = campo
        self.valor = valor


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
