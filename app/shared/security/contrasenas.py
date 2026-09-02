"""Hash y verificacion de contrasenas con Argon2id (`Task/011`, D-011-F).

Por que Argon2id
----------------

Es el ganador de la *Password Hashing Competition* y la primera recomendacion
vigente de OWASP para contrasenas nuevas. Frente a las alternativas evaluadas:

- **bcrypt** es maduro pero **trunca la entrada a 72 bytes** y no es
  *memory-hard*, asi que su coste para un atacante con GPU crece mucho menos.
- **`hashlib.scrypt`**, de la biblioteca estandar, es aceptable para OWASP y no
  anadiria dependencia, pero obligaria a **inventar la serializacion** de la sal
  y los parametros dentro del hash y la logica de rehash. Eso es escribir
  formato criptografico propio para no instalar un paquete: mal negocio.
- **`passlib`** queda descartada: sin publicacion desde 2020 y con
  incompatibilidades conocidas frente a `bcrypt` 4.x.

Por que estos parametros y no los maximos
------------------------------------------

Son los **minimos recomendados por OWASP** para Argon2id: `m=19456` KiB,
`t=2`, `p=1`. El destino de este codigo es **AWS Lambda**, donde la variante de
64 MiB de la RFC 9106 encareceria la memoria asignada y el arranque en frio
(requisito P-07) sin beneficio proporcional: para llegar a probar contrasenas en
masa un atacante tendria que atravesar antes el limite de tasa por IP y el
bloqueo de cuenta, que son las defensas que de verdad acotan el numero de
intentos.

No son configuracion de entorno **a proposito**. Bajarlos es una decision de
seguridad que debe verse y discutirse, no una variable que alguien ajusta para
que una prueba tarde menos. La regresion vive en
`tests/unit/test_hash_de_contrasenas.py`.

Lo que este modulo no hace
--------------------------

- **No compara nada a mano.** La comparacion la hace `argon2-cffi`; escribir una
  propia es exactamente el error que este proyecto no comete.
- **No registra nunca la contrasena** —ni en un log, ni en un mensaje de error,
  ni en una excepcion que se propague— (requisito S-08).
- **No conoce administradores, sesiones ni HTTP.** Es una primitiva transversal
  de `shared` (software-architecture.md seccion 3.4).
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

_HASHER: Final[PasswordHasher] = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

#: Parametros vigentes, **leidos del propio hasher** y no escritos dos veces.
#: Se exponen para que una prueba pueda fijarlos y para que el reporte de la
#: tarea no tenga que copiarlos a mano; derivarlos de la instancia impide que la
#: constante publicada y los parametros reales se separen sin que nadie lo vea.
PARAMETROS_DE_ARGON2: Final[Mapping[str, int]] = MappingProxyType(
    {
        "time_cost": _HASHER.time_cost,
        "memory_cost": _HASHER.memory_cost,
        "parallelism": _HASHER.parallelism,
        "hash_len": _HASHER.hash_len,
        "salt_len": _HASHER.salt_len,
    }
)

#: Hash contra el que se verifica cuando el correo recibido no corresponde a
#: ningun administrador (ver `verificacion_senuelo`).
#:
#: Se calcula sobre un valor **aleatorio de 256 bits generado en cada arranque**:
#: no es una constante que alguien pueda reconocer, no se guarda en ninguna
#: parte y ninguna entrada real puede coincidir con el. Lo unico que importa de
#: este hash es que verificarlo cueste lo mismo que verificar uno de verdad.
_HASH_SENUELO: Final[str] = _HASHER.hash(secrets.token_urlsafe(32))


def hash_de_contrasena(contrasena: str) -> str:
    """Devuelve el hash Argon2id de una contrasena.

    La sal la genera la biblioteca en cada llamada, asi que dos hashes de la
    misma contrasena **son distintos**: sin eso, una tabla precalculada abriria
    a la vez todas las cuentas que compartieran contrasena.
    """
    return _HASHER.hash(contrasena)


def contrasena_valida(hash_almacenado: str, contrasena: str) -> bool:
    """Comprueba una contrasena contra su hash.

    Devuelve `False` en lugar de lanzar, y eso incluye el caso de un hash
    **malformado**. Es deliberado: una fila corrupta en la base debe producir
    "estas credenciales no valen", no un `500`. La alternativa —propagar— haria
    que un dato invalido tumbara el endpoint de acceso, que es justo el que debe
    seguir en pie.

    Ninguna rama incluye la contrasena en un mensaje ni la registra.
    """
    try:
        return bool(_HASHER.verify(hash_almacenado, contrasena))
    except (Argon2Error, InvalidHashError, TypeError, ValueError):
        return False


def necesita_rehash(hash_almacenado: str) -> bool:
    """Indica si el hash se calculo con parametros distintos de los vigentes.

    Permite que, al iniciar sesion correctamente, un hash antiguo se sustituya
    por uno actual sin pedir nada al propietario. Un hash ilegible **no** se
    marca para rehash: no hay contrasena verificada con la que recalcularlo, y
    ese caso ya lo resuelve `contrasena_valida` devolviendo `False`.
    """
    try:
        return bool(_HASHER.check_needs_rehash(hash_almacenado))
    except (Argon2Error, InvalidHashError, TypeError, ValueError):
        return False


def verificacion_senuelo(contrasena: str) -> None:
    """Gasta el mismo trabajo criptografico que una verificacion real.

    Se invoca cuando el correo recibido **no** corresponde a ningun
    administrador (decision D-011-M). Sin ella, ese caso saldria sin ejecutar
    Argon2id y responderia de forma perceptiblemente mas rapida, lo que
    permitiria distinguir "este correo no existe" de "la contrasena es
    incorrecta" — es decir, enumerar cuentas midiendo el reloj.

    **No devuelve nada, y es intencionado**: su resultado no es utilizable como
    verificacion, asi que ningun llamante puede confundirla con una.

    Lo que se afirma es modesto y comprobable: **no queda ningun camino que
    evite el trabajo criptografico**. No se afirma resistencia criptografica al
    analisis temporal, que exigiria medirla.
    """
    contrasena_valida(_HASH_SENUELO, contrasena)
