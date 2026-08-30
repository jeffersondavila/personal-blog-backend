"""Generacion de la miniatura de un medio.

El requisito P-04 pide "imagenes optimizadas: formatos y dimensiones adecuados;
**miniaturas para listados**", y asigna la parte de backend a `Task/010`.
Ninguna fuente canonica fija las dimensiones, asi que las fija esta tarea
(decision D-010-H) y esta prueba las convierte en contrato:

| Regla | Valor |
| --- | --- |
| Cuando | **Siempre** al subir |
| Caja | 480 x 480, proporcion conservada |
| Ampliar | **Nunca** |
| Formato | WebP, calidad 82 |
| Orientacion EXIF | **Normalizada** |
| EXIF del original | **No se copia** |
"""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO

import pytest
from PIL import Image

from app.modules.media.domain.miniaturas import (
    LADO_MAXIMO_DE_LA_MINIATURA,
    MIME_DE_LA_MINIATURA,
    generar_miniatura,
)
from app.modules.media.domain.validacion import validar_imagen
from tests import imagenes


def _miniatura_de(contenido: bytes) -> tuple[bytes, tuple[int, int]]:
    miniatura = generar_miniatura(validar_imagen(contenido))
    return miniatura.contenido, (miniatura.width, miniatura.height)


# --- T-01 ------------------------------------------------------------------
def test_la_miniatura_es_un_webp_decodificable() -> None:
    contenido, _ = _miniatura_de(imagenes.png(ancho=1200, alto=800))

    assert imagenes.formato(contenido) == "WEBP"
    assert MIME_DE_LA_MINIATURA == "image/webp"


def test_la_miniatura_declara_las_dimensiones_que_de_verdad_tiene() -> None:
    """Guarda: los metadatos devueltos no pueden ser una promesa sin comprobar."""
    contenido, declaradas = _miniatura_de(imagenes.png(ancho=1200, alto=800))

    assert imagenes.dimensiones(contenido) == declaradas


# --- T-02 ------------------------------------------------------------------
def test_la_miniatura_cabe_en_la_caja_y_conserva_la_proporcion() -> None:
    _, (ancho, alto) = _miniatura_de(imagenes.png(ancho=1200, alto=800))

    assert max(ancho, alto) == LADO_MAXIMO_DE_LA_MINIATURA
    assert (ancho, alto) == (480, 320)


def test_una_imagen_vertical_tambien_cabe_en_la_caja() -> None:
    """Guarda anti-tautologia: una implementacion que fijara el ancho a 480
    pasaria el caso horizontal y fallaria aqui."""
    _, (ancho, alto) = _miniatura_de(imagenes.png(ancho=800, alto=1200))

    assert (ancho, alto) == (320, 480)


# --- T-03 ------------------------------------------------------------------
def test_la_miniatura_no_amplia_una_imagen_pequena() -> None:
    """Ampliar produciria un archivo mas pesado y mas borroso que el original."""
    _, (ancho, alto) = _miniatura_de(imagenes.png(ancho=100, alto=80))

    assert (ancho, alto) == (100, 80)


# --- T-04 ------------------------------------------------------------------
def test_la_orientacion_exif_se_aplica() -> None:
    """Una imagen horizontal con orientacion 6 esta girada: se ve vertical.

    Ignorar la orientacion produce miniaturas tumbadas, que es un defecto
    visible para cualquiera que mire el listado.
    """
    original = imagenes.jpeg_con_orientacion_exif(ancho=1200, alto=800, orientacion=6)
    assert imagenes.dimensiones(original) == (1200, 800)

    _, (ancho, alto) = _miniatura_de(original)

    assert alto > ancho
    assert (ancho, alto) == (320, 480)


def test_una_imagen_sin_orientacion_no_se_gira() -> None:
    """Guarda anti-tautologia: normalizar no puede significar girar siempre."""
    original = imagenes.jpeg_con_orientacion_exif(ancho=1200, alto=800, orientacion=1)

    _, (ancho, alto) = _miniatura_de(original)

    assert ancho > alto


# --- T-05 ------------------------------------------------------------------
def test_la_miniatura_no_arrastra_el_exif_del_original() -> None:
    """El EXIF de una fotografia lleva modelo de camara y, a menudo, GPS.

    La miniatura se sirve publicamente, asi que copiar ese bloque publicaria
    metadatos personales que nadie pidio publicar.
    """
    original = imagenes.jpeg_con_orientacion_exif(ancho=600, alto=400)
    with Image.open(BytesIO(original)) as abierta:
        assert abierta.getexif().get(0x010F) == "camara-de-prueba"

    contenido, _ = _miniatura_de(original)

    with Image.open(BytesIO(contenido)) as derivada:
        assert dict(derivada.getexif()) == {}


# --- T-06 ------------------------------------------------------------------
def test_la_miniatura_conserva_la_transparencia() -> None:
    """Aplanar el alfa pondria un fondo negro donde deberia verse el de la pagina."""
    contenido, _ = _miniatura_de(imagenes.png_con_transparencia(ancho=600, alto=400))

    with Image.open(BytesIO(contenido)) as derivada:
        convertida = derivada.convert("RGBA")
        assert convertida.getpixel((convertida.width - 1, 0))[3] == 0  # type: ignore[index]


def test_la_miniatura_pesa_menos_que_el_original() -> None:
    """El proposito de la miniatura es el peso (requisito P-04); si no lo cumple,
    no sirve para nada."""
    original = imagenes.png(ancho=1200, alto=800)

    contenido, _ = _miniatura_de(original)

    assert len(contenido) < len(original)


# --- Modos que WebP no escribe directamente --------------------------------
@pytest.mark.parametrize(
    "constructor",
    [imagenes.png_en_paleta, imagenes.png_en_escala_de_grises],
)
def test_una_imagen_indexada_o_en_grises_produce_miniatura_valida(
    constructor: Callable[..., bytes],
) -> None:
    """PNG admite modos que WebP no escribe: paleta (`P`) y escala de grises (`L`).

    Son imagenes normales, no casos raros: cualquier captura de pantalla
    optimizada puede llegar indexada. Sin conversion previa, `save` fallaria y la
    subida entera se caeria con un error del decodificador en lugar de con un
    error del proyecto.
    """
    contenido, (ancho, alto) = _miniatura_de(constructor(ancho=600, alto=400))

    assert imagenes.formato(contenido) == "WEBP"
    assert (ancho, alto) == (480, 320)


def test_una_imagen_indexada_con_transparencia_la_conserva() -> None:
    """La conversion de paleta a RGB perderia el alfa en silencio."""
    contenido, _ = _miniatura_de(imagenes.png_en_paleta(transparente=True))

    with Image.open(BytesIO(contenido)) as derivada:
        assert derivada.convert("RGBA").getchannel("A").getextrema()[0] == 0
