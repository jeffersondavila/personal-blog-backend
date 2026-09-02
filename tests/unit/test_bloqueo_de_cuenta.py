"""Reglas puras del bloqueo de cuenta (matriz B de `Task/011`).

`Task/008` dejo `failed_login_attempts` y `locked_until` en el esquema **sin
comportamiento**. Aqui se decide cual es ese comportamiento, en Python plano y
sin base de datos: la persistencia y la concurrencia se comprueban aparte, contra
PostgreSQL real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.authentication.domain.bloqueo import (
    cuenta_bloqueada,
    estado_tras_un_fallo,
)

AHORA = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
UMBRAL = 5
DURACION = timedelta(minutes=15)


def _tras_un_fallo(fallos: int, bloqueado_hasta: datetime | None = None) -> tuple[int, object]:
    resultado = estado_tras_un_fallo(
        fallos=fallos,
        bloqueado_hasta=bloqueado_hasta,
        ahora=AHORA,
        umbral=UMBRAL,
        duracion=DURACION,
    )
    return resultado.fallos, resultado.bloqueado_hasta


# --- Estado del bloqueo ----------------------------------------------------
def test_una_cuenta_sin_marca_no_esta_bloqueada() -> None:
    assert cuenta_bloqueada(None, ahora=AHORA) is False


def test_una_cuenta_con_bloqueo_en_el_futuro_esta_bloqueada() -> None:
    assert cuenta_bloqueada(AHORA + timedelta(minutes=1), ahora=AHORA) is True


def test_una_cuenta_con_bloqueo_ya_vencido_no_esta_bloqueada() -> None:
    assert cuenta_bloqueada(AHORA - timedelta(seconds=1), ahora=AHORA) is False


def test_el_instante_exacto_de_vencimiento_ya_no_bloquea() -> None:
    """El limite se decide una vez: `locked_until` es exclusivo."""
    assert cuenta_bloqueada(AHORA, ahora=AHORA) is False


# --- B-01 y B-02 -----------------------------------------------------------
def test_el_primer_fallo_incrementa_sin_bloquear() -> None:
    assert _tras_un_fallo(0) == (1, None)


@pytest.mark.parametrize("previos", [1, 2, 3])
def test_los_fallos_intermedios_solo_incrementan(previos: int) -> None:
    fallos, bloqueado_hasta = _tras_un_fallo(previos)

    assert fallos == previos + 1
    assert bloqueado_hasta is None


def test_el_fallo_anterior_al_umbral_todavia_no_bloquea() -> None:
    """Control del limite: `umbral - 1` fallos acumulados no bastan."""
    assert _tras_un_fallo(UMBRAL - 2) == (UMBRAL - 1, None)


# --- B-03 ------------------------------------------------------------------
def test_el_fallo_que_alcanza_el_umbral_bloquea() -> None:
    fallos, bloqueado_hasta = _tras_un_fallo(UMBRAL - 1)

    assert fallos == UMBRAL
    assert bloqueado_hasta == AHORA + DURACION


# --- Bloqueo vigente: ni se extiende ni se acumula --------------------------
def test_un_fallo_durante_el_bloqueo_no_lo_alarga() -> None:
    """Si cada intento desplazara el bloqueo, bastaria con seguir intentando
    para dejar al **unico** administrador fuera de su propio panel para siempre.

    El bloqueo acota la adivinacion; convertirlo en una negacion de servicio
    contra el propietario cambiaria un problema por otro peor.
    """
    vigente = AHORA + timedelta(minutes=5)

    assert _tras_un_fallo(UMBRAL, vigente) == (UMBRAL, vigente)


def test_los_fallos_durante_el_bloqueo_no_se_acumulan() -> None:
    """No se evalua ninguna credencial mientras la cuenta esta bloqueada, asi
    que no hay ningun intento real que contar.
    """
    vigente = AHORA + timedelta(minutes=5)

    fallos, _ = _tras_un_fallo(UMBRAL + 3, vigente)

    assert fallos == UMBRAL + 3


# --- B-05: el bloqueo vencido reinicia la cuenta ---------------------------
def test_el_primer_fallo_tras_un_bloqueo_vencido_empieza_de_cero() -> None:
    """Sin este reinicio, el contador se quedaria en el umbral y **el primer
    fallo posterior volveria a bloquear de inmediato**: el bloqueo temporal se
    comportaria como uno permanente en la practica.
    """
    fallos, bloqueado_hasta = _tras_un_fallo(UMBRAL, AHORA - timedelta(seconds=1))

    assert fallos == 1
    assert bloqueado_hasta is None


def test_un_bloqueo_vencido_no_deja_marca_residual() -> None:
    """La marca vencida se limpia: dejarla obligaria a cada lector posterior a
    recordar que hay que compararla con el reloj.
    """
    _, bloqueado_hasta = _tras_un_fallo(2, AHORA - timedelta(hours=3))

    assert bloqueado_hasta is None


# --- Umbral de uno ---------------------------------------------------------
def test_con_umbral_de_uno_el_primer_fallo_bloquea() -> None:
    """Caso limite de la configuracion, que admite `ge=1`.

    No es un valor recomendado, pero si es alcanzable, y una regla que se
    comportara de forma rara en su propio limite seria una trampa.
    """
    resultado = estado_tras_un_fallo(
        fallos=0, bloqueado_hasta=None, ahora=AHORA, umbral=1, duracion=DURACION
    )

    assert resultado.fallos == 1
    assert resultado.bloqueado_hasta == AHORA + DURACION


# --- UTC obligatorio -------------------------------------------------------
def test_un_instante_sin_zona_horaria_se_rechaza() -> None:
    with pytest.raises(ValueError, match="UTC"):
        cuenta_bloqueada(datetime(2026, 8, 30, 12, 0), ahora=AHORA)
