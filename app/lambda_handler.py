"""Adaptador de la aplicacion FastAPI a AWS Lambda (`Task/023`).

Es la **capa fina y removible** que exige el requisito T-04: envuelve la
instancia ASGI que ya construye `app/main.py` y la expone con la firma que el
runtime de Lambda invoca. El codigo de negocio no cambia, no se entera y no
importa nada de aqui.

Quitar Lambda del proyecto es borrar este archivo y una linea de
`pyproject.toml`. `tests/unit/test_guarda_del_adaptador_lambda.py` mantiene esa
afirmacion viva: recorre el arbol sintactico de `app/` y falla si `mangum`
aparece en cualquier otro modulo.

Que hace el adaptador y que no
------------------------------

Traduce el evento de **API Gateway HTTP API v2** (*payload format* 2.0) al
*scope* ASGI, y la respuesta ASGI de vuelta al formato de respuesta v2. Lo que
importa para este backend:

- `requestContext.http.sourceIp` acaba en `scope["client"]`, que es de donde
  sale `request.client.host`. Es la **unica** fuente de la direccion del cliente
  bajo Lambda, y de ella dependen la particion del limite de tasa y el
  `ip_address` de cada evento de auditoria.
- `Set-Cookie` sale por el array `cookies` de la respuesta v2, separado de
  `headers`. Colapsarlo romperia la sesion administrativa **sin ningun error
  visible**; por eso hay una integracion real que lo vigila.
- `rawQueryString` llega a `scope["query_string"]` sin reinterpretarse.

Lo que **no** hace: decidir nada sobre API Gateway. El *stage*, el dominio y el
tratamiento del *base path* son de `Task/033`. Por eso aqui no se configura
`api_gateway_base_path`: anadirlo hoy seria fijar por la puerta de atras una
decision que no es de esta tarea. Si produccion acabara usando un *stage*
nombrado, `rawPath` traeria el prefijo del *stage* y **esa** seria la tarea que
lo trate.

Por que `lifespan="off"`
------------------------

Verificado sobre la rueda fijada de `mangum==0.22.0`:

1. `LifespanCycle` se instancia **dentro** de `Mangum.__call__`, de modo que el
   ciclo de arranque y apagado correria **una vez por invocacion**, no una vez
   por contenedor.
2. El modo `"auto"` solo degrada a "no soportado" cuando la aplicacion envia un
   mensaje antes de recibir el evento de arranque. Starlette **si** implementa
   el protocolo, asi que `"auto"` no degradaria: ejecutaria el ciclo entero en
   cada peticion.

Como `create_app()` no declara ningun manejador de ciclo de vida, ese ciclo no
haria ningun trabajo util. Y `"auto"` tampoco seria la opcion prudente de cara
al futuro: un arranque que calentara un *pool* se ejecutaria —y se destruiria—
en **cada** peticion, que es peor que no ejecutarlo.

La decision se apoya en una premisa que podria caducar, asi que la premisa esta
protegida en tres capas por `tests/unit/test_guarda_del_adaptador_lambda.py`.
El dia que la aplicacion adquiera ciclo de vida explicito, esa prueba se pone
roja y obliga a revisar esta eleccion en lugar de heredarla.

Ejecucion local
---------------

**No cambia.** `uvicorn app.main:app` sigue siendo el punto de entrada en
desarrollo y en el `CMD` del Dockerfile. Este modulo solo se usa cuando el
artefacto de `Task/024` se despliega como funcion Lambda.
"""

from __future__ import annotations

import asyncio

from mangum import Mangum
from mangum.types import ASGI

from app.main import app

# El bucle de eventos del proceso se establece **aqui**, una sola vez, al
# importar el modulo. No es un detalle de conveniencia.
#
# `Mangum.__init__` llama a `asyncio.get_event_loop()` y captura `RuntimeError`
# para crear uno si no existe. Esa es la forma correcta en Python 3.14, donde la
# llamada **lanza**. En Python 3.12 —la version que fija este proyecto— la misma
# llamada **no lanza**: emite `DeprecationWarning: There is no current event
# loop` y devuelve un bucle nuevo. El `except` no llega a ejecutarse y el aviso
# sale. Con la politica `pytest -W error` del proyecto, eso es un error.
#
# La respuesta **no** es silenciar el aviso: el proyecto ya rechazo esa via con
# `anyio`/`starlette` en `Task/020`. Tampoco hay una version corregida aguas
# arriba que adoptar. Lo que se hace aqui es no tomar el camino deprecado:
# establecido el bucle, `get_event_loop()` lo devuelve sin avisar.
#
# Un unico bucle por proceso es ademas el modelo correcto bajo Lambda: vive lo
# que viva el entorno de ejecucion, igual que lo haria el que crea Mangum. Si ya
# hubiera uno **en marcha** —importar el modulo dentro de un contexto async— no
# se toca nada: `get_event_loop()` devuelve el que corre, tambien sin avisar.
#
# Regresion permanente: `tests/unit/test_arranque_del_handler_lambda.py`.
try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

#: Nombre del *handler* que configurara la funcion Lambda: `app.lambda_handler.handler`.
#: Lo consumen `Task/024` —al empaquetar— y `Task/025` —al desplegar—.
NOMBRE_DEL_HANDLER = "app.lambda_handler.handler"


def crear_handler(aplicacion: ASGI) -> Mangum:
    """Envuelve una aplicacion ASGI con el adaptador de Lambda.

    Recibir la aplicacion permite a las pruebas montar el adaptador sobre una
    instancia construida con su propia configuracion, igual que `create_app()`
    admite `settings`. El comportamiento productivo es el `handler` de abajo,
    identico al que habria sin esta funcion.

    El tipo del parametro es el del propio adaptador y no el `ASGIApp` de
    Starlette: no son intercambiables bajo `mypy --strict`. `ASGIApp` declara que
    `__call__` devuelve `Awaitable[None]`, que es mas ancho que el
    `Coroutine[Any, Any, None]` que exige el adaptador, asi que el primero no es
    asignable al segundo. Declarar aqui el tipo real evita un `type: ignore` que
    solo habria tapado la diferencia.
    """
    return Mangum(aplicacion, lifespan="off")


#: Punto de entrada de la funcion Lambda. Envuelve **la misma** instancia que
#: ejecuta uvicorn en local: no hay una segunda aplicacion.
handler = crear_handler(app)
