"""Capa de presentacion de la autenticacion administrativa.

Interfaz publica del modulo. Expone dos cosas y nada mas:

- `router`: los tres endpoints de autenticacion.
- `AdministradorRequerido` / `requiere_administrador`: la **proteccion
  reutilizable** —el `require_administrator` del alcance de `Task/011`— que
  `Task/012` aplicara a todos sus endpoints administrativos.

Que el resto del backend dependa de este `__init__` y no de los modulos de
dentro es lo que mantiene el acoplamiento entre modulos en una **interfaz
publica**, que es la mitigacion que ADR-004 exige para el riesgo que el
monolito modular acepta.

Por que la dependencia vive aqui y no en `app/shared/security`
--------------------------------------------------------------

software-architecture.md seccion 3.4 asigna las *dependencias de autorizacion*
a `shared/security`. Resolverlas exige consultar **sesiones y
administradores**, que son de este modulo, asi que colocarlas en `shared`
obligaria a que `shared` importara un modulo de negocio — justo lo que la regla
de dependencias prohibe. `shared/security` conserva las primitivas
transversales (hash de contrasenas, direccion del cliente); la autorizacion
vive con quien es dueno de los datos que consulta. Decision **D-011-O**.
"""

from app.modules.authentication.presentation.dependencias import (
    AdministradorRequerido,
    requiere_administrador,
)
from app.modules.authentication.presentation.router import router

__all__ = [
    "AdministradorRequerido",
    "requiere_administrador",
    "router",
]
