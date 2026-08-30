"""Generacion de la miniatura de una imagen ya validada.

Requisito P-04: *"imagenes optimizadas: formatos y dimensiones adecuados;
miniaturas para listados"*. Ninguna fuente canonica fija las dimensiones, asi
que las fija `Task/010` (decision D-010-H) y las prueba.

Politica
--------

- **Cuando: siempre al subir.** Generarla bajo demanda dejaria una biblioteca
  en la que unos medios tienen miniatura y otros no, y obligaria a **todo**
  consumidor a contemplar los dos casos.
- **Caja: 480 x 480, proporcion conservada.** Sirve un listado en pantalla de
  alta densidad sin acercarse al peso del original.
- **Nunca amplia.** Una imagen ampliada pesa mas y se ve peor que la original:
  seria una "optimizacion" que empeora las dos cosas que dice mejorar.
- **Formato: WebP, calidad 82.** Comprime mejor que JPEG a igualdad de calidad
  percibida y, a diferencia de el, admite canal alfa.
- **La orientacion EXIF se aplica.** Ignorarla deja tumbadas en el listado las
  fotografias hechas con un movil.
- **El EXIF del original no se copia.** Lleva modelo de camara y a menudo
  coordenadas GPS, y la miniatura se sirve publicamente.

Lo que este modulo **no** hace: no recorta, no rellena, no marca al agua, no
genera varios tamanos y no elige formato por navegador. Un pipeline de imagen
completo seria funcionalidad que nadie ha pedido.

La miniatura **no** se persiste como fila: su clave se deriva de la del original
(decision D-010-I), asi que `Task/010` no modifica el esquema fisico.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Final

from PIL import Image, ImageOps

from app.modules.media.domain.validacion import ImagenValidada

#: Lado mayor de la caja en la que debe caber la miniatura.
LADO_MAXIMO_DE_LA_MINIATURA: Final = 480

#: Calidad de compresion WebP. 82 es el punto habitual en el que el archivo baja
#: mucho y la diferencia deja de apreciarse a este tamano.
CALIDAD_DE_LA_MINIATURA: Final = 82

MIME_DE_LA_MINIATURA: Final = "image/webp"

#: Modos que WebP escribe de forma directa. Cualquier otro —paleta, escala de
#: grises, CMYK— se convierte antes, conservando el alfa si lo hubiera.
_MODOS_DIRECTOS: Final = frozenset({"RGB", "RGBA"})


@dataclass(frozen=True, slots=True)
class Miniatura:
    """Derivado de una imagen, listo para almacenarse."""

    contenido: bytes
    mime_type: str
    width: int
    height: int


def _preparar(imagen: Image.Image) -> Image.Image:
    """Aplica la orientacion EXIF y lleva la imagen a un modo que WebP escribe.

    `exif_transpose` gira los pixeles **y** retira la etiqueta de orientacion,
    que es justo lo correcto: dejarla puesta despues de haber girado haria que
    el visor volviera a girar la imagen ya corregida.
    """
    orientada = ImageOps.exif_transpose(imagen) or imagen
    if orientada.mode in _MODOS_DIRECTOS:
        return orientada
    tiene_alfa = orientada.mode in {"LA", "PA", "P"} and "transparency" in orientada.info
    return orientada.convert("RGBA" if tiene_alfa or orientada.mode == "LA" else "RGB")


def generar_miniatura(imagen: ImagenValidada) -> Miniatura:
    """Deriva la miniatura de una imagen ya validada.

    Recibe una `ImagenValidada` y no bytes sueltos a proposito: el tipo dice que
    el contenido ya se decodifico, ya paso el limite de pixeles y ya se sabe que
    su formato es admisible. Asi esta funcion no puede invocarse sobre algo sin
    validar, y no necesita repetir esas comprobaciones.
    """
    with Image.open(BytesIO(imagen.contenido)) as abierta:
        preparada = _preparar(abierta)
        # `thumbnail` reduce en sitio conservando la proporcion y **nunca
        # amplia**: si la imagen ya cabe en la caja, la deja como esta.
        preparada.thumbnail(
            (LADO_MAXIMO_DE_LA_MINIATURA, LADO_MAXIMO_DE_LA_MINIATURA),
            Image.Resampling.LANCZOS,
        )
        destino = BytesIO()
        # Sin `exif=`: no se copia ningun metadato del original.
        preparada.save(destino, format="WEBP", quality=CALIDAD_DE_LA_MINIATURA)
        ancho, alto = preparada.size

    return Miniatura(
        contenido=destino.getvalue(),
        mime_type=MIME_DE_LA_MINIATURA,
        width=ancho,
        height=alto,
    )
