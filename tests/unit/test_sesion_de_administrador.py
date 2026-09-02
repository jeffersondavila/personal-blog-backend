"""Reglas puras de la sesion administrativa (matriz S de `Task/011`).

Aqui no hay base de datos ni HTTP: son las reglas que deciden **que es una
credencial** y **cuando una sesion sigue viva**. La persistencia y el ciclo de
vida completo se comprueban en `tests/integration/`.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.authentication.domain.sesion import (
    LONGITUD_DE_HUELLA,
    entropia_minima_en_bits,
    generar_credencial,
    huella_de_credencial,
    sesion_vigente,
)

AHORA = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


# --- S-01 ------------------------------------------------------------------
def test_la_credencial_es_suficientemente_larga_y_url_safe() -> None:
    """256 bits en base64 url-safe son 43 caracteres sin relleno."""
    credencial = generar_credencial()

    assert len(credencial) >= 43
    assert all(caracter.isalnum() or caracter in "-_" for caracter in credencial)


def test_la_credencial_declara_al_menos_256_bits_de_entropia() -> None:
    assert entropia_minima_en_bits() >= 256


def test_dos_credenciales_consecutivas_nunca_coinciden() -> None:
    """Un generador predecible haria inutil todo lo demas.

    No demuestra aleatoriedad criptografica —eso lo aporta `secrets`, que es la
    fuente CSPRNG de la biblioteca estandar—: demuestra que no se ha colado un
    contador, una marca de tiempo ni un valor derivado del correo.
    """
    generadas = {generar_credencial() for _ in range(200)}

    assert len(generadas) == 200


# --- Huella ----------------------------------------------------------------
def test_la_huella_es_sha256_en_hexadecimal() -> None:
    credencial = generar_credencial()

    esperada = hashlib.sha256(credencial.encode("utf-8")).hexdigest()

    assert huella_de_credencial(credencial) == esperada
    assert len(huella_de_credencial(credencial)) == LONGITUD_DE_HUELLA


def test_la_huella_no_contiene_la_credencial() -> None:
    """Es la propiedad que hace que un volcado de la tabla no permita suplantar."""
    credencial = generar_credencial()

    assert credencial not in huella_de_credencial(credencial)


def test_la_huella_es_estable_para_la_misma_credencial() -> None:
    """Sin esto no se podria buscar la sesion por indice."""
    credencial = generar_credencial()

    assert huella_de_credencial(credencial) == huella_de_credencial(credencial)


def test_credenciales_distintas_producen_huellas_distintas() -> None:
    assert huella_de_credencial("una") != huella_de_credencial("otra")


# --- S-03 y S-04 -----------------------------------------------------------
def test_una_sesion_sin_revocar_y_no_caducada_esta_vigente() -> None:
    assert (
        sesion_vigente(
            expira_en=AHORA + timedelta(hours=1),
            revocada_en=None,
            ahora=AHORA,
        )
        is True
    )


def test_una_sesion_caducada_no_esta_vigente() -> None:
    assert (
        sesion_vigente(
            expira_en=AHORA - timedelta(seconds=1),
            revocada_en=None,
            ahora=AHORA,
        )
        is False
    )


def test_el_instante_exacto_de_expiracion_ya_no_esta_vigente() -> None:
    """El limite se decide una vez y se fija: `expires_at` es exclusivo."""
    assert sesion_vigente(expira_en=AHORA, revocada_en=None, ahora=AHORA) is False


def test_una_sesion_revocada_no_esta_vigente_aunque_no_haya_caducado() -> None:
    """Es la mitad que hace que cerrar sesion signifique algo en el servidor."""
    assert (
        sesion_vigente(
            expira_en=AHORA + timedelta(hours=6),
            revocada_en=AHORA - timedelta(minutes=1),
            ahora=AHORA,
        )
        is False
    )


def test_una_sesion_revocada_en_el_futuro_se_considera_revocada() -> None:
    """`revoked_at` es una marca, no una programacion: si esta, esta revocada."""
    assert (
        sesion_vigente(
            expira_en=AHORA + timedelta(hours=6),
            revocada_en=AHORA + timedelta(minutes=1),
            ahora=AHORA,
        )
        is False
    )


# --- UTC obligatorio -------------------------------------------------------
@pytest.mark.parametrize(
    "argumentos",
    [
        {"expira_en": datetime(2026, 8, 30, 13, 0), "revocada_en": None, "ahora": AHORA},
        {
            "expira_en": AHORA,
            "revocada_en": None,
            "ahora": datetime(2026, 8, 30, 12, 0),
        },
        {
            "expira_en": AHORA,
            "revocada_en": datetime(2026, 8, 30, 11, 0),
            "ahora": AHORA,
        },
    ],
)
def test_un_instante_sin_zona_horaria_se_rechaza(argumentos: dict[str, object]) -> None:
    """Comparar un instante con zona y otro sin ella es un `TypeError` en Python.

    Dejarlo pasar convertiria un descuido en un `500` durante una peticion real.
    Se rechaza aqui, que es donde se ve el nombre del argumento culpable.
    """
    with pytest.raises(ValueError, match="UTC"):
        sesion_vigente(**argumentos)  # type: ignore[arg-type]
