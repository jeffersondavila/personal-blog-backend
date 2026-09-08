"""Senuelos sobre el formatter aprobado; no se sustituye su arquitectura."""

from __future__ import annotations

import json
import logging

import pytest

from app.shared.logging import JsonLogFormatter
from app.shared.logging.configuration import UtcTextFormatter
from app.shared.logging.redaccion import redactar_texto

SECRETO = "CANARY018-52c5a064"


@pytest.mark.parametrize(
    "texto",
    [
        f"Cookie: primero={SECRETO}; segundo={SECRETO}",
        f"Set-Cookie: cred={SECRETO}; Path=/; HttpOnly",
        f'Authorization: Digest username="x", response="{SECRETO}"',
        f"password_confirmation={SECRETO}",
        f"access_token={SECRETO}&refresh_token={SECRETO}",
        f"api-key={SECRETO}",
        f"https://{SECRETO}@example.test/recurso",
        f"https://usuario:{SECRETO}/extra@example.test/recurso",
        f'password="antes\\"{SECRETO}"',
    ],
)
def test_redaccion_textual_cubre_cabeceras_y_credenciales_completas(texto: str) -> None:
    resultado = redactar_texto(texto)
    assert SECRETO not in resultado
    assert redactar_texto(resultado) == resultado


@pytest.mark.parametrize("formatter", [JsonLogFormatter(), UtcTextFormatter()])
@pytest.mark.parametrize("superficie", ["mensaje", "contexto", "excepcion"])
def test_senuelo_ausente_en_salida_completa_sin_perder_diagnostico(
    formatter: logging.Formatter, superficie: str
) -> None:
    mensaje = "Fallo de servicio; diagnostico util"
    secreto = f"Cookie: a={SECRETO}; b={SECRETO}"
    registro = logging.LogRecord("app.prueba", logging.ERROR, __file__, 1, mensaje, (), None)
    registro.request_id = "task018-redaccion"
    registro.status_code = 503
    if superficie == "mensaje":
        registro.msg += " " + secreto
    elif superficie == "contexto":
        registro.detalle = {"anidado": [secreto]}
    else:
        error = RuntimeError(secreto)
        error.__cause__ = ValueError(f"api-key={SECRETO}")
        registro.exc_info = (RuntimeError, error, None)
    salida = formatter.format(registro)
    assert SECRETO not in salida
    assert "diagnostico util" in salida
    assert "task018-redaccion" in salida
    assert "503" in salida
    if isinstance(formatter, JsonLogFormatter):
        assert json.loads(salida)["level"] == "ERROR"
