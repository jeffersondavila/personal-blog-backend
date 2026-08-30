"""Constructores de imagenes de prueba.

Las imagenes se **generan**, no se versionan como binarios: un `.png` en el
repositorio no dice que contiene, no se puede parametrizar y obliga a confiar en
que alguien lo creo bien. Aqui cada imagen se describe por su forma, su formato
y su orientacion, que es exactamente lo que la prueba quiere afirmar.
"""

from __future__ import annotations

import struct
import zlib
from io import BytesIO

from PIL import Image

#: Firma con la que empieza todo archivo PNG.
_FIRMA_PNG = b"\x89PNG\r\n\x1a\n"

#: Longitud fija de un fragmento PNG vacio: 4 de longitud + 4 de tipo + 4 de CRC.
_SOBRECARGA_DE_FRAGMENTO = 12


def _fragmento_png(tipo: bytes, datos: bytes) -> bytes:
    return (
        struct.pack(">I", len(datos))
        + tipo
        + datos
        + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
    )


def _serializar(imagen: Image.Image, formato: str) -> bytes:
    destino = BytesIO()
    imagen.save(destino, format=formato)
    return destino.getvalue()


def imagen(*, ancho: int = 1200, alto: int = 800, formato: str = "PNG") -> bytes:
    """Imagen valida con un degradado, para que no sea trivialmente comprimible."""
    lienzo = Image.new("RGB", (ancho, alto))
    pixeles = lienzo.load()
    assert pixeles is not None
    for x in range(ancho):
        for y in range(alto):
            pixeles[x, y] = (
                x * 255 // max(ancho - 1, 1),
                y * 255 // max(alto - 1, 1),
                128,
            )
    return _serializar(lienzo, formato)


def png(*, ancho: int = 1200, alto: int = 800) -> bytes:
    return imagen(ancho=ancho, alto=alto, formato="PNG")


def jpeg(*, ancho: int = 1200, alto: int = 800) -> bytes:
    return imagen(ancho=ancho, alto=alto, formato="JPEG")


def webp(*, ancho: int = 1200, alto: int = 800) -> bytes:
    return imagen(ancho=ancho, alto=alto, formato="WEBP")


def gif(*, ancho: int = 64, alto: int = 64) -> bytes:
    """GIF valido. Se decodifica sin problemas: lo que lo rechaza es la politica
    de formatos (decision D-010-E), no un fallo de lectura."""
    return _serializar(Image.new("P", (ancho, alto)), "GIF")


#: SVG con contenido activo. No es un formato rasterizado y por tanto ni
#: siquiera se identifica como imagen; se rechaza por serlo, no por el `script`.
SVG_CON_SCRIPT = (
    b'<?xml version="1.0"?>'
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b"<script>alert(1)</script></svg>"
)


def png_en_paleta(*, ancho: int = 600, alto: int = 400, transparente: bool = False) -> bytes:
    """PNG en modo paleta (`P`), que es como PNG guarda una imagen indexada.

    Es una imagen perfectamente normal que un administrador puede subir, y **no**
    es uno de los modos que WebP escribe de forma directa: obliga a convertirla
    antes de generar la miniatura.
    """
    lienzo = Image.new("P", (ancho, alto))
    lienzo.putpalette([(x * 3) % 256 for x in range(768)])
    for x in range(ancho):
        for y in range(alto):
            # La mitad derecha usa el indice 0, que es el que se declara
            # transparente. Es una region **solida**, no una linea: una franja
            # de un pixel se difuminaria al reducir y la transparencia dejaria
            # de ser observable en la miniatura.
            lienzo.putpixel((x, y), 0 if x >= ancho // 2 else 1 + (x + y) % 255)
    if not transparente:
        return _serializar(lienzo, "PNG")
    destino = BytesIO()
    lienzo.save(destino, format="PNG", transparency=0)
    return destino.getvalue()


def png_en_escala_de_grises(*, ancho: int = 600, alto: int = 400) -> bytes:
    """PNG en modo `L`. Tampoco es un modo que WebP escriba directamente."""
    lienzo = Image.new("L", (ancho, alto))
    for x in range(ancho):
        for y in range(alto):
            lienzo.putpixel((x, y), (x + y) % 256)
    return _serializar(lienzo, "PNG")


def png_con_transparencia(*, ancho: int = 1200, alto: int = 800) -> bytes:
    """PNG con canal alfa: la mitad izquierda opaca, la derecha transparente."""
    lienzo = Image.new("RGBA", (ancho, alto), (255, 0, 0, 255))
    for x in range(ancho // 2, ancho):
        for y in range(alto):
            lienzo.putpixel((x, y), (0, 0, 255, 0))
    return _serializar(lienzo, "PNG")


def jpeg_con_orientacion_exif(*, ancho: int = 1200, alto: int = 800, orientacion: int = 6) -> bytes:
    """JPEG con EXIF que incluye orientacion y una etiqueta identificable.

    `orientacion=6` significa "girada 90 grados": al aplicarla, una imagen
    horizontal pasa a ser vertical. Es el caso que hace visible el defecto de
    ignorar la orientacion.

    Se anade ademas `Make`, que hace las veces de metadato sensible —el bloque
    real de una fotografia llevaria modelo de camara y coordenadas GPS— para
    poder comprobar que el derivado **no** lo arrastra.
    """
    lienzo = Image.new("RGB", (ancho, alto), (10, 120, 200))
    exif = Image.Exif()
    exif[0x0112] = orientacion  # Orientation
    exif[0x010F] = "camara-de-prueba"  # Make
    destino = BytesIO()
    lienzo.save(destino, format="JPEG", exif=exif)
    return destino.getvalue()


def png_truncado() -> bytes:
    """PNG valido cortado por la mitad: la cabecera es correcta, los datos faltan.

    Es el caso que distingue validar de verdad —decodificar— de mirar los
    primeros bytes: la firma y las dimensiones son perfectas.
    """
    completo = png(ancho=400, alto=400)
    return completo[: len(completo) // 2]


def png_con_dimensiones_declaradas(ancho: int, alto: int) -> bytes:
    """PNG cuya cabecera **declara** dimensiones enormes con muy pocos bytes.

    Es la forma real de una *decompression bomb*: el archivo pesa nada y la
    cabecera anuncia una imagen que, descomprimida, agotaria la memoria. Por eso
    el limite de tamano en bytes **no** protege de esto y hace falta un limite
    de pixeles aparte.
    """
    cabecera = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    return (
        _FIRMA_PNG
        + _fragmento_png(b"IHDR", cabecera)
        + _fragmento_png(b"IDAT", zlib.compress(b"\x00" * 16))
        + _fragmento_png(b"IEND", b"")
    )


def png_de_exactamente(bytes_totales: int, *, ancho: int = 64, alto: int = 64) -> bytes:
    """PNG valido que ocupa **exactamente** `bytes_totales`.

    El relleno es un fragmento PNG auxiliar y privado (`prVt`): la primera letra
    minuscula lo marca como auxiliar, y el estandar obliga a los lectores a
    ignorar los fragmentos auxiliares que no conocen. La imagen sigue siendo
    valida y decodificable.

    Existe para comprobar el limite de tamano en su valor **exacto** y en el
    exacto mas uno, que es donde se esconden los errores de comparacion por uno.
    """
    base = png(ancho=ancho, alto=alto)
    relleno = bytes_totales - len(base) - _SOBRECARGA_DE_FRAGMENTO
    if relleno < 0:  # pragma: no cover - solo si se pide un tamano imposible
        raise ValueError(f"{bytes_totales} bytes no bastan para un PNG de {ancho}x{alto}")
    fragmento = _fragmento_png(b"prVt", bytes(relleno))
    # Antes del fragmento final `IEND`, que siempre ocupa los ultimos 12 bytes.
    return base[:-_SOBRECARGA_DE_FRAGMENTO] + fragmento + base[-_SOBRECARGA_DE_FRAGMENTO:]


def dimensiones(contenido: bytes) -> tuple[int, int]:
    """Ancho y alto reales de una imagen serializada."""
    with Image.open(BytesIO(contenido)) as abierta:
        return abierta.size


def formato(contenido: bytes) -> str:
    """Formato real de una imagen serializada, segun quien la decodifica."""
    with Image.open(BytesIO(contenido)) as abierta:
        return abierta.format or ""
