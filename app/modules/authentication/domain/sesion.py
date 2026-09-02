"""Reglas de la sesion administrativa (`Task/011`, decision D-011-B y D-011-C).

Python plano: sin SQLAlchemy, sin FastAPI y sin conocer la tabla que la guarda
(ADR-004). Lo que vive aqui es lo que decide **que es una credencial valida** y
**cuando una sesion sigue viva**, que es la regla que ningun adaptador puede
saltarse.

La credencial y su huella
-------------------------

El cliente recibe una **credencial opaca**: una cadena aleatoria sin significado
que no transporta ninguna afirmacion. La base guarda su **huella SHA-256**, no
la credencial.

Por que SHA-256 y no Argon2 para la credencial —la pregunta es legitima, porque
para contrasenas se hace justo lo contrario—: un KDF lento existe para encarecer
la busqueda por diccionario de un secreto **de baja entropia**, que es lo que es
una contrasena elegida por una persona. Esta credencial tiene **256 bits de
azar**: no hay diccionario que probar, y un hash lento solo anadiria latencia a
cada peticion administrativa. Es el mismo criterio con el que se tratan las
claves de API.

Consecuencia practica: quien lea la tabla `administrator_sessions` **no puede
suplantar a nadie**, porque de la huella no se vuelve a la credencial.

Por que no se compara la credencial en claro
---------------------------------------------

La sesion se busca **por indice unico sobre la huella**. No existe ningun punto
del codigo donde dos credenciales se comparen caracter a caracter, asi que no hay
comparacion propia que pueda escribirse mal (§48 del alcance de la tarea).

Lo que **no** se afirma: que el motor resuelva esa busqueda en tiempo constante.
No se ha medido y no se promete. Lo que se afirma es que la credencial en claro
no se guarda, no se compara y no se registra en ninguna parte.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Final

#: Bytes de azar por credencial. 32 bytes = 256 bits.
BYTES_DE_CREDENCIAL: Final[int] = 32

#: Longitud del hexadecimal de SHA-256. Es tambien la longitud de la columna.
LONGITUD_DE_HUELLA: Final[int] = 64


def entropia_minima_en_bits() -> int:
    """Entropia garantizada de una credencial.

    Existe para que la propiedad quede **fijada por prueba** en lugar de vivir
    solo en un comentario: rebajar `BYTES_DE_CREDENCIAL` pondria roja una prueba
    en vez de pasar inadvertido en una revision.
    """
    return BYTES_DE_CREDENCIAL * 8


def generar_credencial() -> str:
    """Genera la credencial opaca que viaja en la cookie.

    `secrets` es la fuente CSPRNG de la biblioteca estandar. **No** se usa
    `random` —determinista y sembrable—, ni `uuid1` —que incorpora la MAC y el
    reloj—, ni nada derivado del correo o del instante: todos ellos convierten
    una credencial en algo adivinable.
    """
    return secrets.token_urlsafe(BYTES_DE_CREDENCIAL)


def huella_de_credencial(credencial: str) -> str:
    """Huella SHA-256, en hexadecimal, de una credencial.

    Es lo unico que se persiste y lo unico por lo que se busca.
    """
    return hashlib.sha256(credencial.encode("utf-8")).hexdigest()


def sesion_vigente(
    *,
    expira_en: datetime,
    revocada_en: datetime | None,
    ahora: datetime,
) -> bool:
    """Decide si una sesion sigue autorizando.

    Dos condiciones, y las dos se comprueban siempre:

    1. **No ha caducado.** `expira_en` es **exclusivo**: en el instante exacto de
       expiracion la sesion ya no vale.
    2. **No esta revocada.** Basta con que `revocada_en` tenga valor. No se
       compara con `ahora` a proposito: `revoked_at` es una marca de "esto ya no
       vale", no una revocacion programada para mas tarde. Tratarla como una
       fecha futura permitiria que una sesion cerrada siguiera funcionando
       durante un desfase de reloj.
    """
    _exigir_utc(expira_en=expira_en, ahora=ahora, revocada_en=revocada_en)
    if revocada_en is not None:
        return False
    return ahora < expira_en


def _exigir_utc(**instantes: datetime | None) -> None:
    """Rechaza cualquier instante sin zona horaria.

    CONTENT_MODEL.md (invariante 10) exige UTC en todo el proyecto, y comparar un
    instante con zona con otro sin ella es un `TypeError` en Python. Detectarlo
    aqui convierte un descuido en un mensaje que **nombra el argumento
    culpable**, en lugar de en un `500` durante una peticion real.
    """
    for nombre, valor in instantes.items():
        if valor is not None and valor.tzinfo is None:
            raise ValueError(f"'{nombre}' debe ser un instante con zona horaria (UTC)")
