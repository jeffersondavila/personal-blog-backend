"""Generacion de las claves de objeto de un medio.

`software-architecture.md` seccion 3.7 y USER_FLOWS.md B.4 exigen **nombres de
objeto no predecibles**: conocer una URL no puede permitir adivinar otra. Es una
propiedad de seguridad, no de estilo, porque el bucket es privado y el enlace
temporal es lo unico que separa una imagen de quien no deberia verla.

De ahi las dos invariantes que se comprueban aqui:

1. **La clave no es adivinable.** El componente aleatorio es un UUID v4 completo.
2. **El nombre del archivo no participa en la clave.** No hay *sanitizacion* que
   revisar, no hay `..` que escapar y no hay codificacion que se pueda olvidar:
   el nombre original simplemente **no entra** (decision D-010-G).
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.media.domain.claves import (
    LONGITUD_MAXIMA_DE_CLAVE,
    ClavesDelMedio,
    clave_de_la_miniatura,
    generar_claves,
)

#: Nombres que un cliente hostil podria enviar. Ninguno debe influir en la clave.
NOMBRES_HOSTILES = [
    "../../etc/passwd",
    "..\\..\\windows\\system32\\config\\sam",
    "C:\\Users\\victima\\secreto.png",
    "a/b/c.png",
    "foto.png\x00.exe",
    "%2e%2e%2fescape.png",
]


# --- K-01 ------------------------------------------------------------------
def test_las_claves_no_son_predecibles() -> None:
    """Mil claves seguidas, todas distintas y con un UUID v4 real dentro."""
    claves = {generar_claves(extension="png").original for _ in range(1000)}

    assert len(claves) == 1000
    identificador = uuid.UUID(generar_claves(extension="png").original.split("/")[1])
    assert identificador.version == 4


# --- K-02 ------------------------------------------------------------------
def test_dos_cargas_del_mismo_nombre_producen_claves_distintas() -> None:
    """Subir dos veces `foto.png` no puede sobrescribir la primera imagen."""
    primera = generar_claves(extension="png")
    segunda = generar_claves(extension="png")

    assert primera.original != segunda.original
    assert primera.miniatura != segunda.miniatura


# --- K-03 ------------------------------------------------------------------
@pytest.mark.parametrize("nombre", NOMBRES_HOSTILES)
def test_el_nombre_del_archivo_no_puede_influir_en_la_clave(nombre: str) -> None:
    """La firma ni siquiera acepta el nombre: es la forma mas fuerte de la garantia.

    Comprobar que un nombre hostil se *limpia* dejaria abierta la pregunta de si
    la limpieza cubre todos los casos. Que el nombre no sea un argumento cierra
    la pregunta entera.
    """
    claves = generar_claves(extension="png")

    assert nombre not in claves.original
    assert ".." not in claves.original
    assert "\\" not in claves.original
    assert "\x00" not in claves.original
    assert claves.original.count("/") == 2


# --- K-04 ------------------------------------------------------------------
@pytest.mark.parametrize("extension", ["png", "jpg", "webp"])
def test_la_extension_de_la_clave_viene_del_formato_validado(extension: str) -> None:
    claves = generar_claves(extension=extension)

    assert claves.original.endswith(f"/original.{extension}")


def test_la_miniatura_siempre_es_webp() -> None:
    """Decision D-010-H: el derivado tiene un unico formato, sea cual sea el origen."""
    assert generar_claves(extension="jpg").miniatura.endswith("/thumbnail.webp")


# --- K-05 ------------------------------------------------------------------
def test_la_clave_cabe_en_la_columna() -> None:
    """`media_assets.object_key` es `VARCHAR(512)` (data-model.md seccion 4.1).

    Una clave mas larga que la columna se detectaria en produccion, al insertar,
    con el objeto ya escrito en el almacenamiento.
    """
    claves = generar_claves(extension="webp")

    assert len(claves.original) <= LONGITUD_MAXIMA_DE_CLAVE
    assert len(claves.miniatura) <= LONGITUD_MAXIMA_DE_CLAVE


# --- K-06 ------------------------------------------------------------------
def test_la_clave_de_la_miniatura_se_deriva_de_la_del_original() -> None:
    """Decision D-010-I: la miniatura no se persiste porque **se deriva**.

    Es lo que permite borrar la miniatura de un medio conociendo solo su
    `object_key`, sin una columna ni una tabla nuevas.
    """
    claves = generar_claves(extension="png")

    assert clave_de_la_miniatura(claves.original) == claves.miniatura


def test_el_original_y_su_miniatura_comparten_prefijo() -> None:
    claves: ClavesDelMedio = generar_claves(extension="png")

    assert claves.original.rsplit("/", 1)[0] == claves.miniatura.rsplit("/", 1)[0]
