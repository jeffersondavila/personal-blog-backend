"""Contexto de correlacion de la peticion (`Task/017`, requisito O-02).

Que resuelve este modulo
------------------------

Un `ContextVar` con el identificador de la peticion en curso, para que **todo**
lo que se registre durante esa peticion lo lleve **sin pasarlo por parametro**.

Por que un `ContextVar` y no un argumento mas
---------------------------------------------

Llevar el `request_id` hasta el punto donde se emite un log obligaria a
atravesarlo por `presentation`, `application`, `domain` e `infrastructure`. Eso
contaminaria la firma de cada caso de uso con un dato que **no es de negocio**, y
el dominio pasaria a conocer un detalle de transporte. `contextvars` es
biblioteca estandar y es implicito para todo lo que se ejecute dentro de la
peticion, incluidas las tareas `async`.

**El dominio no lee este modulo.** No emite logs: quien los emite es la capa de
transporte, y el `logging.Filter` de `configuration.py` inyecta el valor sin que
nadie tenga que pedirlo. La aplicacion sigue sin acoplarse a ningun destino de
telemetria (principio 9 de `overview.md`, ADR-008).

El contrato del identificador
-----------------------------

Fijado por `Task/017`; detalle completo en la ficha, seccion 9.

- **Cabecera `X-Request-ID`**. Es el unico nombre que el proyecto ya usa en las
  cuatro capas: `error.request_id` (api-contracts.md seccion 7),
  `audit_events.request_id`, `HttpError.requestId` del frontend y
  `request_id_de()` del backend.
- **De 8 a 64 caracteres**, del alfabeto `A-Za-z0-9-_`.
- El maximo **no es una eleccion de estilo**: `audit_events.request_id` es
  `VARCHAR(64)`. Un valor mas largo no fallaria al entrar, sino **al escribir la
  auditoria** de una operacion administrativa ya ejecutada.
- El alfabeto excluye por construccion `\r`, `\n`, espacios y controles, que es
  lo que permitiria **inyectar una linea de log falsa** desde una cabecera.

Politica ante varias cabeceras
------------------------------

**Una peticion tiene exactamente un correlation ID.** Si llegan varios
candidatos no hay forma no arbitraria de elegir, asi que **no se elige ninguno**:
se descartan todos y se genera uno propio.

No se resuelve con *first-wins* ni con *last-wins*. Hacer depender la identidad
de una peticion de esa politica —la del framework, o la de un proxy intermedio,
que puede ser la contraria— produce justo la ambiguedad que un correlation ID
existe para eliminar.

Un valor rechazado **nunca se registra**. Escribirlo en el log seria exactamente
la inyeccion que la validacion evita; solo se registra el booleano
`incoming_request_id_discarded`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from contextvars import ContextVar, Token
from typing import Final

#: Nombre exacto de la cabecera, decidido en `Task/017`.
NOMBRE_DE_LA_CABECERA_DE_CORRELACION: Final[str] = "X-Request-ID"

#: Un identificador de un caracter no discrimina nada al buscar en un log.
LONGITUD_MINIMA_DEL_REQUEST_ID: Final[int] = 8

#: Impuesto por `audit_events.request_id` — `VARCHAR(64)`. No es negociable
#: desde aqui: cambiarlo exigiria una migracion.
LONGITUD_MAXIMA_DEL_REQUEST_ID: Final[int] = 64

#: Alfabeto cerrado. `re.ASCII` es deliberado: sin el, `\w` aceptaria letras
#: Unicode y el alfabeto dejaria de ser cerrado.
_FORMATO_DEL_REQUEST_ID: Final[re.Pattern[str]] = re.compile(
    rf"\A[A-Za-z0-9_-]{{{LONGITUD_MINIMA_DEL_REQUEST_ID},{LONGITUD_MAXIMA_DEL_REQUEST_ID}}}\Z",
    re.ASCII,
)

#: Identificador de la peticion en curso. `None` fuera de una peticion —una
#: tarea de arranque, un script— y esa ausencia es informacion valida: significa
#: "esto no ocurrio dentro de ninguna peticion".
_request_id_actual: ContextVar[str | None] = ContextVar("request_id", default=None)


def generar_request_id() -> str:
    """Crea un identificador nuevo: UUID v4 en su forma canonica."""
    return str(uuid.uuid4())


def es_request_id_valido(valor: str) -> bool:
    """Indica si un valor recibido de fuera puede usarse como correlation ID."""
    return bool(_FORMATO_DEL_REQUEST_ID.fullmatch(valor))


def resolver_request_id(entrantes: Sequence[str]) -> tuple[str, bool]:
    """Decide el identificador de la peticion a partir de lo que llego.

    Devuelve el identificador y **si hubo descarte**, para que quien registre
    pueda emitir `incoming_request_id_discarded` sin ver ningun valor rechazado.

    `entrantes` es la lista **completa** de valores de la cabecera, no uno solo:
    leerla de la forma habitual devolveria un unico valor y **ocultaria** la
    repeticion, que es precisamente el caso que hay que detectar.
    """
    if len(entrantes) == 1 and es_request_id_valido(entrantes[0]):
        return entrantes[0], False
    return generar_request_id(), bool(entrantes)


def request_id_actual() -> str | None:
    """Identificador de la peticion en curso, o `None` fuera de una peticion."""
    return _request_id_actual.get()


def establecer_request_id(valor: str) -> Token[str | None]:
    """Fija el identificador y devuelve el token con el que se deshace.

    Quien llame **debe** devolver el token a `restablecer_request_id` en un
    `finally`. Sin eso, el valor sobrevive a la peticion y puede aparecer en el
    log de otra: el `ContextVar` se copia al contexto, pero el del hilo que
    atiende varias peticiones en serie es el mismo.
    """
    return _request_id_actual.set(valor)


def restablecer_request_id(token: Token[str | None]) -> None:
    """Deshace un `establecer_request_id`, dejando el contexto como estaba."""
    _request_id_actual.reset(token)
