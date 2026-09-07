"""Pruebas del log estructurado."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from app.shared.logging import JsonLogFormatter, configure_logging, get_logger


def _formatear(record: logging.LogRecord) -> dict[str, Any]:
    resultado: dict[str, Any] = json.loads(JsonLogFormatter().format(record))
    return resultado


def _registro(**extra: Any) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.prueba",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="Mensaje de prueba",
        args=(),
        exc_info=None,
    )
    for clave, valor in extra.items():
        setattr(record, clave, valor)
    return record


def test_cada_linea_es_json_valido_con_los_campos_fijos() -> None:
    salida = _formatear(_registro())

    assert salida["level"] == "INFO"
    assert salida["logger"] == "app.prueba"
    assert salida["message"] == "Mensaje de prueba"
    assert salida["line"] == 42
    assert "timestamp" in salida
    assert "module" in salida


def test_el_contexto_adicional_se_emite_aparte() -> None:
    salida = _formatear(_registro(request_id="abc-123", status_code=404))

    assert salida["context"] == {"request_id": "abc-123", "status_code": 404}


def test_sin_contexto_no_se_emite_la_clave() -> None:
    assert "context" not in _formatear(_registro())


def test_la_excepcion_se_incluye_en_el_log_y_no_rompe_el_json() -> None:
    try:
        raise ValueError("fallo controlado")
    except ValueError:
        import sys

        record = _registro()
        record.exc_info = sys.exc_info()

    salida = _formatear(record)

    assert "ValueError" in salida["exception"]
    assert salida["message"] == "Mensaje de prueba"


def test_la_pila_se_incluye_cuando_se_solicita() -> None:
    record = _registro()
    record.stack_info = "Stack (most recent call last):\n  linea de ejemplo"

    salida = _formatear(record)

    assert "linea de ejemplo" in salida["stack"]


def test_un_valor_no_serializable_no_rompe_el_formato() -> None:
    salida = _formatear(_registro(objeto=object()))

    assert "context" in salida
    assert isinstance(salida["context"]["objeto"], str)


def test_configure_logging_es_idempotente() -> None:
    configure_logging(level="INFO", log_format="json")
    tras_la_primera = len(logging.getLogger().handlers)
    configure_logging(level="INFO", log_format="json")

    assert len(logging.getLogger().handlers) == tras_la_primera == 1


def test_configure_logging_aplica_nivel_y_formato() -> None:
    configure_logging(level="warning", log_format="text")
    raiz = logging.getLogger()

    assert raiz.level == logging.WARNING
    assert not isinstance(raiz.handlers[0].formatter, JsonLogFormatter)

    configure_logging(level="INFO", log_format="json")
    assert isinstance(logging.getLogger().handlers[0].formatter, JsonLogFormatter)


def test_el_log_de_la_aplicacion_no_contiene_la_contrasena(
    capsys: pytest.CaptureFixture[str], settings_factory: Any
) -> None:
    """El arranque registra la conexion enmascarada, nunca la contrasena (S-08)."""
    from app.main import create_app

    configuracion = settings_factory(
        database_url="postgresql://usuario:clave_secreta@localhost:5432/base",
        log_format="json",
    )
    create_app(settings=configuracion)

    salida = capsys.readouterr().out
    # `-1` y no `next(...)`: importar `app.main` ejecuta `app = create_app()` a
    # nivel de modulo, asi que cuando este test es el primero en importarlo hay
    # **dos** lineas de arranque y la primera es la de esa instancia, con la
    # configuracion del entorno minimo. Tomar la primera hacia que la prueba
    # dependiera de si otro test habia importado el modulo antes. Fragilidad
    # preexistente, corregida al descubrirla en `Task/017`: la prueba se vuelve
    # determinista, no mas permisiva.
    lineas = [
        json.loads(texto) for texto in salida.splitlines() if "Aplicacion inicializada" in texto
    ]
    linea = lineas[-1]

    assert "clave_secreta" not in salida
    assert linea["context"]["database"] == "postgresql://usuario:***@localhost:5432/base"


def test_get_logger_devuelve_el_logger_del_modulo() -> None:
    assert get_logger("app.modulo").name == "app.modulo"
