"""Politica de parametros de consulta desconocidos (decision D-009-C).

api-contracts.md seccion 6 dejaba la eleccion abierta: *"los filtros
desconocidos se ignoran o se rechazan de forma consistente; la decision se fija
en `Task/009`"*. **Se rechazan, con el `422` del contrato comun.**

Por que rechazar y no ignorar
-----------------------------

1. **Coherencia con el proyecto.** `Settings` usa `extra="forbid"` y pytest se
   ejecuta con `--strict-markers` y `--strict-config`: ante una clave que no se
   reconoce, este proyecto falla en voz alta en lugar de seguir en silencio.
2. **Una errata deja de ser invisible.** `?tagg=docker` ignorado devuelve el
   listado **entero** con aspecto de haber filtrado. Rechazado, el cliente se
   entera en la primera prueba.
3. **OpenAPI pasa a ser el contrato**, no una descripcion aproximada de el.
4. **`status` queda cerrado por construccion.** No es un parametro publico, asi
   que `?status=draft` no se ignora: se rechaza. No existe ninguna forma de
   pedir contenido no publicado.

**Coste aceptado y registrado:** un parametro de analitica anadido a la URL de
la API produciria `422`. El frontend no debe reenviarlos.

Por que la lista de admitidos se deriva de la ruta
--------------------------------------------------

Escribir el conjunto de nombres junto a cada operacion lo condenaria a
desincronizarse: quien anada un filtro nuevo y olvide registrarlo aqui lo veria
rechazado sin motivo aparente. El conjunto se **lee de la propia operacion**, de
modo que declarar el parametro es lo unico que hace falta para admitirlo.

Eso apoya la politica en la estructura interna de FastAPI, y por eso existe una
guarda: `test_los_parametros_declarados_son_admitidos` se pone **roja** si la
derivacion dejara de funcionar. Sin ella, una derivacion rota devolveria un
conjunto vacio y la API rechazaria **todo** mientras las pruebas de rechazo
seguirian verdes.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.dependencies.models import Dependant
from fastapi.exceptions import RequestValidationError


def _nombres_admitidos(dependant: Dependant) -> set[str]:
    """Nombres de parametro de consulta que declara una operacion.

    Recorre tambien las subdependencias: los parametros de paginacion no se
    declaran en la firma del endpoint, sino en la dependencia compartida que los
    resuelve.
    """
    nombres = {campo.alias for campo in dependant.query_params}
    for subdependencia in dependant.dependencies:
        nombres |= _nombres_admitidos(subdependencia)
    return nombres


def rechazar_parametros_desconocidos(request: Request) -> None:
    """Rechaza la peticion si trae parametros que la operacion no declara.

    Se lanza `RequestValidationError` y no una excepcion propia para reutilizar
    el manejador que ya existe: el cuerpo resultante es exactamente la envoltura
    de error del proyecto, con `code = "validation_error"` y los campos
    afectados en `details` (api-contracts.md seccion 7). Inventar un segundo
    formato de error esta prohibido.
    """
    ruta = request.scope.get("route")
    dependant = getattr(ruta, "dependant", None)
    if dependant is None:  # pragma: no cover - Starlette siempre resuelve la ruta
        raise AssertionError(
            "no se pudo determinar la operacion de la peticion, asi que no se puede "
            "saber que parametros admite. Rechazar todo o admitir todo serian ambos "
            "incorrectos: se detiene para que el defecto sea visible."
        )

    admitidos = _nombres_admitidos(dependant)
    desconocidos = sorted(set(request.query_params) - admitidos)
    if not desconocidos:
        return

    raise RequestValidationError(
        [
            {
                "type": "unexpected_query_parameter",
                "loc": ("query", nombre),
                "msg": "Parametro de consulta no admitido por este endpoint.",
                "input": request.query_params[nombre],
            }
            for nombre in desconocidos
        ]
    )
