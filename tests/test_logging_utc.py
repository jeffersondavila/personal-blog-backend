"""Pruebas del reloj del log: las marcas de tiempo son UTC reales.

Son deterministas por construccion: cada prueba fabrica un `LogRecord` con un
instante **conocido** en lugar de leer el reloj del sistema, de modo que el
resultado no depende de la maquina ni del momento de la ejecucion.

Existen porque el formateador declara emitir UTC y antes lo delegaba en
`logging.Formatter.formatTime`, que usa `time.localtime`: en Windows producia la
hora local y dentro del contenedor coincidia con UTC solo porque su entorno ya
estaba en UTC. El comportamiento dependia del sistema operativo.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from app.shared.logging import JsonLogFormatter, configure_logging, format_utc_timestamp

#: `time.tzset` solo existe en Unix. Se obtiene asi —y no con `time.tzset`
#: directamente— para que el analisis de tipos sea valido en Windows y en Linux
#: sin necesidad de silenciar el error en uno de los dos.
_tzset: Callable[[], None] | None = getattr(time, "tzset", None)

#: Instante de referencia. En cualquier zona al oeste de Greenwich la hora local
#: correspondiente es distinta, lo que hace observable un error de conversion.
_INSTANTE = datetime(2026, 8, 11, 20, 15, 30, 123000, tzinfo=UTC)
_EPOCH = _INSTANTE.timestamp()
_ESPERADO_JSON = "2026-08-11T20:15:30.123Z"
_ESPERADO_TEXTO = "2026-08-11T20:15:30Z"

#: Instantes adicionales: mediodia, una madrugada que en UTC-6 cae el dia
#: anterior, y el ultimo segundo del ano.
_CASOS: list[tuple[datetime, str]] = [
    (datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC), "2026-08-11T12:00:00.000Z"),
    (datetime(2026, 1, 1, 0, 30, 0, 500000, tzinfo=UTC), "2026-01-01T00:30:00.500Z"),
    (datetime(2026, 12, 31, 23, 59, 59, 999000, tzinfo=UTC), "2026-12-31T23:59:59.999Z"),
]


def _registro_en(instante: float) -> logging.LogRecord:
    """Construye un registro cuyo `created` es el instante indicado."""
    record = logging.LogRecord(
        name="app.prueba",
        level=logging.INFO,
        pathname=__file__,
        lineno=7,
        msg="Instante conocido",
        args=(),
        exc_info=None,
    )
    record.created = instante
    record.msecs = (instante - int(instante)) * 1000
    return record


def _formatear(instante: float) -> dict[str, Any]:
    resultado: dict[str, Any] = json.loads(JsonLogFormatter().format(_registro_en(instante)))
    return resultado


@pytest.fixture
def _log_raiz_restaurado() -> Iterator[None]:
    """Devuelve el logger raiz a su estado previo tras la prueba."""
    raiz = logging.getLogger()
    manejadores = list(raiz.handlers)
    nivel = raiz.level
    yield
    raiz.handlers = manejadores
    raiz.setLevel(nivel)


def test_el_timestamp_json_es_el_instante_utc_esperado() -> None:
    assert _formatear(_EPOCH)["timestamp"] == _ESPERADO_JSON


@pytest.mark.parametrize(("instante", "esperado"), _CASOS)
def test_cada_instante_se_representa_en_utc(instante: datetime, esperado: str) -> None:
    """Incluye una madrugada que, en la zona local de desarrollo, es el dia anterior."""
    assert _formatear(instante.timestamp())["timestamp"] == esperado


def test_el_timestamp_json_termina_en_z_y_no_lleva_offset_local() -> None:
    marca = _formatear(_EPOCH)["timestamp"]

    assert marca.endswith("Z")
    # Ni el offset local (`-0600`, `-06:00`) ni ningun otro desplazamiento.
    assert re.search(r"[+-]\d{2}:?\d{2}$", marca) is None


def test_el_timestamp_json_se_reinterpreta_como_el_mismo_instante() -> None:
    """La marca no solo tiene forma de UTC: representa el instante correcto."""
    marca = _formatear(_EPOCH)["timestamp"]

    releido = datetime.fromisoformat(marca.replace("Z", "+00:00"))

    assert releido.utcoffset() is not None
    assert releido.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert releido == _INSTANTE


def test_el_formateador_de_texto_tambien_usa_utc(_log_raiz_restaurado: None) -> None:
    """El formato `text` documenta timestamps UTC, luego debe emitirlos."""
    configure_logging(level="INFO", log_format="text")
    formateador = logging.getLogger().handlers[0].formatter
    assert formateador is not None

    linea = formateador.format(_registro_en(_EPOCH))

    assert linea.startswith(_ESPERADO_TEXTO)
    assert re.search(r"[+-]\d{4}", linea) is None


def test_el_timestamp_no_coincide_con_la_hora_local_del_host() -> None:
    """En un host desplazado de UTC, emitir la hora local seria un fallo visible."""
    local = time.localtime(_EPOCH)
    if local[:6] == time.gmtime(_EPOCH)[:6]:
        pytest.skip("el host ya opera en UTC: la diferencia no es observable aqui")

    hora_local = time.strftime("%Y-%m-%dT%H:%M:%S", local)

    assert hora_local not in _formatear(_EPOCH)["timestamp"]


@pytest.mark.skipif(_tzset is None, reason="time.tzset no existe en Windows")
def test_la_variable_tz_no_altera_el_timestamp() -> None:
    """La conversion es explicita, asi que `TZ` no puede desplazarla.

    Se restaura el valor original: la zona horaria del proceso es estado global
    y ninguna prueba debe dejarla cambiada.
    """
    assert _tzset is not None
    original = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Pacific/Kiritimati"  # UTC+14, el extremo opuesto
        _tzset()

        assert _formatear(_EPOCH)["timestamp"] == _ESPERADO_JSON
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        _tzset()


def test_la_conversion_publica_es_la_que_usa_el_formateador() -> None:
    assert format_utc_timestamp(_EPOCH) == _formatear(_EPOCH)["timestamp"]
