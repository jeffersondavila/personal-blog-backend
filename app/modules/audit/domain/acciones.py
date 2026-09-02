"""Catalogo de acciones auditables (`Task/011`).

`Task/008` dejo `AuditEvent.action` como cadena libre **a proposito**: congelarla
en un `CHECK` habria obligado a migrar el esquema cada vez que se decidiera una
accion nueva, y en aquel momento no habia ninguna decidida. El catalogo se cierra
"en `Task/011` y `Task/012`", y esta es su primera mitad.

Por que una enumeracion y no cadenas sueltas
--------------------------------------------

La restriccion no puede vivir en la base sin pagar una migracion por accion, pero
si puede vivir aqui: una errata en un literal escrito a mano —
`"authentication.login_suceeded"`— produciria un evento que **ninguna consulta
posterior encontraria**, y el defecto solo se veria el dia que alguien fuera a
leer el historial. Con la enumeracion, esa errata no compila.

Por que cuatro y no veinte
--------------------------

Cada entrada tiene un productor real en el codigo de esta tarea. Un catalogo con
acciones que nadie emite es documentacion que aparenta un historial inexistente.
`Task/012` anadira las suyas cuando tenga operaciones que registrar.

Lo que **no** se audita, y por que
----------------------------------

Un rechazo por **limite de tasa** no genera evento. Es un hecho operativo del
endpoint, no una accion administrativa: cualquiera desde fuera puede provocarlo a
voluntad, asi que auditarlo permitiria llenar el historial de ruido justo antes
de hacer algo que si conviene esconder. El contador deja constancia en su propia
tabla y la peticion queda en el log estructurado.
"""

from __future__ import annotations

from enum import StrEnum


class AccionAuditada(StrEnum):
    """Acciones de autenticacion que dejan rastro en el historial.

    El prefijo `authentication.` no es decorativo: `Task/012` anadira acciones de
    contenido y el prefijo mantiene legible de un vistazo de que modulo viene cada
    entrada del historial.
    """

    #: El administrador inicio sesion correctamente.
    ACCESO_CORRECTO = "authentication.login_succeeded"
    #: Un intento de acceso no prospero. `actor_id` es nulo si el correo recibido
    #: no correspondia a ningun administrador.
    ACCESO_FALLIDO = "authentication.login_failed"
    #: El administrador cerro sesion.
    CIERRE_DE_SESION = "authentication.logout"
    #: Un intento fallido alcanzo el umbral y activo el bloqueo temporal. Se
    #: registra la **transicion**, no el estado: los intentos posteriores durante
    #: el mismo bloqueo no vuelven a emitirlo.
    CUENTA_BLOQUEADA = "authentication.account_locked"


#: Tipo de entidad al que apuntan todos los eventos de autenticacion. Es el
#: administrador afectado, incluso cuando no se sabe quien es.
ENTIDAD_ADMINISTRADOR = "administrator"
