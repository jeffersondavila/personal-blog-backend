"""L-18 — la sesion administrativa real sobrevive al adaptador Lambda (`Task/023`).

Por que esta prueba existe, y por que contra PostgreSQL real
------------------------------------------------------------

El riesgo mas caro de `Task/023` no es que falle una traduccion cualquiera: es
que falle **la de las cookies**, porque el sintoma seria silencioso. El
*payload format* 2.0 de API Gateway entrega las cookies en un array propio,
separado de `headers`. Un adaptador que las colapsara en `headers` seguiria
devolviendo `200` en el inicio de sesion; simplemente, el panel administrativo
no volveria a entrar nunca.

`tests/contract/test_handler_lambda.py` fija esa traduccion contra una
aplicacion ASGI diminuta, que demuestra la **mecanica**. Esto demuestra el
**producto**: el flujo autentico de `Task/011` —`POST /admin/auth/login`,
sesion opaca *server-side* persistida en PostgreSQL, y `GET /admin/auth/me`
recuperandola en la peticion siguiente— recorrido entero a traves del handler
de Lambda, con la cookie viajando por donde viajara en produccion.

Nada de esto es simulable sin base de datos: la sesion **es** una fila.

Politica de la integracion (heredada, no relajada)
--------------------------------------------------

- `PERSONAL_BLOG_TEST_DATABASE_URL` **no definida** -> `SKIP` con motivo.
- Definida -> PostgreSQL **debe** funcionar: cualquier fallo es `FAIL`.

La fixture de abajo deriva de `database_settings` y `sesion_de_pruebas`, ambas
descendientes de `destino_de_integracion_verificado`, de modo que la guarda
*fail-closed* del harness sigue intacta (`CERT-AUD-002`).

Por que la cookie **no** se marca insegura aqui
-----------------------------------------------

`cliente_administrativo` construye la aplicacion con `auth_cookie_secure=False`
porque `TestClient` habla HTTP y un cliente que respete la norma no reenvia una
cookie `Secure` recibida por HTTP. Aqui no hay navegador ni httpx de por medio:
la cookie se lee del array `cookies` de la respuesta y se devuelve en el array
`cookies` del evento siguiente, que es exactamente lo que hace API Gateway. Por
eso esta prueba corre con la configuracion **por defecto**, `Secure` incluido,
que es la de produccion.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.shared.configuration import Settings
from tests.eventos_lambda import (
    cabeceras_de,
    cookies_de,
    cuerpo_json,
    evento_con_json,
    evento_http_api_v2,
    invocar,
    par_de_cookie,
)
from tests.integration.datos_de_autenticacion import CONTRASENA, CORREO, administrador

pytestmark = pytest.mark.integration

ACCESO = "/api/v1/admin/auth/login"
SESION_ACTUAL = "/api/v1/admin/auth/me"
CIERRE = "/api/v1/admin/auth/logout"
NOMBRE_DE_LA_COOKIE = "blog_admin_session"


@pytest.fixture
def handler_administrativo(database_settings: Settings, sesion_de_pruebas: Session) -> Any:
    """Handler Lambda sobre la aplicacion conectada a la transaccion de la prueba.

    Se sustituye `get_session` por el mismo motivo que en `cliente_de_la_api`: la
    dependencia real abre su propia sesion con `session_scope`, que confirma al
    salir, y cada invocacion escaparia del aislamiento de la prueba.
    """
    from app.lambda_handler import crear_handler
    from app.main import create_app
    from app.shared.database import get_session

    aplicacion = create_app(settings=database_settings)
    aplicacion.dependency_overrides[get_session] = lambda: sesion_de_pruebas

    return crear_handler(aplicacion)


def _acceder(handler: Any) -> dict[str, Any]:
    return invocar(
        handler,
        evento_con_json(
            metodo="POST",
            ruta=ACCESO,
            datos={"email": CORREO, "password": CONTRASENA},
        ),
    )


# --- L-18 -------------------------------------------------------------------
def test_el_acceso_entrega_la_cookie_en_el_array_de_cookies(
    handler_administrativo: Any, sesion_de_pruebas: Session
) -> None:
    """La cookie de sesion sale por `cookies[]`, no colapsada en `headers`."""
    administrador(sesion_de_pruebas)

    respuesta = _acceder(handler_administrativo)

    assert respuesta["statusCode"] == 200
    entregadas = cookies_de(respuesta)
    assert [cookie for cookie in entregadas if cookie.startswith(f"{NOMBRE_DE_LA_COOKIE}=")]
    assert "set-cookie" not in cabeceras_de(respuesta)


def test_la_cookie_entregada_conserva_sus_atributos_de_seguridad(
    handler_administrativo: Any, sesion_de_pruebas: Session
) -> None:
    """El adaptador transporta la cookie entera, no solo el par `nombre=valor`."""
    administrador(sesion_de_pruebas)

    respuesta = _acceder(handler_administrativo)
    cookie = next(
        valor for valor in cookies_de(respuesta) if valor.startswith(f"{NOMBRE_DE_LA_COOKIE}=")
    )

    assert "HttpOnly" in cookie
    assert "Secure" in cookie


def test_la_sesion_administrativa_sobrevive_al_handler(
    handler_administrativo: Any, sesion_de_pruebas: Session
) -> None:
    """El ciclo completo: acceder, recibir la cookie y volver a usarla.

    Es la prueba que impide que el adaptador rompa el panel en silencio.
    """
    fila = administrador(sesion_de_pruebas)

    acceso = _acceder(handler_administrativo)
    cookie = next(
        valor for valor in cookies_de(acceso) if valor.startswith(f"{NOMBRE_DE_LA_COOKIE}=")
    )

    sesion = invocar(
        handler_administrativo,
        evento_http_api_v2(ruta=SESION_ACTUAL, cookies=[par_de_cookie(cookie)]),
    )

    assert sesion["statusCode"] == 200
    assert cuerpo_json(sesion) == {
        "id": str(fila.id),
        "email": CORREO,
        "display_name": fila.display_name,
    }


def test_sin_cookie_la_sesion_actual_sigue_rechazandose(
    handler_administrativo: Any, sesion_de_pruebas: Session
) -> None:
    """Caso negativo: el adaptador no puede volver publica una ruta protegida."""
    administrador(sesion_de_pruebas)

    sesion = invocar(handler_administrativo, evento_http_api_v2(ruta=SESION_ACTUAL))

    assert sesion["statusCode"] == 401


def test_el_cierre_de_sesion_invalida_la_cookie_a_traves_del_handler(
    handler_administrativo: Any, sesion_de_pruebas: Session
) -> None:
    """Cerrar sesion tambien viaja por el adaptador, y deja de valer de verdad."""
    administrador(sesion_de_pruebas)

    acceso = _acceder(handler_administrativo)
    cookie = par_de_cookie(
        next(valor for valor in cookies_de(acceso) if valor.startswith(f"{NOMBRE_DE_LA_COOKIE}="))
    )

    cierre = invocar(
        handler_administrativo,
        evento_http_api_v2(metodo="POST", ruta=CIERRE, cookies=[cookie]),
    )
    despues = invocar(
        handler_administrativo,
        evento_http_api_v2(ruta=SESION_ACTUAL, cookies=[cookie]),
    )

    assert cierre["statusCode"] == 204
    assert despues["statusCode"] == 401


def test_la_direccion_de_origen_del_evento_llega_a_la_auditoria(
    handler_administrativo: Any, sesion_de_pruebas: Session
) -> None:
    """L-14 contra el producto real: la IP del evento acaba en `audit_events`.

    Cierra el circulo que el contrato abre: alli se demuestra que la direccion
    llega al *scope*; aqui, que el codigo que la consume la persiste. Perderla
    dejaria la auditoria llena de `unknown` sin ningun error visible.
    """
    from app.modules.audit.infrastructure.models import AuditEvent

    administrador(sesion_de_pruebas)

    _acceder(handler_administrativo)

    direcciones = {fila.ip_address for fila in sesion_de_pruebas.query(AuditEvent).all()}

    assert direcciones == {"203.0.113.42"}
