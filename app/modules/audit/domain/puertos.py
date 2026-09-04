"""Puertos del modulo de auditoria.

Por que este puerto se mudo aqui en `Task/012`
-----------------------------------------------

`Task/011` declaro `RegistroDeAuditoria` dentro de
`app/modules/authentication/domain/puertos.py`, y era razonable: el inicio y el
cierre de sesion eran sus **unicos** consumidores.

`Task/012` cambia ese hecho. Escriben en el historial los cuatro tipos de
contenido, el perfil, las etiquetas y los medios. Que todos ellos tuvieran que
importar el modulo de **autenticacion** para escribir un evento seria una
dependencia que no describe ninguna relacion real: no hay nada de autenticacion
en publicar un articulo.

El puerto vive donde vive su dueno. software-architecture.md seccion 3.3 asigna
al modulo `audit` el *"registro inmutable de acciones administrativas"*, y su
implementacion —`RegistroSqlDeAuditoria`— ya vivia aqui. `authentication` lo
**reexporta**, asi que la mudanza no cambia ninguna de sus firmas ni su
comportamiento: es un refactor, no un cambio de contrato.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ContextoDeAuditoria(Protocol):
    """Datos de correlacion que acompanan a cada evento.

    Es un protocolo y no una clase concreta para que la capa de aplicacion no
    tenga que importar nada de presentacion: lo que se le pasa es un objeto con
    estos dos atributos, y de donde salen no es asunto suyo.

    `Task/012` reutiliza el **mismo** objeto que construye `Task/011`
    (`ContextoDeLaPeticion`): no hay un segundo mecanismo de correlacion ni una
    segunda politica de direccion del cliente.
    """

    origen: str
    request_id: str


class RegistroDeAuditoria(Protocol):
    """Escritura del historial administrativo.

    Solo **crea**: la auditoria no se modifica ni se borra, y las guardas que lo
    garantizan viven en el modelo desde `Task/008`.
    """

    def registrar(
        self,
        accion: str,
        *,
        entidad: str,
        actor_id: uuid.UUID | None,
        entidad_id: uuid.UUID | None,
        request_id: str | None,
        ip: str | None,
        metadatos: dict[str, Any] | None = None,
    ) -> None:
        """Anade un evento al historial.

        `entidad` es obligatorio y **no tiene valor por defecto**. Hasta
        `Task/012` el registro escribia siempre `administrator`, porque era el
        unico tipo que producia eventos; ahora hay siete. Un valor por defecto
        etiquetaria en silencio como administrador el evento de quien se
        olvidara de pasarlo, y ese defecto solo se veria al leer el historial.

        `actor_id` admite nulo porque hay eventos sin actor conocido: un intento
        de acceso contra un correo que no existe tambien se audita.
        """
        ...
