"""Fuente del instante actual (`Task/011`, mudada a `shared` en `Task/012`).

Por que esta aqui
-----------------

Un reloj no conoce ninguna regla de negocio: es una capacidad tecnica
transversal, que es exactamente lo que `app/shared` alberga
(software-architecture.md seccion 3.4). `Task/011` lo dejo dentro de
`authentication` porque era su unico consumidor; `Task/012` lo necesita ademas
en los cuatro tipos de contenido, para fijar `published_at`.

Que ese instante lo ponga el **caso de uso** y no la base de datos no es una
eleccion de esta tarea: `data-model.md` D-H lo dice al distinguir las dos clases
de marca temporal —*"`published_at`, en cambio, es un momento **de negocio** que
fija el caso de uso con su reloj inyectado"*—. `created_at` y `updated_at` los
pone `now()` de PostgreSQL; `published_at`, este reloj.

`authentication` reexporta las dos piezas, asi que sus firmas no cambian.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Reloj(Protocol):
    """Fuente del instante actual.

    Existe para que la expiracion, el bloqueo, la ventana del limite de tasa y
    la fecha de publicacion se puedan probar con instantes fijos en lugar de con
    esperas reales. Es una abstraccion minima —un metodo— y no un framework de
    tiempo.
    """

    def ahora(self) -> datetime:
        """Instante actual, **siempre con zona horaria UTC**."""
        ...


class RelojDelSistema:
    """Instante actual del proceso, en UTC.

    Siempre **UTC con zona horaria**. `datetime.now()` sin zona produce un
    instante que no significa lo mismo en Windows —donde se desarrolla—, en el
    contenedor Linux del entorno local y en Lambda, y comparar uno de esos con
    un instante de PostgreSQL es un `TypeError` en el mejor caso y un desfase
    silencioso en el peor.
    """

    def ahora(self) -> datetime:
        return datetime.now(UTC)
