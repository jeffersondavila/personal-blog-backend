"""Constructores de administradores para las pruebas de `Task/011`.

Mismo criterio que `datos.py`: funciones normales, no fixtures. El harness de
integracion exige que toda fixture derive del resolutor verificado
(`CERT-AUD-002`), y estas funciones no resuelven ningun destino — reciben la
sesion que la prueba ya obtuvo por el camino comprobado.

**Todo lo que se crea aqui es ficticio.** El correo es de un dominio reservado
para ejemplos (RFC 2606) y la contrasena es una cadena de prueba. `Task/011` no
crea ningun administrador real: el del entorno local es de `Task/022` y el de
produccion, de `Task/036`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditEvent
from app.modules.authentication.infrastructure.models import (
    Administrator,
    AdministratorSession,
    LoginRateLimit,
)
from app.shared.security import hash_de_contrasena

#: Credenciales ficticias. No abren nada real: la base de pruebas se recrea.
CORREO = "administrador@example.invalid"
CONTRASENA = "contrasena-de-prueba-suficientemente-larga"
NOMBRE_VISIBLE = "Administrador de prueba"


def administrador(
    sesion: Session,
    *,
    correo: str = CORREO,
    contrasena: str = CONTRASENA,
    nombre_visible: str = NOMBRE_VISIBLE,
    intentos_fallidos: int = 0,
    bloqueado_hasta: datetime | None = None,
    ultimo_acceso: datetime | None = None,
    password_hash: str | None = None,
) -> Administrator:
    """Crea el administrador singleton de la prueba y lo deja disponible.

    `password_hash` permite fijar un hash concreto —por ejemplo, uno calculado
    con parametros antiguos— sin volver a pasar por Argon2id.
    """
    fila = Administrator(
        email=correo,
        password_hash=password_hash or hash_de_contrasena(contrasena),
        display_name=nombre_visible,
        failed_login_attempts=intentos_fallidos,
        locked_until=bloqueado_hasta,
        last_login_at=ultimo_acceso,
    )
    sesion.add(fila)
    sesion.flush()
    return fila


def limpiar_autenticacion(sesion: Session) -> None:
    """Borra todo lo que escribe la autenticacion, **en orden de dependencias**.

    Lo necesitan las pruebas que confirman de verdad —las que ejercitan la ruta
    real de sesion o dos conexiones simultaneas—, porque lo que confirman
    sobrevive al final de la prueba y `administrators.is_singleton` es unico: una
    fila olvidada impide que **cualquier** prueba posterior cree su administrador.

    El orden no es cosmetico. `audit_events.actor_id` es una clave foranea con
    `ON DELETE RESTRICT` —para que el historial no se pierda con quien lo
    genero—, asi que borrar el administrador antes que sus eventos **falla**, y
    el fallo dentro de un `finally` deja exactamente la fila que se pretendia
    limpiar. Fue el defecto real que dejo la primera version de estas pruebas.

    Se usa DML masivo a proposito: las guardas de inmutabilidad de `AuditEvent`
    actuan sobre la *unit of work* del ORM y no sobre esta ruta, tal como
    `Task/008` documento al describir su alcance exacto. Es la unica forma de
    limpiar un historial de pruebas sin relajar ninguna garantia del codigo real.
    """
    for modelo in (AuditEvent, AdministratorSession, LoginRateLimit, Administrator):
        sesion.execute(delete(modelo))
