"""Errores del dominio de medios.

Cada uno hereda del error de aplicacion cuyo codigo HTTP le corresponde en
api-contracts.md seccion 8, de modo que la traduccion a respuesta ya esta
resuelta en `app.shared.errors.handlers` y no hay que tocarla cuando `Task/012`
exponga la subida por HTTP:

- **`ImagenInvalidaError` -> `422`.** La peticion esta bien formada; lo que no
  supera la validacion es su contenido.
- **`TipoDeImagenNoPermitidoError` -> `415`.** El archivo es una imagen
  legitima, pero de un formato que no se acepta.
- **`ImagenDemasiadoGrandeError` -> `413`.** El limite es de tamano, y `413` es
  el codigo que lo dice.
- **`MedioEnUsoError` -> `409`.** Conflicto con el estado actual: el medio esta
  referenciado por algun contenido.

Se importa de `app.shared.errors.exceptions` —el modulo hoja— y no del paquete
`app.shared.errors`, que reexporta los manejadores y con ellos **arrastraria
FastAPI al dominio**. Es el defecto real que `Task/008` corrigio y que
`tests/unit/test_independencia_del_dominio.py` vigila.
"""

from __future__ import annotations

from typing import Any

from app.shared.errors.exceptions import (
    ConflictError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationFailedError,
)


class ImagenInvalidaError(ValidationFailedError):
    """El contenido no es una imagen decodificable."""

    code = "invalid_image"


class TipoDeImagenNoPermitidoError(UnsupportedMediaTypeError):
    """El formato de la imagen no esta en la lista permitida."""

    code = "unsupported_image_type"


class ImagenDemasiadoGrandeError(PayloadTooLargeError):
    """La imagen supera el limite de bytes o el de pixeles."""

    code = "image_too_large"


class MedioEnUsoError(ConflictError):
    """El medio esta referenciado por algun contenido y no puede eliminarse.

    Invariante 5 de CONTENT_MODEL.md. El flujo B.5 exige que el rechazo diga
    **donde** se usa, asi que los usos viajan en `details` —la forma que
    api-contracts.md seccion 7 reserva para el contexto estructurado— y no
    concatenados dentro del mensaje.
    """

    code = "media_in_use"

    def __init__(self, mensaje: str, *, usos: list[dict[str, Any]]) -> None:
        super().__init__(mensaje, details={"usos": usos})
        self.usos = usos
