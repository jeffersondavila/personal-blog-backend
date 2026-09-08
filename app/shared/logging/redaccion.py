"""Redaccion de secretos en el log (`Task/017`, requisito O-08, riesgo R-36).

Por que existe este modulo
--------------------------

`Task/005.6` abrio **R-36** con esta causa: la regla S-08 —*"los logs no
contienen contrasenas, tokens ni cadenas de conexion"*— *"se cumple hoy, pero
depende de que **quien registra el evento** no pase un valor sensible: no hay
ningun mecanismo que lo impida"*.

Esto es ese mecanismo. La disciplina de quien llama al logger deja de ser la
unica barrera.

Las dos vias de fuga, y por que hacen falta dos reglas
------------------------------------------------------

1. **Por el nombre del campo.** Alguien pasa `extra={"password": ...}`. Se
   reconoce por la clave, sin mirar el valor.
2. **Por la forma del valor.** Una excepcion de `psycopg` que trae la cadena de
   conexion entera, o una URL prefirmada con su firma. Ahi **no hay clave que
   mirar**: el secreto viaja dentro de un texto cuyo nombre es inocente. Se
   reconoce por patron.

La segunda es la que R-36 describe como *"una excepcion de driver [...] puede
filtrar una credencial"*, y es la razon de que el redactor se aplique tambien al
`message`, a la traza y a la pila, no solo al contexto.

Que NO hace
-----------

**No borra el diagnostico.** Un redactor que vacia todo pasaria cualquier prueba
negativa y dejaria el log inservible. Por eso:

- La DSN conserva esquema, anfitrion, puerto y base: solo pierde la contrasena.
- La excepcion conserva su **tipo** y su mensaje no sensible.
- Los campos operativos —`request_id`, `method`, `path`, `status_code`,
  `duration_ms`, `error_code`— **no se tocan nunca**.

**No trunca.** El valor se sustituye por un marcador fijo. Truncar dejaria el
prefijo del secreto a la vista, y a veces el prefijo ya basta.
"""

from __future__ import annotations

import re
from typing import Any, Final

#: Sustituye al valor completo. Fijo y sin parte del original.
MARCADOR_DE_REDACCION: Final[str] = "[REDACTADO]"

#: Fragmentos de nombre que hacen sensible a un campo. La comparacion es por
#: **contenido** e insensible a mayusculas: `storage_secret_key`,
#: `SECRET_KEY` y `secret` caen todos por el fragmento `secret`.
#:
#: Se usan fragmentos largos y especificos a proposito. `key` a secas marcaria
#: como sensible cualquier campo que hable de una clave de objeto, que es dato
#: operativo legitimo.
_FRAGMENTOS_SENSIBLES: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "authorization",
        "cookie",
        "session",
        "credential",
        "access_key",
        "api_key",
        "private",
        "signature",
        "database_url",
        "dsn",
        "email",
        "body",
    }
)

#: Atributos que las bibliotecas anaden al `LogRecord` y que no son contexto de
#: nadie. `color_message` es de Uvicorn y **llega con secuencias ANSI dentro**:
#: medido en el contenedor durante la definicion de `Task/017`.
ATRIBUTOS_INTERNOS_IGNORADOS: Final[frozenset[str]] = frozenset({"color_message"})

#: Valores que ya son una mascara. El redactor **no los vuelve a redactar**:
#: `Settings.database_url_safe` ya entrega la DSN con `***`, y sustituirlo por
#: otro marcador cambiaria un valor que el proyecto ya fijo sin ganar nada.
#: Tambien es lo que hace idempotente a `redactar_texto`.
_MASCARAS_YA_APLICADAS: Final[frozenset[str]] = frozenset({"***", MARCADOR_DE_REDACCION})

#: Credenciales dentro de una cadena de conexion: `esquema://usuario:SECRETO@host`.
#: `_DSN` cubre la contrasena —que puede contener `/` y `:`, de ahi que la clase
#: solo excluya `@` y espacios— y `_USUARIO_EN_URL` el usuario cuando viaja en la
#: propia URL, con o sin contrasena detras. El **anfitrion se conserva**, porque
#: es el diagnostico: a que servidor se intento conectar (`Task/018`).
_DSN: Final[re.Pattern[str]] = re.compile(r"(?P<inicio>://[^:/\s@]+:)(?P<secreto>[^@\s]+)(?=@)")
_USUARIO_EN_URL: Final[re.Pattern[str]] = re.compile(r"(?P<inicio>://)[^:/\s@]+(?=@)")

# Una cabecera puede contener varios pares (Cookie) o un esquema arbitrario
# (Authorization). Su valor completo ocupa la linea, no el primer token.
#
# Consecuencia deliberada: lo que siga en ESA MISMA linea tambien se descarta.
# Es la direccion segura del error —`Cookie: a=1; b=2` no tiene un delimitador
# fiable donde parar— y no afecta al formato JSON, donde `request_id`,
# `status_code` y el contexto son campos propios y no viajan en el mensaje.
_CABECERA_SENSIBLE: Final[re.Pattern[str]] = re.compile(
    r"\b(?P<clave>Authorization|Cookie|Set-Cookie)\s*:\s*[^\r\n]*", re.IGNORECASE
)

#: Parametros de una URL prefirmada. La firma **es** la credencial: quien la lee
#: accede al objeto sin ninguna otra autenticacion.
_PARAMETROS_FIRMADOS: Final[re.Pattern[str]] = re.compile(
    r"(?P<clave>X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|Signature|AWSAccessKeyId)"
    r"(?P<igual>=)(?P<valor>[^&\s\"]+)",
    re.IGNORECASE,
)

#: Credencial de un esquema de autorizacion HTTP.
_ESQUEMA_DE_AUTORIZACION: Final[re.Pattern[str]] = re.compile(
    r"\b(?P<esquema>Bearer|Basic)\s+(?P<valor>[A-Za-z0-9._~+/=\-\[\]]+)",
    re.IGNORECASE,
)

#: Secuencias de escape ANSI. No son un secreto, pero ensucian el JSON y no
#: aportan nada a un log que ya no se lee en una terminal con color.
_SECUENCIAS_ANSI: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Valores etiquetados en texto de drivers, repr de diccionarios y excepciones.
# El grupo con comillas incluye espacios; el valor sin comillas acaba en un
# delimitador. Los secretos opacos SIN etiqueta conservan el limite documentado.
_VALOR_ETIQUETADO: Final[re.Pattern[str]] = re.compile(
    r"(?P<clave>[\w-]*(?:"
    + "|".join(fragmento.replace("_", "[_-]") for fragmento in sorted(_FRAGMENTOS_SENSIBLES))
    + r")[\w-]*)"
    r"[\"']?\s*[:=]\s*(?:\[REDACTADO\]|\*{3}|[bru]?\"(?:\\.|[^\"\\])*\"|"
    r"[bru]?'(?:\\.|[^'\\])*'|[^\s,;}\]\"']+)",
    re.IGNORECASE,
)
_CORREO: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Z0-9.!#$%&'*+/=?^_`{|}~:\-\]])"
    r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+",
    re.IGNORECASE,
)


def es_clave_sensible(clave: str) -> bool:
    """Indica si un nombre de campo basta para considerar sensible su valor."""
    normalizada = clave.lower().replace("-", "_")
    return any(fragmento in normalizada for fragmento in _FRAGMENTOS_SENSIBLES)


def redactar_texto(texto: str) -> str:
    """Sustituye por el marcador todo lo que tenga forma de secreto.

    Es **idempotente**: el marcador no vuelve a coincidir con nada que produzca
    un resultado distinto, asi que aplicarla dos veces da lo mismo que una.
    """
    sin_ansi = _SECUENCIAS_ANSI.sub("", texto)
    sin_cabeceras = _CABECERA_SENSIBLE.sub(rf"\g<clave>={MARCADOR_DE_REDACCION}", sin_ansi)
    sin_dsn = _DSN.sub(_redactar_la_dsn, sin_cabeceras)
    sin_dsn = _USUARIO_EN_URL.sub(rf"\g<inicio>{MARCADOR_DE_REDACCION}", sin_dsn)
    sin_firma = _PARAMETROS_FIRMADOS.sub(rf"\g<clave>\g<igual>{MARCADOR_DE_REDACCION}", sin_dsn)
    sin_autorizacion = _ESQUEMA_DE_AUTORIZACION.sub(
        rf"\g<esquema> {MARCADOR_DE_REDACCION}", sin_firma
    )
    sin_etiquetados = _VALOR_ETIQUETADO.sub(rf"\g<clave>={MARCADOR_DE_REDACCION}", sin_autorizacion)
    return _CORREO.sub(MARCADOR_DE_REDACCION, sin_etiquetados)


def _redactar_la_dsn(coincidencia: re.Match[str]) -> str:
    """Sustituye la contrasena de una DSN, salvo que ya sea una mascara."""
    secreto = coincidencia.group("secreto")
    if secreto in _MASCARAS_YA_APLICADAS:
        return coincidencia.group(0)
    return f"{coincidencia.group('inicio')}{MARCADOR_DE_REDACCION}"


def redactar_valor(clave: str, valor: Any) -> Any:
    """Redacta un valor de contexto segun su nombre y su forma.

    Recorre diccionarios y listas: un secreto anidado dentro de `details` no
    esta menos expuesto por estar mas hondo.
    """
    if es_clave_sensible(clave):
        return MARCADOR_DE_REDACCION
    return _redactar_estructura(valor)


def _redactar_estructura(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {
            str(sub_clave): redactar_valor(str(sub_clave), sub_valor)
            for sub_clave, sub_valor in valor.items()
        }
    if isinstance(valor, list | tuple):
        return [_redactar_estructura(elemento) for elemento in valor]
    if isinstance(valor, str):
        return redactar_texto(valor)
    return valor


def redactar_contexto(contexto: dict[str, Any]) -> dict[str, Any]:
    """Aplica la politica a todo el contexto de un registro."""
    return {
        clave: redactar_valor(clave, valor)
        for clave, valor in contexto.items()
        if clave not in ATRIBUTOS_INTERNOS_IGNORADOS
    }
