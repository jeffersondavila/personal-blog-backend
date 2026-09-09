"""Guardas contra cuerpos ilimitados y PNG corruptos (S-11)."""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.modules.media.domain.errores import ImagenInvalidaError
from app.modules.media.domain.validacion import TAMANO_MAXIMO_BYTES, validar_imagen
from tests import imagenes


def test_png_con_crc_incorrecto_se_rechaza_aunque_sus_pixeles_decodifiquen() -> None:
    original = imagenes.png(ancho=8, alto=8)
    posicion = original.index(b"IDAT")
    longitud = int.from_bytes(original[posicion - 4 : posicion], "big")
    crc = posicion + 4 + longitud
    corrupto = original[:crc] + bytes([original[crc] ^ 1]) + original[crc + 1 :]
    # Control positivo: el decoder actual carga los pixeles sin mirar ese CRC.
    with Image.open(BytesIO(corrupto)) as imagen:
        imagen.load()
        assert imagen.size == (8, 8)
    with pytest.raises(ImagenInvalidaError):
        validar_imagen(corrupto)


@pytest.mark.parametrize("con_longitud", [True, False])
def test_cuerpo_de_subida_excesivo_se_rechaza_antes_de_parsear(
    client: TestClient, con_longitud: bool
) -> None:
    limite = TAMANO_MAXIMO_BYTES + 64 * 1024

    def fragmentos() -> Iterator[bytes]:
        for _ in range(6):
            yield b"x" * (1024 * 1024)

    headers = {"Content-Type": "multipart/form-data; boundary=prueba018"}
    if con_longitud:
        headers["Content-Length"] = str(limite + 1)
    respuesta = client.post("/api/v1/admin/media", content=fragmentos(), headers=headers)
    assert respuesta.status_code == 413
    assert respuesta.json()["error"]["request_id"] == respuesta.headers["x-request-id"]
    assert respuesta.headers.get("cache-control") == "no-store"
