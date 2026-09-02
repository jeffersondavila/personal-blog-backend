"""Esquemas HTTP de la autenticacion administrativa (`Task/011`).

Los esquemas de entrada y salida son **distintos de los modelos ORM** (regla 9 de
software-architecture.md seccion 3.5). Aqui esa separacion no es estilistica: es
lo que garantiza que `password_hash`, `failed_login_attempts` y `locked_until`
**no tengan ninguna ruta** hacia una respuesta.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.authentication.domain.puertos import AdministradorAutenticado

#: Longitud maxima de una direccion de correo (RFC 5321).
LONGITUD_MAXIMA_DE_CORREO = 254

#: Tope de la contrasena recibida. Argon2id no tiene el limite de 72 bytes de
#: bcrypt, asi que el tope no es del algoritmo: acota el tamano de lo que se
#: acepta procesar en un endpoint publico.
LONGITUD_MAXIMA_DE_CONTRASENA = 1024


class CredencialesDeAcceso(BaseModel):
    """Cuerpo de `POST /admin/auth/login`.

    `password` es `SecretStr` a proposito: su `repr` es una mascara, asi que un
    volcado accidental del modelo —una traza, un `logger.debug(cuerpo)`— no
    arrastra la contrasena (requisito S-08).

    `extra="forbid"` mantiene la postura estricta que `Task/009` fijo para toda
    la API: una clave desconocida es una errata del cliente, y aceptarla en
    silencio es como un `remember_me` que nadie implementa acaba pareciendo que
    funciona.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(
        min_length=3,
        max_length=LONGITUD_MAXIMA_DE_CORREO,
        description="Correo del administrador. Es el identificador de acceso.",
    )
    password: SecretStr = Field(
        min_length=1,
        max_length=LONGITUD_MAXIMA_DE_CONTRASENA,
        description="Contrasena en claro. Nunca se almacena ni se registra.",
    )


class AdministradorPublico(BaseModel):
    """Identidad del administrador autenticado.

    Son los **unicos** tres campos del contrato. Anadir uno aqui es anadirlo a
    `v1`, del que ya no podria retirarse sin `/api/v2` (api-contracts.md seccion
    10); y ninguno de los que faltan —hash, contador de fallos, bloqueo— tiene
    nada que hacer en un cliente.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str

    @classmethod
    def de_identidad(cls, administrador: AdministradorAutenticado) -> AdministradorPublico:
        return cls(
            id=administrador.id,
            email=administrador.email,
            display_name=administrador.display_name,
        )
