"""Contrato del adaptador Lambda ↔ API Gateway HTTP API v2 (`Task/023`).

Que se prueba aqui
------------------

Que un evento de **API Gateway HTTP API, payload format 2.0** se traduce al
*scope* ASGI que la aplicacion actual ya sabe atender, y que la respuesta ASGI
se traduce de vuelta al formato de respuesta v2. Es la frontera de transporte:
la semantica del API —que un borrador no salga, que el filtro recorra las
asociaciones reales— sigue viviendo en `tests/integration/`.

Por eso estas pruebas **no necesitan base de datos**: usan `aplicacion_publica`,
que neutraliza la sesion con la guarda que estalla al primer uso. Una prueba de
este archivo que alcanzara PostgreSQL tendria un defecto y se pondria roja
diciendolo.

Por que hay dos niveles de prueba
---------------------------------

1. **Contra la aplicacion real** (`handler_de_la_aplicacion`): codigos de
   estado, cuerpo, cabeceras de seguridad, correlacion y modelo de error. Es lo
   que de verdad viajara a produccion.
2. **Contra una aplicacion ASGI diminuta** (`handler_de_sonda`): la traduccion
   pura de cookies y de *scope*. Aislarla permite fijar el contrato **exacto**
   —que `Set-Cookie` sale por `cookies[]` y **no** por `headers`— sin montar un
   flujo de negocio para observarlo.

El segundo nivel no sustituye al primero en lo que importa de verdad: que la
**sesion administrativa real** sobrevive al adaptador se demuestra contra
PostgreSQL en
`tests/integration/test_handler_lambda_sesion_administrativa.py` (caso L-18).

Por que ningun import de `app.main` vive en la cabecera
-------------------------------------------------------

`app/main.py` construye la instancia ASGI al importarse, y `app/lambda_handler.py`
la importa. Un import a nivel de modulo aqui la construiria **durante la
collection**, con el entorno que hubiera en ese momento, que es exactamente el
defecto `CERT-AUD-001` que `tests/test_hermeticidad.py` impide. Los imports
viven dentro de las fixtures, igual que `create_app` en el resto del harness.
"""

from __future__ import annotations

import os
from typing import Any, Final

import pytest
from fastapi import FastAPI
from starlette.types import Receive, Scope, Send

from tests.eventos_lambda import (
    DIRECCION_DE_ORIGEN,
    cabeceras_de,
    cookies_de,
    cuerpo_json,
    evento_http_api_v2,
    invocar,
)

RUTA_DE_VIVACIDAD: Final[str] = "/health"
RUTA_DE_ARTICULOS: Final[str] = "/api/v1/posts"
RUTA_INEXISTENTE: Final[str] = "/esta-ruta-no-existe"

#: Identificador entrante valido segun el alfabeto cerrado de `Task/017`:
#: `[A-Za-z0-9_-]{8,64}`.
CORRELACION_ENTRANTE: Final[str] = "peticion-de-prueba-0001"

#: Cabeceras de seguridad que `Task/018` exige en toda respuesta. Si el
#: adaptador perdiera cualquiera de ellas seria una regresion de seguridad
#: silenciosa: la respuesta seguiria siendo `200`.
CABECERAS_DE_SEGURIDAD: Final[tuple[str, ...]] = (
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
    "content-security-policy",
)


@pytest.fixture
def handler_de_la_aplicacion(aplicacion_publica: FastAPI) -> Any:
    """Handler Lambda sobre la aplicacion completa del proyecto."""
    from app.lambda_handler import crear_handler

    return crear_handler(aplicacion_publica)


@pytest.fixture
def sonda_asgi() -> dict[str, Any]:
    """Registro donde la aplicacion de sonda deja el *scope* que recibio."""
    return {}


@pytest.fixture
def handler_de_sonda(sonda_asgi: dict[str, Any]) -> Any:
    """Handler sobre una aplicacion ASGI diminuta que responde dos cookies.

    Sirve para fijar la traduccion pura —*scope* de entrada y `Set-Cookie` de
    salida— sin depender de ningun comportamiento de negocio.
    """
    from app.lambda_handler import crear_handler

    async def aplicacion_de_sonda(scope: Scope, receive: Receive, send: Send) -> None:
        sonda_asgi.update(scope)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"set-cookie", b"primera=1; Path=/; HttpOnly"),
                    (b"set-cookie", b"segunda=2; Path=/; HttpOnly"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b'{"ok":true}'})

    return crear_handler(aplicacion_de_sonda)


# --- L-01 -------------------------------------------------------------------
def test_el_modulo_del_handler_expone_un_callable() -> None:
    """El artefacto que `Task/024` empaqueta y `Task/025` despliega existe."""
    from app import lambda_handler

    assert callable(lambda_handler.handler)


# --- L-02 -------------------------------------------------------------------
def test_el_handler_envuelve_la_misma_aplicacion(aplicacion_publica: FastAPI) -> None:
    """Requisito T-04: una sola aplicacion, envuelta, nunca duplicada."""
    from app.lambda_handler import crear_handler

    handler = crear_handler(aplicacion_publica)

    assert handler.app is aplicacion_publica


def test_el_handler_de_modulo_envuelve_la_instancia_que_ejecuta_uvicorn() -> None:
    """El handler productivo y `uvicorn app.main:app` sirven el mismo objeto."""
    import app.main
    from app import lambda_handler

    assert lambda_handler.handler.app is app.main.app


# --- L-03 -------------------------------------------------------------------
def test_un_evento_v2_de_health_responde_200(handler_de_la_aplicacion: Any) -> None:
    respuesta = invocar(handler_de_la_aplicacion, evento_http_api_v2())

    assert respuesta["statusCode"] == 200


# --- L-04 -------------------------------------------------------------------
def test_el_cuerpo_es_identico_al_de_la_ejecucion_asgi_local(
    handler_de_la_aplicacion: Any, aplicacion_publica: FastAPI
) -> None:
    """Criterio de salida de STAGE-08: misma respuesta por ambos caminos."""
    from fastapi.testclient import TestClient

    with TestClient(aplicacion_publica, raise_server_exceptions=False) as cliente:
        respuesta_local = cliente.get(RUTA_DE_VIVACIDAD)

    respuesta_lambda = invocar(handler_de_la_aplicacion, evento_http_api_v2())

    assert respuesta_lambda["statusCode"] == respuesta_local.status_code
    assert cuerpo_json(respuesta_lambda) == respuesta_local.json()


def test_la_respuesta_declara_el_tipo_de_contenido_json(handler_de_la_aplicacion: Any) -> None:
    """`application/json` es tipo de texto: el cuerpo no viaja en base64."""
    respuesta = invocar(handler_de_la_aplicacion, evento_http_api_v2())

    assert cabeceras_de(respuesta)["content-type"].startswith("application/json")
    assert respuesta["isBase64Encoded"] is False


# --- L-05 -------------------------------------------------------------------
@pytest.mark.parametrize("cabecera", CABECERAS_DE_SEGURIDAD)
def test_la_respuesta_lambda_conserva_las_cabeceras_de_seguridad(
    handler_de_la_aplicacion: Any, cabecera: str
) -> None:
    """Perderlas seria una regresion de `Task/018` invisible: seguiria dando 200."""
    respuesta = invocar(handler_de_la_aplicacion, evento_http_api_v2())

    assert cabecera in cabeceras_de(respuesta)


# --- L-06 -------------------------------------------------------------------
def test_la_respuesta_lambda_siempre_trae_el_correlation_id(
    handler_de_la_aplicacion: Any,
) -> None:
    respuesta = invocar(handler_de_la_aplicacion, evento_http_api_v2())

    assert cabeceras_de(respuesta)["x-request-id"]


def test_el_correlation_id_entrante_se_conserva(handler_de_la_aplicacion: Any) -> None:
    respuesta = invocar(
        handler_de_la_aplicacion,
        evento_http_api_v2(cabeceras={"x-request-id": CORRELACION_ENTRANTE}),
    )

    assert cabeceras_de(respuesta)["x-request-id"] == CORRELACION_ENTRANTE


# --- L-07 -------------------------------------------------------------------
def test_la_query_string_del_evento_llega_a_la_aplicacion(
    handler_de_la_aplicacion: Any,
) -> None:
    """Un parametro desconocido se rechaza con `422` (contrato de `Task/009`).

    Es discriminante: si el adaptador perdiera `rawQueryString`, la peticion
    llegaria sin parametros y acabaria consultando la base —donde la guarda de
    las pruebas de contrato estalla—, nunca en `422`.
    """
    respuesta = invocar(
        handler_de_la_aplicacion,
        evento_http_api_v2(ruta=RUTA_DE_ARTICULOS, consulta="parametro_inventado=1"),
    )

    assert respuesta["statusCode"] == 422
    assert cuerpo_json(respuesta)["error"]["code"] == "validation_error"


def test_la_query_string_llega_sin_alterar_al_scope(
    handler_de_sonda: Any, sonda_asgi: dict[str, Any]
) -> None:
    invocar(handler_de_sonda, evento_http_api_v2(consulta="tag=docker&page=2"))

    assert sonda_asgi["query_string"] == b"tag=docker&page=2"


# --- L-08 -------------------------------------------------------------------
def test_el_path_del_evento_llega_intacto_a_la_aplicacion(
    handler_de_sonda: Any, sonda_asgi: dict[str, Any]
) -> None:
    """Incluido el segmento variable de una ruta con parametro de camino."""
    invocar(handler_de_sonda, evento_http_api_v2(ruta="/api/v1/posts/mi-primer-articulo"))

    assert sonda_asgi["path"] == "/api/v1/posts/mi-primer-articulo"


def test_el_metodo_y_la_version_http_llegan_al_scope(
    handler_de_sonda: Any, sonda_asgi: dict[str, Any]
) -> None:
    invocar(handler_de_sonda, evento_http_api_v2(metodo="POST", ruta=RUTA_DE_ARTICULOS))

    assert sonda_asgi["type"] == "http"
    assert sonda_asgi["method"] == "POST"
    assert sonda_asgi["http_version"] == "1.1"


# --- L-09 -------------------------------------------------------------------
def test_una_ruta_inexistente_responde_404(handler_de_la_aplicacion: Any) -> None:
    respuesta = invocar(handler_de_la_aplicacion, evento_http_api_v2(ruta=RUTA_INEXISTENTE))

    assert respuesta["statusCode"] == 404


# --- L-10 -------------------------------------------------------------------
def test_el_error_conserva_el_modelo_comun_del_proyecto(
    handler_de_la_aplicacion: Any,
) -> None:
    """El adaptador no puede cambiar la envoltura de error ni filtrar trazas."""
    respuesta = invocar(handler_de_la_aplicacion, evento_http_api_v2(ruta=RUTA_INEXISTENTE))

    error = cuerpo_json(respuesta)["error"]

    assert set(error) >= {"code", "message", "request_id"}
    assert error["request_id"] == cabeceras_de(respuesta)["x-request-id"]


# --- L-11 -------------------------------------------------------------------
def test_un_metodo_no_permitido_responde_405(handler_de_la_aplicacion: Any) -> None:
    respuesta = invocar(
        handler_de_la_aplicacion, evento_http_api_v2(metodo="POST", ruta=RUTA_DE_VIVACIDAD)
    )

    assert respuesta["statusCode"] == 405


# --- L-12 -------------------------------------------------------------------
def test_las_cookies_salen_en_el_array_cookies_y_no_en_headers(handler_de_sonda: Any) -> None:
    """El riesgo caro de esta tarea.

    El formato v2 entrega las cookies en un array propio. Colapsarlas en
    `headers` haria que API Gateway emitiera **una sola** `Set-Cookie`, y la
    sesion administrativa se romperia sin ningun error visible.
    """
    respuesta = invocar(handler_de_sonda, evento_http_api_v2())

    assert cookies_de(respuesta) == [
        "primera=1; Path=/; HttpOnly",
        "segunda=2; Path=/; HttpOnly",
    ]
    assert "set-cookie" not in cabeceras_de(respuesta)


# --- L-13 -------------------------------------------------------------------
def test_las_cookies_del_evento_llegan_como_una_sola_cabecera(
    handler_de_sonda: Any, sonda_asgi: dict[str, Any]
) -> None:
    """En v2 las cookies entran como array y HTTP espera una cabecera unica."""
    invocar(
        handler_de_sonda,
        evento_http_api_v2(cookies=["blog_admin_session=abc", "otra=1"]),
    )

    recibidas = [
        valor.decode() for clave, valor in sonda_asgi["headers"] if clave.decode() == "cookie"
    ]

    assert recibidas == ["blog_admin_session=abc; otra=1"]


# --- L-14 -------------------------------------------------------------------
def test_la_direccion_de_origen_sobrevive_al_adaptador(
    handler_de_sonda: Any, sonda_asgi: dict[str, Any]
) -> None:
    """`requestContext.http.sourceIp` es la unica fuente de la IP en Lambda."""
    invocar(handler_de_sonda, evento_http_api_v2())

    assert sonda_asgi["client"] == (DIRECCION_DE_ORIGEN, 0)


def test_la_politica_de_confianza_vigente_resuelve_esa_direccion(
    handler_de_sonda: Any, sonda_asgi: dict[str, Any]
) -> None:
    """El consumidor real de `request.client.host` recibe la IP del evento.

    `Task/023` **no** rediseña la politica de confianza en proxies: la ejercita
    tal cual esta, con su valor por defecto —`0` saltos, que ignora
    `X-Forwarded-For` por completo— para demostrar que el dato sobrevive.
    """
    from app.shared.security.peticiones import direccion_del_cliente

    invocar(handler_de_sonda, evento_http_api_v2(cabeceras={"x-forwarded-for": "198.51.100.7"}))
    anfitrion, _ = sonda_asgi["client"]

    resuelta = direccion_del_cliente(
        direccion_del_par=anfitrion,
        cabecera_reenviada="198.51.100.7",
        saltos_de_confianza=0,
    )

    assert resuelta == DIRECCION_DE_ORIGEN


# --- L-16 -------------------------------------------------------------------
def test_invocar_el_handler_no_exige_credenciales_aws(
    handler_de_la_aplicacion: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ni credenciales, ni region, ni endpoint: el adaptador es local y puro.

    `Task/023` no toca AWS real (ETAPA 09 y 10). Si alguna vez el handler
    necesitara hablar con AWS para responder, esta prueba se pondria roja.
    """
    for nombre in [clave for clave in os.environ if clave.upper().startswith("AWS_")]:
        monkeypatch.delenv(nombre, raising=False)

    respuesta = invocar(handler_de_la_aplicacion, evento_http_api_v2())

    assert respuesta["statusCode"] == 200
