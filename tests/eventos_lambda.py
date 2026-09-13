"""Harness de eventos de API Gateway HTTP API v2 (`Task/023`).

Vive aqui —y no dentro de un modulo de prueba— porque lo comparten el contrato
(`tests/contract/test_handler_lambda.py`) y la integracion
(`tests/integration/test_handler_lambda_sesion_administrativa.py`). Es el mismo
criterio que siguio `tests/almacenamiento_de_pruebas.py` en `Task/010`.

**No importa `app.main` ni `app.lambda_handler`.** Construir la aplicacion al
importar este modulo la construiria durante la collection, que es el defecto
`CERT-AUD-001`. Aqui solo se arman diccionarios.

Forma del evento
----------------

Los campos son los que documenta AWS para el *payload format* 2.0. El adaptador
lee de el `version`, `requestContext.http.{method,path,sourceIp}`,
`rawQueryString`, `headers`, `cookies`, `body` e `isBase64Encoded`.

`stage` lleva `$default` **solo porque el evento necesita un valor**: `Task/023`
no decide que *stage* tendra produccion. Esa decision, y el tratamiento del
*base path* que un *stage* nombrado exigiria, son de `Task/033`.
"""

from __future__ import annotations

import json
from typing import Any, Final

#: Direccion de origen que declara el evento. API Gateway la pone en
#: `requestContext.http.sourceIp`, y es la unica fuente de la IP bajo Lambda.
DIRECCION_DE_ORIGEN: Final[str] = "203.0.113.42"

#: Anfitrion del API. El adaptador lo usa para construir `scope["server"]`.
ANFITRION: Final[str] = "api.blog.invalid"


class ContextoLambda:
    """Contexto de invocacion minimo.

    El adaptador lo guarda en el *scope* como `aws.context` y no lo interpreta
    para los eventos de API Gateway, asi que basta con que exista y tenga la
    forma que entrega el runtime.
    """

    function_name = "personal-blog-backend"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:personal-blog-backend"
    aws_request_id = "id-de-invocacion-de-prueba"


def evento_http_api_v2(
    *,
    metodo: str = "GET",
    ruta: str = "/health",
    consulta: str = "",
    cabeceras: dict[str, str] | None = None,
    cookies: list[str] | None = None,
    cuerpo: str | None = None,
    direccion_de_origen: str = DIRECCION_DE_ORIGEN,
) -> dict[str, Any]:
    """Construye un evento de API Gateway HTTP API con *payload format* 2.0."""
    cabeceras_finales = {"host": ANFITRION, "user-agent": "agente-de-prueba"}
    cabeceras_finales.update(cabeceras or {})

    evento: dict[str, Any] = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": ruta,
        "rawQueryString": consulta,
        "headers": cabeceras_finales,
        "requestContext": {
            "accountId": "000000000000",
            "apiId": "api-de-prueba",
            "domainName": ANFITRION,
            "http": {
                "method": metodo,
                "path": ruta,
                "protocol": "HTTP/1.1",
                "sourceIp": direccion_de_origen,
                "userAgent": "agente-de-prueba",
            },
            "requestId": "id-de-la-peticion",
            "routeKey": "$default",
            "stage": "$default",
            "time": "13/Sep/2026:00:00:00 +0000",
            "timeEpoch": 1789171200000,
        },
        "isBase64Encoded": False,
    }
    if cookies is not None:
        evento["cookies"] = cookies
    if cuerpo is not None:
        evento["body"] = cuerpo
    return evento


def evento_con_json(*, metodo: str, ruta: str, datos: Any, **extra: Any) -> dict[str, Any]:
    """Evento con cuerpo JSON, como el que enviaria el panel administrativo."""
    cabeceras = {"content-type": "application/json"}
    cabeceras.update(extra.pop("cabeceras", {}) or {})
    return evento_http_api_v2(
        metodo=metodo,
        ruta=ruta,
        cuerpo=json.dumps(datos),
        cabeceras=cabeceras,
        **extra,
    )


def invocar(handler: Any, evento: dict[str, Any]) -> dict[str, Any]:
    """Invoca el handler como lo haria el runtime de Lambda."""
    respuesta: dict[str, Any] = handler(evento, ContextoLambda())
    return respuesta


def cuerpo_json(respuesta: dict[str, Any]) -> Any:
    return json.loads(respuesta["body"])


def cabeceras_de(respuesta: dict[str, Any]) -> dict[str, str]:
    """Cabeceras de la respuesta v2, normalizadas a minusculas.

    La clave puede faltar: el formato v2 omite los campos vacios.
    """
    return {clave.lower(): valor for clave, valor in (respuesta.get("headers") or {}).items()}


def cookies_de(respuesta: dict[str, Any]) -> list[str]:
    """Cookies de la respuesta v2. Ausentes cuando no hay ninguna."""
    cookies: list[str] = respuesta.get("cookies") or []
    return cookies


def par_de_cookie(cookie: str) -> str:
    """Reduce una `Set-Cookie` completa al `nombre=valor` que reenvia el cliente.

    Es lo que hace un navegador: los atributos —`Path`, `HttpOnly`, `Secure`,
    `SameSite`— gobiernan **cuando** se reenvia, no **que** se reenvia.
    """
    return cookie.split(";", 1)[0].strip()
