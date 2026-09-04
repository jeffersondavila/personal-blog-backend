"""Capa de presentacion de la autenticacion administrativa.

Interfaz publica del modulo. Expone dos cosas y nada mas:

- `router`: los tres endpoints de autenticacion.
- `AdministradorRequerido` / `requiere_administrador`: la **proteccion
  reutilizable** —el `require_administrator` del alcance de `Task/011`— que
  `Task/012` aplica a todos sus endpoints administrativos.
- `exigir_origen_permitido` y `sin_cache`: la segunda capa de la defensa CSRF y
  la politica de cache que `Task/012` **reutiliza** en lugar de repetir.
- `ContextoRequerido` / `ContextoDeLaPeticion`: el `request_id` y la direccion
  del cliente con los que se correlaciona un evento de auditoria. `Task/012`
  usa **este** mecanismo; no crea un segundo identificador de peticion ni una
  segunda politica de confianza en proxies.

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
    ContextoDeLaPeticion,
    ContextoRequerido,
    exigir_origen_permitido,
    requiere_administrador,
    sin_cache,
)
from app.modules.authentication.presentation.router import router

__all__ = [
    "AdministradorRequerido",
    "ContextoDeLaPeticion",
    "ContextoRequerido",
    "exigir_origen_permitido",
    "requiere_administrador",
    "router",
    "sin_cache",
]
