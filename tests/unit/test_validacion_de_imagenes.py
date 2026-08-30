"""Validacion de una imagen subida, sobre su **contenido real**.

USER_FLOWS.md B.4 lo pide en dos palabras —"el backend valida tipo MIME y
tamano"— y los requisitos S-11 y S-02 lo repiten. Lo que esas frases no dicen, y
es lo que decide si la validacion sirve de algo, es **contra que** se valida.

Aqui se valida contra los bytes. Ni la extension del nombre, ni el
`Content-Type` que declara el cliente, ni la firma de los primeros bytes: se
**decodifica** la imagen. Las tres alternativas son afirmaciones del cliente, y
un cliente hostil las controla enteras.

`Task/018` endurecera esta validacion; `Task/010` fija la base y sus limites
(decisiones D-010-E y D-010-F).
"""

from __future__ import annotations

import hashlib

import pytest

from app.modules.media.domain.errores import (
    ImagenDemasiadoGrandeError,
    ImagenInvalidaError,
    TipoDeImagenNoPermitidoError,
)
from app.modules.media.domain.validacion import (
    PIXELES_MAXIMOS,
    TAMANO_MAXIMO_BYTES,
    validar_imagen,
)
from tests import imagenes


# --- I-01 ------------------------------------------------------------------
def test_una_imagen_valida_se_acepta_con_sus_dimensiones_reales() -> None:
    contenido = imagenes.png(ancho=640, alto=480)

    validada = validar_imagen(contenido)

    assert validada.mime_type == "image/png"
    assert validada.extension == "png"
    assert (validada.width, validada.height) == (640, 480)
    assert validada.size_bytes == len(contenido)


# --- I-02 ------------------------------------------------------------------
def test_un_archivo_que_no_es_imagen_se_rechaza() -> None:
    with pytest.raises(ImagenInvalidaError):
        validar_imagen(b"esto no es una imagen, por mucho que se llame foto.png")


# --- I-03 ------------------------------------------------------------------
def test_manda_el_contenido_y_no_lo_que_diga_el_nombre() -> None:
    """El defecto clasico: un ejecutable llamado `.jpg`.

    La funcion **ni siquiera recibe** el nombre del archivo. Es la version
    fuerte de la garantia: no hay forma de que una decision dependa de el.
    """
    un_png = imagenes.png(ancho=32, alto=32)

    validada = validar_imagen(un_png)

    assert validada.mime_type == "image/png"
    assert validada.extension == "png"


def test_un_jpeg_se_reconoce_como_jpeg_aunque_venga_de_donde_venga() -> None:
    """Guarda anti-tautologia: si todo se identificara como PNG, la prueba
    anterior pasaria igual sin comprobar nada."""
    validada = validar_imagen(imagenes.jpeg(ancho=32, alto=32))

    assert validada.mime_type == "image/jpeg"
    assert validada.extension == "jpg"


# --- I-04 ------------------------------------------------------------------
def test_una_imagen_truncada_se_rechaza() -> None:
    """La cabecera es valida y las dimensiones tambien: solo decodificar lo detecta."""
    with pytest.raises(ImagenInvalidaError):
        validar_imagen(imagenes.png_truncado())


# --- I-05 ------------------------------------------------------------------
def test_un_formato_fuera_de_la_lista_se_rechaza_por_su_tipo() -> None:
    """El GIF se decodifica sin problema: lo rechaza la **politica** (D-010-E)."""
    with pytest.raises(TipoDeImagenNoPermitidoError):
        validar_imagen(imagenes.gif())


def test_un_svg_no_llega_a_considerarse_una_imagen() -> None:
    """SVG es XML con capacidad de script, y no un formato rasterizado.

    Se rechaza como contenido invalido y no como tipo no permitido, porque no
    llega a identificarse como imagen: es la consecuencia directa de validar
    decodificando. Lo que importa —y es lo que esta prueba fija— es que **no se
    almacena**, no cual de los dos errores sale.
    """
    with pytest.raises(ImagenInvalidaError):
        validar_imagen(imagenes.SVG_CON_SCRIPT)


# --- I-06 y I-07 -----------------------------------------------------------
def test_el_tamano_limite_exacto_se_acepta() -> None:
    validada = validar_imagen(imagenes.png_de_exactamente(TAMANO_MAXIMO_BYTES))

    assert validada.size_bytes == TAMANO_MAXIMO_BYTES


def test_un_byte_por_encima_del_limite_se_rechaza() -> None:
    with pytest.raises(ImagenDemasiadoGrandeError):
        validar_imagen(imagenes.png_de_exactamente(TAMANO_MAXIMO_BYTES + 1))


# --- I-08 ------------------------------------------------------------------
def test_un_contenido_vacio_se_rechaza() -> None:
    with pytest.raises(ImagenInvalidaError):
        validar_imagen(b"")


# --- I-09 ------------------------------------------------------------------
def test_una_imagen_con_demasiados_pixeles_se_rechaza() -> None:
    """El limite de bytes no protege de una *decompression bomb*.

    Esta imagen ocupa menos de cien bytes y declara ochenta millones de pixeles.
    Pasa holgadamente el limite de tamano y agotaria la memoria al decodificarse,
    asi que el rechazo tiene que ocurrir **antes** de decodificar.
    """
    declarados = imagenes.png_con_dimensiones_declaradas(10_000, 8_000)
    assert len(declarados) < TAMANO_MAXIMO_BYTES
    assert 10_000 * 8_000 > PIXELES_MAXIMOS

    with pytest.raises(ImagenDemasiadoGrandeError):
        validar_imagen(declarados)


def test_una_bomba_que_el_decodificador_detecta_tambien_se_rechaza_igual() -> None:
    """Pillow tiene su propio umbral, mas alto que el del proyecto.

    Por encima de el lanza su propia excepcion, que **no** puede escapar como un
    error interno: debe llegar al llamante con el mismo significado que el
    limite propio.
    """
    with pytest.raises(ImagenDemasiadoGrandeError):
        validar_imagen(imagenes.png_con_dimensiones_declaradas(40_000, 40_000))


# --- I-10 ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("constructor", "mime", "extension"),
    [
        (imagenes.png, "image/png", "png"),
        (imagenes.jpeg, "image/jpeg", "jpg"),
        (imagenes.webp, "image/webp", "webp"),
    ],
)
def test_los_tres_formatos_permitidos_se_aceptan(
    constructor: object, mime: str, extension: str
) -> None:
    validada = validar_imagen(constructor(ancho=64, alto=64))  # type: ignore[operator]

    assert validada.mime_type == mime
    assert validada.extension == extension


# --- I-11 ------------------------------------------------------------------
def test_el_checksum_es_el_de_los_bytes_almacenados() -> None:
    """`media_assets.checksum` es SHA-256 en hexadecimal (data-model.md 4.1).

    Se calcula sobre el contenido, nunca sobre el nombre: un checksum del nombre
    coincidiria para dos imagenes distintas llamadas igual, que es exactamente
    lo contrario de lo que la columna sirve para detectar.
    """
    contenido = imagenes.png(ancho=64, alto=64)

    validada = validar_imagen(contenido)

    assert validada.checksum == hashlib.sha256(contenido).hexdigest()
    assert len(validada.checksum) == 64


def test_dos_imagenes_distintas_tienen_checksums_distintos() -> None:
    """Guarda anti-tautologia del caso anterior."""
    primera = validar_imagen(imagenes.png(ancho=64, alto=64))
    segunda = validar_imagen(imagenes.png(ancho=65, alto=64))

    assert primera.checksum != segunda.checksum


def test_el_contenido_validado_es_el_mismo_que_entro() -> None:
    """La validacion **no** recodifica el original: lo que se guarda es lo que llego."""
    contenido = imagenes.png(ancho=64, alto=64)

    assert validar_imagen(contenido).contenido == contenido
