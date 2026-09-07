"""Middleware de correlacion y evento de peticion (`Task/017`, O-01 y O-02).

Hace tres cosas, y solo tres
----------------------------

1. **Resuelve el correlation ID** de la peticion segun el contrato de
   `contexto.py`, y lo deja disponible en dos sitios: el `ContextVar` —para que
   el `logging.Filter` lo inyecte en todo registro— y `request.state.request_id`
   —de donde ya lo leen `request_id_de()` y `contexto_de_la_peticion`—.
2. **Devuelve la cabecera** en la respuesta, sea cual sea su estado.
3. **Emite un unico evento por peticion** con los campos estructurados.

Por que sustituye al access log de Uvicorn
-------------------------------------------

Medido en el contenedor durante la definicion: `uvicorn.access` emite la linea
`"172.22.0.4:35932 - \\"GET /health HTTP/1.1\\" 200"`, con metodo, ruta, estado y
direccion **dentro de una cadena**. Es JSON valido pero no parseable por campos,
no lleva `request_id` —Uvicorn no lo conoce— y no lleva duracion.

Este evento la sustituye. `uvicorn.error` **no se toca**: sigue emitiendo
arranque, apagado y errores del servidor.

Por que `request.state` **y** `ContextVar`
------------------------------------------

No es duplicar el dato. Son dos alcances distintos:

- `request.state` es de quien tiene el objeto `Request` a mano: los manejadores
  de error y la dependencia de contexto de auditoria. Ya existia.
- El `ContextVar` es de quien **no** lo tiene: cualquier logger de cualquier
  capa. Es lo que hace innecesario pasar el identificador por parametro.

El middleware siembra los dos con **el mismo valor**, que es justo lo que el
docstring de `request_id_de()` anticipaba: *"cambiara el origen del valor sin
tocar a quien lo consume"*.

Por que `perf_counter` y no el reloj civil
-------------------------------------------

`time.perf_counter` es monotonico. Con `datetime.now()`, un ajuste de reloj o un
cambio de horario producirian duraciones negativas o disparatadas justo cuando
mas falta hace el diagnostico.
"""

from __future__ import annotations

import logging
import time
from typing import Final

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.logging.contexto import (
    NOMBRE_DE_LA_CABECERA_DE_CORRELACION,
    establecer_request_id,
    resolver_request_id,
    restablecer_request_id,
)

_logger = logging.getLogger("app.peticion")

#: Rutas cuya peticion satisfactoria se registra a `DEBUG`.
#:
#: Medido antes de implementar: el 90,8 % de las lineas del log del contenedor
#: eran sondas correctas a `/health`, unas 11 500 al dia entre el `HEALTHCHECK`
#: de Docker (cada 30 s) y el `healthCheck` de Traefik (cada 10 s). A `INFO`
#: ahogarian cualquier diagnostico en Portainer.
#:
#: **Solo baja de nivel el exito.** Una sonda que falla sube a `WARNING` o
#: `ERROR` como cualquier otra peticion: un fallo de sonda nunca se silencia.
RUTAS_DE_SONDA: Final[frozenset[str]] = frozenset({"/health", "/ready"})

_MENSAJE_DEL_EVENTO: Final[str] = "Peticion completada"

#: El nombre de la cabecera en minusculas y en bytes, que es como viaja en ASGI.
_CABECERA_EN_BYTES: Final[bytes] = NOMBRE_DE_LA_CABECERA_DE_CORRELACION.lower().encode("latin-1")


def _nivel_para(status_code: int, ruta: str) -> int:
    """Nivel del evento segun el resultado, no segun la familia del codigo.

    No todo `4xx` es un error: un `404` en una API publica es funcionamiento
    correcto —el recurso no existe o no es visible— y registrarlo como `ERROR`
    convertiria el nivel en ruido. Lo que interesa vigilar es el `4xx` que habla
    de **seguridad** (`401`, `403`) o de **abuso** (`429`).
    """
    if status_code == 503 and ruta == "/ready":
        return logging.WARNING
    if status_code >= 500:
        return logging.ERROR
    if status_code in (401, 403, 429):
        return logging.WARNING
    if status_code < 400 and ruta in RUTAS_DE_SONDA:
        return logging.DEBUG
    return logging.INFO


class CorrelacionDePeticiones:
    """Middleware ASGI puro: correlacion, cabecera de respuesta y evento.

    Se implementa sobre la interfaz ASGI y no con `BaseHTTPMiddleware` a
    proposito. `BaseHTTPMiddleware` ejecuta la aplicacion en una tarea aparte, y
    el `ContextVar` sembrado alli **no es visible** desde los manejadores de
    error de la aplicacion: el identificador de la respuesta y el de los logs
    podrian divergir, que es exactamente lo que esta tarea existe para impedir.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        peticion = Request(scope)
        entrantes = peticion.headers.getlist(NOMBRE_DE_LA_CABECERA_DE_CORRELACION)
        request_id, hubo_descarte = resolver_request_id(entrantes)

        # Los dos alcances, con el mismo valor. `scope["state"]` es lo que
        # respalda a `request.state`, del que ya dependen `request_id_de()` y la
        # dependencia de contexto de auditoria.
        scope.setdefault("state", {})["request_id"] = request_id
        token = establecer_request_id(request_id)

        comenzado_en = time.perf_counter()
        estado_final = 500

        async def _enviar(mensaje: Message) -> None:
            nonlocal estado_final
            if mensaje["type"] == "http.response.start":
                estado_final = mensaje["status"]
                cabeceras = list(mensaje.get("headers", []))
                # Las respuestas de error ya la traen: `build_error_response` la
                # pone porque un `500` no controlado lo resuelve
                # `ServerErrorMiddleware`, montado por encima de este middleware.
                # Anadirla otra vez emitiria la cabecera duplicada, que es justo
                # la ambiguedad que el contrato de entrada prohibe.
                if not any(nombre.lower() == _CABECERA_EN_BYTES for nombre, _ in cabeceras):
                    cabeceras.append(
                        (
                            NOMBRE_DE_LA_CABECERA_DE_CORRELACION.encode("latin-1"),
                            request_id.encode("latin-1"),
                        )
                    )
                mensaje = {**mensaje, "headers": cabeceras}
            await send(mensaje)

        try:
            await self._app(scope, receive, _enviar)
        except Exception as error:
            # Uvicorn registra la excepcion despues del reset. Transportar el
            # ID validado en la propia excepcion conserva ese ultimo enlace
            # sin dejar vivo el ContextVar ni modificar mensaje o causa.
            error.__dict__["_blog_request_id"] = request_id
            raise
        finally:
            # En el `finally` a proposito: una excepcion que escape hasta aqui
            # tambien deja su evento, y el contexto se restaura pase lo que pase.
            # Sin el `reset`, el identificador sobreviviria a la peticion y
            # apareceria en el log de la siguiente atendida por el mismo hilo.
            duracion_ms = round((time.perf_counter() - comenzado_en) * 1000, 1)
            ruta = scope.get("path", "")
            contexto: dict[str, object] = {
                "request_id": request_id,
                "method": scope.get("method", ""),
                # La ruta **sin** query string: medido en el baseline, la query
                # entraba tal cual en el log de acceso, y ahi puede viajar un
                # dato sensible (requisito O-08).
                "path": ruta,
                "status_code": estado_final,
                "duration_ms": duracion_ms,
            }
            if hubo_descarte:
                # Solo el booleano. El valor rechazado **nunca** se registra:
                # escribirlo seria la inyeccion de log que la validacion evita.
                contexto["incoming_request_id_discarded"] = True

            _logger.log(_nivel_para(estado_final, ruta), _MENSAJE_DEL_EVENTO, extra=contexto)
            restablecer_request_id(token)
