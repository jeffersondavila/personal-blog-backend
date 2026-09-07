"""Configuracion del log del proceso.

El destino es siempre la **salida estandar**: en local la captura Docker y se
consulta con Portainer; en la nube la recoge CloudWatch (requisito O-07 y
local-to-cloud-mapping.md). El proceso no escribe archivos de log: el sistema
de archivos de Lambda es efimero.

Formato `json` por defecto (requisito O-01). El correlation ID de extremo a
extremo se implementa en `Task/017`; aqui el campo `request_id` se emite solo
cuando quien registra el evento lo aporta explicitamente.

Regla no negociable: **los logs no contienen contrasenas, tokens ni cadenas de
conexion completas** (requisito S-08).

Todas las marcas de tiempo se emiten en **UTC de forma explicita**, con
`timezone.utc` en el formato JSON y `time.gmtime` en el de texto. No se delega
en la zona horaria del sistema: el proceso corre en Windows durante el
desarrollo, en un contenedor Linux en local y en Lambda en la nube, y una linea
de log solo es correlacionable si su instante significa lo mismo en los tres.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any, Final

from app.shared.logging.contexto import es_request_id_valido, request_id_actual
from app.shared.logging.redaccion import redactar_contexto, redactar_texto

# Atributos que `logging.LogRecord` trae de serie. Todo lo que no este aqui se
# considera contexto anadido por quien registra y se emite dentro de `context`.
_RESERVED_RECORD_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

_TEXT_FORMAT: Final[str] = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

#: El sufijo `Z` es literal: `time.gmtime` ya devuelve UTC, de modo que `%z`
#: quedaria vacio y la marca resultaria ambigua.
_TEXT_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"


def format_utc_timestamp(created: float) -> str:
    """Convierte un instante de `LogRecord.created` en ISO 8601 UTC.

    Devuelve siempre la forma `2026-08-11T20:15:30.123Z`: precision de
    milisegundos y sufijo `Z`. La conversion es explicita —`timezone.utc`— y por
    tanto no la altera la zona horaria del sistema ni la variable `TZ`.
    """
    momento = datetime.fromtimestamp(created, tz=UTC)
    return f"{momento:%Y-%m-%dT%H:%M:%S}.{momento.microsecond // 1000:03d}Z"


class UtcClockFormatter(logging.Formatter):
    """Formateador cuyo reloj es UTC en lugar de la hora local.

    `logging.Formatter` convierte con `time.localtime` de serie: en Windows eso
    produce la hora local del desarrollador y dentro del contenedor coincide con
    UTC solo porque su entorno ya esta en UTC. Sustituir el `converter` hace la
    decision explicita y la vuelve independiente del sistema operativo.
    """

    @staticmethod
    def converter(timestamp: float | None = None) -> time.struct_time:
        """Descompone el instante en UTC (reemplaza a `time.localtime`)."""
        return time.gmtime(timestamp)


class UtcTextFormatter(UtcClockFormatter):
    """Formato de texto legible, con la marca de tiempo en UTC."""

    def format(self, record: logging.LogRecord) -> str:
        texto = redactar_texto(super().format(record))
        contexto = redactar_contexto(
            {
                clave: valor
                for clave, valor in record.__dict__.items()
                if clave not in _RESERVED_RECORD_ATTRIBUTES and not clave.startswith("_")
            }
        )
        if contexto:
            texto += " " + json.dumps(contexto, ensure_ascii=False, default=str)
        return texto


class JsonLogFormatter(UtcClockFormatter):
    """Formatea cada registro como una sola linea JSON.

    Campos fijos: `timestamp` (ISO 8601 en UTC), `level`, `logger`, `message`,
    `module` y `line`. `context` aparece solo si el registro lleva atributos
    propios, y `exception` solo si hay excepcion asociada.

    El `timestamp` no pasa por `formatTime`: lo construye
    `format_utc_timestamp`, que fija tanto la zona como la precision.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": format_utc_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            # El mensaje pasa por el redactor porque un secreto puede llegar
            # interpolado en el propio texto, sin ninguna clave que lo delate
            # (requisito O-08, riesgo R-36).
            "message": redactar_texto(record.getMessage()),
            "module": record.module,
            "line": record.lineno,
        }

        context = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_ATTRIBUTES and not key.startswith("_")
        }
        context = redactar_contexto(context)
        if context:
            payload["context"] = context

        # La traza es la via de fuga que R-36 describe: una excepcion de driver
        # puede traer la cadena de conexion entera. Se redacta el texto ya
        # formateado, que incluye la cadena de `__cause__`.
        if record.exc_info is not None:
            payload["exception"] = redactar_texto(self.formatException(record.exc_info))
        if record.stack_info is not None:
            payload["stack"] = redactar_texto(self.formatStack(record.stack_info))

        return json.dumps(payload, ensure_ascii=False, default=str)


class FiltroDeCorrelacion(logging.Filter):
    """Anade `request_id` a todo registro emitido dentro de una peticion.

    Es un `Filter` y no un `Formatter` propio por dos razones: el valor queda
    como atributo del `LogRecord`, asi que aparece **tambien** con
    `BLOG_LOG_FORMAT=text`; y el formateador no necesita conocer el concepto de
    peticion.

    Fuera de una peticion —el arranque, un script— no hay identificador y **no
    se inventa uno**: su ausencia significa "esto no ocurrio dentro de ninguna
    peticion", que es informacion util.

    Nunca sobrescribe un `request_id` que el llamante haya pasado de forma
    explicita en `extra`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            actual = request_id_actual()
            if actual is None and record.name == "uvicorn.error" and record.exc_info:
                # ASGI ya restauro el contexto cuando Uvicorn emite este error.
                candidato = getattr(record.exc_info[1], "_blog_request_id", None)
                if isinstance(candidato, str) and es_request_id_valido(candidato):
                    actual = candidato
            if actual is not None:
                record.request_id = actual
        return True


def configure_logging(level: str = "INFO", log_format: str = "json") -> None:
    """Configura el log raiz del proceso.

    Es idempotente: reemplaza los manejadores existentes en lugar de anadir
    otro, de modo que llamarla dos veces no duplica cada linea.
    """
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLogFormatter() if log_format == "json" else _text_formatter())
    handler.addFilter(FiltroDeCorrelacion())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn instala sus propios manejadores con formato propio. Se
    # desactivan para que toda la salida del proceso tenga un unico formato.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # `uvicorn.access` queda silenciado desde `Task/017`: lo **sustituye** el
    # evento de peticion de `middleware.py`, que dice lo mismo y ademas lleva
    # `request_id` y `duration_ms` como campos propios en lugar de una cadena.
    #
    # Se silencia SOLO el logger de acceso. `uvicorn.error` —arranque, apagado y
    # errores del servidor— se conserva intacto: perderlo dejaria el proceso sin
    # diagnostico de servidor, que es un precio que esta tarea no paga.
    logging.getLogger("uvicorn.access").disabled = True


def _text_formatter() -> logging.Formatter:
    return UtcTextFormatter(fmt=_TEXT_FORMAT, datefmt=_TEXT_DATE_FORMAT)


def get_logger(name: str) -> logging.Logger:
    """Devuelve el logger del modulo indicado."""
    return logging.getLogger(name)
