"""Jerarquia de errores de la aplicacion, **sin framework**.

Este paquete reexporta unicamente las excepciones. La traduccion a HTTP sigue
viviendo en un unico punto —`app.shared.errors.handlers`
(software-architecture.md seccion 3.6)— pero se importa desde ese modulo, no
desde aqui.

Por que la reexportacion de los manejadores se retiro (`Task/008`)
------------------------------------------------------------------

Importar un submodulo ejecuta el `__init__` de su paquete. Mientras este archivo
importaba `handlers`, un modulo de dominio que escribiera

    from app.shared.errors.exceptions import ConflictError

cargaba **FastAPI y Starlette** sin nombrarlos, porque el `__init__` intermedio
los arrastraba. Eso rompe la regla de dependencias de ADR-004: el dominio es
Python plano y no conoce el framework.

No es un detalle de estilo: era el unico camino por el que el framework entraba
en el dominio, y no se veia en ningun import. La regresion vive en
`tests/unit/test_independencia_del_dominio.py`, que importa cada paquete
`domain` en un interprete limpio y comprueba que no aparece nada prohibido en
`sys.modules`.
"""

from app.shared.errors.exceptions import (
    ApplicationError,
    ConflictError,
    DependencyUnavailableError,
    ResourceNotFoundError,
    ValidationFailedError,
)

__all__ = [
    "ApplicationError",
    "ConflictError",
    "DependencyUnavailableError",
    "ResourceNotFoundError",
    "ValidationFailedError",
]
