"""Validacion de una imagen subida.

La regla que gobierna este modulo cabe en una linea: **manda el contenido**.

Ni la extension del nombre, ni el `Content-Type` que declara el cliente, ni la
firma de los primeros bytes. Las tres son afirmaciones que un cliente hostil
controla enteras, y las tres siguen siendo ciertas para un archivo que no es lo
que dice ser. La unica comprobacion que no se puede falsificar es **decodificar
la imagen**, que es lo que se hace aqui.

De ahi que `validar_imagen` **ni siquiera reciba** el nombre del archivo: no hay
forma de que una decision dependa de el. El nombre se conserva aparte, como
metadato informativo en `media_assets.original_filename`.

Politica (decisiones D-010-E y D-010-F)
---------------------------------------

- **Formatos: JPEG, PNG y WebP.** Cubren todo lo que el MVP publica. **SVG
  queda fuera por seguridad**: es XML con capacidad de script. GIF queda fuera
  porque la animacion complica la miniatura y ningun flujo la pide.
- **Tamano: 5 MiB.** Una fotografia de portada holgada, y una cota al cuerpo de
  la peticion.
- **Pixeles: 40 millones.** Guarda contra una *decompression bomb*: un PNG de
  68 bytes puede declarar 40000 x 40000.

Los limites de tamano y de pixeles son **independientes** y ninguno sustituye al
otro: el primero acota lo que viaja por la red, el segundo lo que ocupa al
descomprimirse.

`Task/018` endurecera esta validacion. Endurecer significa restringir: ampliar
la lista de formatos no es un endurecimiento y no le corresponde.
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO
from typing import Final

from PIL import Image

from app.modules.media.domain.errores import (
    ImagenDemasiadoGrandeError,
    ImagenInvalidaError,
    TipoDeImagenNoPermitidoError,
)

#: Formatos aceptados, de la etiqueta que usa el decodificador al tipo MIME y la
#: extension del proyecto. La extension de un JPEG es `jpg` y no `jpeg` por
#: convencion; la clave del objeto la toma de aqui, nunca del nombre recibido.
FORMATOS_PERMITIDOS: Final[dict[str, tuple[str, str]]] = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}

#: 5 MiB (decision D-010-F).
TAMANO_MAXIMO_BYTES: Final = 5 * 1024 * 1024

#: 40 millones de pixeles: por encima de 8000 x 5000 aproximadamente.
PIXELES_MAXIMOS: Final = 40_000_000


@dataclass(frozen=True, slots=True)
class ImagenValidada:
    """Imagen que supero la validacion, con los metadatos que se persistiran.

    `contenido` son los bytes **originales**, sin recodificar: lo que se guarda
    es exactamente lo que llego. Recodificar el original perderia calidad sin
    que nadie lo pidiera, y haria que el `checksum` no correspondiera al archivo
    que el administrador subio.
    """

    contenido: bytes
    mime_type: str
    extension: str
    width: int
    height: int
    size_bytes: int
    checksum: str


def validar_imagen(contenido: bytes) -> ImagenValidada:
    """Comprueba que `contenido` es una imagen admisible y extrae sus metadatos.

    El orden de las comprobaciones no es casual: primero lo barato y lo que
    protege de lo caro. El tamano en bytes se mide sin decodificar; las
    dimensiones se leen de la cabecera; y solo despues se decodifica de verdad,
    que es la unica operacion que consume memoria proporcional a la imagen.
    """
    if len(contenido) > TAMANO_MAXIMO_BYTES:
        raise ImagenDemasiadoGrandeError(
            f"la imagen supera el limite de {TAMANO_MAXIMO_BYTES} bytes"
        )

    with warnings.catch_warnings():
        # Pillow avisa antes de rechazar. Con la suite en `-W error` ese aviso
        # se convertiria en una excepcion distinta y el llamante recibiria un
        # error interno en lugar del suyo. Se fuerza aqui para tratarlo igual
        # que el rechazo: ambos significan "demasiados pixeles".
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            imagen = Image.open(BytesIO(contenido))
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ImagenDemasiadoGrandeError(
                "la imagen declara mas pixeles de los permitidos"
            ) from error
        except Exception as error:
            raise ImagenInvalidaError("el contenido no es una imagen valida") from error

    with imagen:
        formato = imagen.format or ""
        if formato not in FORMATOS_PERMITIDOS:
            permitidos = ", ".join(sorted(FORMATOS_PERMITIDOS))
            raise TipoDeImagenNoPermitidoError(
                f"formato de imagen no permitido; se aceptan: {permitidos}"
            )

        ancho, alto = imagen.size
        if ancho * alto > PIXELES_MAXIMOS:
            raise ImagenDemasiadoGrandeError(
                f"la imagen supera el limite de {PIXELES_MAXIMOS} pixeles"
            )

        try:
            # Decodifica de verdad. Es lo unico que detecta un archivo cuya
            # cabecera es perfecta y cuyos datos estan truncados o corruptos.
            imagen.load()
        except Exception as error:
            raise ImagenInvalidaError(
                "la imagen no se puede decodificar: esta truncada o danada"
            ) from error

    mime_type, extension = FORMATOS_PERMITIDOS[formato]
    return ImagenValidada(
        contenido=contenido,
        mime_type=mime_type,
        extension=extension,
        width=ancho,
        height=alto,
        size_bytes=len(contenido),
        checksum=hashlib.sha256(contenido).hexdigest(),
    )
