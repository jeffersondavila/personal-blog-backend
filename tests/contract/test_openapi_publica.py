"""La especificacion OpenAPI describe exactamente la API de `Task/009` (matriz L).

api-contracts.md seccion 11 declara la especificacion OpenAPI generada como un
**resultado** de `Task/009` y `Task/012`. Estas pruebas la tratan como tal: no
comprueban que exista, comprueban que **coincide con el contrato**.

Importa mas de lo que parece. La especificacion es lo que el frontend lee para
saber que puede pedir; una ruta administrativa filtrada ahi por descuido
anunciaria una superficie que no debe existir todavia, y un endpoint documentado
de mas —`/videos/{slug}`— comprometeria el contrato `v1`, del que ya no podria
retirarse sin `/api/v2` (api-contracts.md seccion 10).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

#: Las **diez** rutas publicas del contrato vigente (api-contracts.md seccion 3),
#: mas la sonda de vivacidad, que vive fuera del prefijo versionado a proposito.
#:
#: Se escriben una a una en lugar de derivarlas de la aplicacion: derivarlas
#: haria que la prueba se adaptara sola a cualquier ruta nueva, que es justo lo
#: que no debe hacer. Aqui el contrato es la lista, y la aplicacion tiene que
#: coincidir con ella.
RUTAS_ESPERADAS = {
    "/health",
    "/api/v1/profile",
    "/api/v1/posts",
    "/api/v1/posts/{slug}",
    "/api/v1/book-reviews",
    "/api/v1/book-reviews/{slug}",
    "/api/v1/videos",
    "/api/v1/projects",
    "/api/v1/projects/{slug}",
    "/api/v1/tags",
    "/api/v1/search",
}

#: Los **tres** endpoints de autenticacion que anade `Task/011`.
RUTAS_DE_AUTENTICACION = {
    "/api/v1/admin/auth/login",
    "/api/v1/admin/auth/logout",
    "/api/v1/admin/auth/me",
}

#: Prefijo de todo lo administrativo. Desde `Task/012` hay 23 rutas mas bajo el,
#: y su contrato **exacto** vive en `test_contrato_administrativo.py`: este
#: modulo comprueba la API **publica**, y duplicar aqui la lista administrativa
#: la condenaria a divergir.
PREFIJO_ADMINISTRATIVO = "/api/v1/admin"


@pytest.fixture
def documento(cliente_publico: TestClient) -> dict[str, Any]:
    """Especificacion OpenAPI generada por la aplicacion."""
    contenido: dict[str, Any] = cliente_publico.get("/openapi.json").json()
    return contenido


# --- L-01: rutas exactas ---------------------------------------------------
def test_la_especificacion_declara_exactamente_las_rutas_del_contrato(
    documento: dict[str, Any],
) -> None:
    """Las diez rutas publicas y la sonda de vivacidad, **exactamente**.

    **La expectativa cambio en `Task/011` y otra vez en `Task/012`**, las dos
    por un cambio de requisito —el primero de los supuestos que
    BACKEND_TESTING_STRATEGY.md seccion 9 admite—: hasta `Task/011` no existia
    ningun endpoint administrativo, y hasta `Task/012` no existia el CRUD.

    Lo que la prueba protege **no** cambia, y el conjunto sigue siendo cerrado y
    escrito a mano: una ruta publica nueva sigue teniendo que anotarse aqui para
    pasar. Lo que cambia es su **alcance**: este modulo comprueba la API
    publica, asi que mira lo que **no** cuelga del prefijo administrativo. El
    conjunto exacto de rutas administrativas se comprueba, igual de cerrado, en
    `test_contrato_administrativo.py`.
    """
    publicas = {ruta for ruta in documento["paths"] if not ruta.startswith(PREFIJO_ADMINISTRATIVO)}

    assert publicas == RUTAS_ESPERADAS


# --- L-02: ningun endpoint administrativo ----------------------------------
def test_la_autenticacion_sigue_siendo_las_tres_rutas_de_task_011(
    documento: dict[str, Any],
) -> None:
    """Regresion de `Task/011`: sus tres endpoints, intactos.

    Antes esta prueba exigia que **lo unico** administrativo fuera la
    autenticacion, y anotaba que el CRUD llegaria en `Task/012`. Ha llegado, asi
    que la prueba se estrecha a lo que sigue protegiendo: que bajo
    `/admin/auth` no aparezca ni desaparezca nada — en particular, que no se
    cuele un `register` o un `reset-password` que ninguna fuente pide.
    """
    de_autenticacion = {
        ruta for ruta in documento["paths"] if ruta.startswith(f"{PREFIJO_ADMINISTRATIVO}/auth")
    }

    assert de_autenticacion == RUTAS_DE_AUTENTICACION


# --- L-03: no existe detalle de video --------------------------------------
def test_no_se_declara_el_detalle_de_video(documento: dict[str, Any]) -> None:
    """No esta en el contrato canonico y `Task/009` no lo inventa."""
    assert "/api/v1/videos/{slug}" not in documento["paths"]


# --- L-04: solo lectura ----------------------------------------------------
def test_la_api_publica_es_de_solo_lectura(documento: dict[str, Any]) -> None:
    """Ningun endpoint **publico** escribe: los flujos publicos no modifican datos.

    Las rutas administrativas quedan fuera del recorrido porque escribir es
    justamente lo que hacen. La comprobacion se estrecha al conjunto del que la
    afirmacion sigue siendo cierta, en lugar de relajarse: desde `Task/012` el
    filtro es el **prefijo**, no una lista de tres rutas.
    """
    for ruta, operaciones in documento["paths"].items():
        if ruta.startswith(PREFIJO_ADMINISTRATIVO):
            continue
        metodos = {metodo.lower() for metodo in operaciones}
        assert metodos == {"get"}, f"{ruta} declara metodos distintos de GET: {sorted(metodos)}"


# --- L-06: `status` no es un parametro publico -----------------------------
def test_ningun_endpoint_publico_declara_el_parametro_status(
    documento: dict[str, Any],
) -> None:
    """api-contracts.md seccion 6: `status` es **solo administrativo**.

    Antes de `Task/012` la comprobacion podia recorrer la especificacion entera,
    porque no existia ningun endpoint administrativo con filtros. Ahora los
    cuatro listados del panel **si** declaran `status` —es su unico filtro,
    decision D-012-M—, asi que la prueba se estrecha al lado del que la
    afirmacion sigue siendo cierta: el publico. Que los administrativos sean
    **exactamente** esos cuatro se comprueba en `test_contrato_administrativo.py`.
    """
    for ruta, operaciones in documento["paths"].items():
        if ruta.startswith(PREFIJO_ADMINISTRATIVO):
            continue
        for metodo, operacion in operaciones.items():
            nombres = {parametro["name"] for parametro in operacion.get("parameters", [])}
            assert "status" not in nombres, f"{metodo.upper()} {ruta} declara `status`"


# --- L-05: parametros y esquemas documentados ------------------------------
@pytest.mark.parametrize(
    ("ruta", "esperados"),
    [
        ("/api/v1/posts", {"page", "page_size", "tag", "featured", "sort"}),
        ("/api/v1/book-reviews", {"page", "page_size", "tag", "featured", "sort"}),
        ("/api/v1/videos", {"page", "page_size", "tag", "featured", "sort"}),
        ("/api/v1/projects", {"page", "page_size", "tag", "featured", "sort"}),
        ("/api/v1/tags", {"page", "page_size"}),
        ("/api/v1/search", {"q", "page", "page_size"}),
        ("/api/v1/profile", set()),
    ],
)
def test_cada_endpoint_declara_sus_parametros(
    documento: dict[str, Any], ruta: str, esperados: set[str]
) -> None:
    """Los parametros declarados son ademas los **unicos** admitidos (D-009-C)."""
    operacion = documento["paths"][ruta]["get"]
    nombres = {parametro["name"] for parametro in operacion.get("parameters", [])}

    assert nombres == esperados


def test_el_orden_se_documenta_como_lista_cerrada(documento: dict[str, Any]) -> None:
    """D-009-D y D-009-E: cuatro valores admitidos, ninguno mas."""
    parametros = documento["paths"]["/api/v1/posts"]["get"]["parameters"]
    sort = next(parametro for parametro in parametros if parametro["name"] == "sort")

    valores: set[str] = set()
    for alternativa in sort["schema"].get("anyOf", [sort["schema"]]):
        valores |= set(alternativa.get("enum", []))

    assert valores == {"published_at", "-published_at", "title", "-title"}


def test_el_destacado_se_documenta_como_literal(documento: dict[str, Any]) -> None:
    """D-009-G: solo `true` y `false`, sin coerciones ambiguas."""
    parametros = documento["paths"]["/api/v1/posts"]["get"]["parameters"]
    featured = next(parametro for parametro in parametros if parametro["name"] == "featured")

    valores: set[str] = set()
    for alternativa in featured["schema"].get("anyOf", [featured["schema"]]):
        valores |= set(alternativa.get("enum", []))

    assert valores == {"true", "false"}


@pytest.mark.parametrize(
    ("ruta", "esquema"),
    [
        ("/api/v1/profile", "ProfilePublico"),
        ("/api/v1/posts", "Pagina_PostDeListado_"),
        ("/api/v1/posts/{slug}", "PostDetallado"),
        ("/api/v1/book-reviews", "Pagina_ReviewDeListado_"),
        ("/api/v1/book-reviews/{slug}", "ReviewDetallada"),
        ("/api/v1/videos", "Pagina_VideoDeListado_"),
        ("/api/v1/projects", "Pagina_ProyectoDeListado_"),
        ("/api/v1/projects/{slug}", "ProyectoDetallado"),
        ("/api/v1/tags", "Pagina_EtiquetaPublica_"),
        ("/api/v1/search", "Pagina_ResultadoDeBusqueda_"),
    ],
)
def test_cada_endpoint_declara_su_modelo_de_respuesta(
    documento: dict[str, Any], ruta: str, esquema: str
) -> None:
    """Se devuelven modelos explicitos, nunca modelos ORM."""
    respuesta = documento["paths"][ruta]["get"]["responses"]["200"]
    referencia = respuesta["content"]["application/json"]["schema"]["$ref"]

    assert referencia.endswith(f"/{esquema}")


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/v1/posts",
        "/api/v1/book-reviews",
        "/api/v1/videos",
        "/api/v1/projects",
        "/api/v1/tags",
        "/api/v1/search",
    ],
)
def test_la_envoltura_de_paginacion_se_documenta_entera(
    documento: dict[str, Any], ruta: str
) -> None:
    """Los cinco campos de api-contracts.md seccion 5, en todas las colecciones."""
    referencia = documento["paths"][ruta]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    esquema = documento["components"]["schemas"][referencia.rsplit("/", 1)[-1]]

    assert set(esquema["properties"]) == {"items", "page", "page_size", "total", "pages"}


# --- El contrato de error tambien se documenta -----------------------------
@pytest.mark.parametrize(
    "ruta", ["/api/v1/posts/{slug}", "/api/v1/book-reviews/{slug}", "/api/v1/projects/{slug}"]
)
def test_los_detalles_documentan_su_404(documento: dict[str, Any], ruta: str) -> None:
    referencia = documento["paths"][ruta]["get"]["responses"]["404"]["content"]["application/json"][
        "schema"
    ]["$ref"]

    assert referencia.endswith("/RespuestaDeError")


def test_el_422_documentado_es_la_envoltura_real_del_proyecto(documento: dict[str, Any]) -> None:
    """Sin esto, la especificacion describiria la forma por defecto de FastAPI.

    FastAPI documenta por su cuenta un `422` con una lista `detail`, que **no**
    es lo que este backend devuelve. Un cliente generado desde una
    especificacion asi fallaria al leer el primer error de validacion.
    """
    referencia = documento["paths"]["/api/v1/posts"]["get"]["responses"]["422"]["content"][
        "application/json"
    ]["schema"]["$ref"]

    assert referencia.endswith("/RespuestaDeError")

    error = documento["components"]["schemas"]["DetalleDeError"]
    assert set(error["properties"]) == {"code", "message", "details", "request_id"}


def test_no_queda_rastro_del_error_por_defecto_de_fastapi(documento: dict[str, Any]) -> None:
    """Guarda de coherencia: dos formas de error documentadas serian una de mas."""
    esquemas = set(documento["components"]["schemas"])

    assert "HTTPValidationError" not in esquemas


# --- Ningun esquema publico filtra campos internos -------------------------
@pytest.mark.parametrize(
    "esquema",
    [
        "PostDeListado",
        "PostDetallado",
        "ReviewDeListado",
        "ReviewDetallada",
        "VideoDeListado",
        "ProyectoDeListado",
        "ProyectoDetallado",
        "ProfilePublico",
        "EtiquetaPublica",
        "MedioPublico",
        "ResultadoDeBusqueda",
    ],
)
def test_ningun_esquema_publico_declara_campos_internos(
    documento: dict[str, Any], esquema: str
) -> None:
    """La comprobacion se hace sobre el **contrato**, no sobre una respuesta.

    Las pruebas de integracion comprueban que una respuesta concreta no lleva
    estos campos; esta comprueba que el contrato no los promete siquiera, que es
    lo que impide que aparezcan el dia que se sirva otro contenido.
    """
    internos = {"id", "status", "is_singleton", "created_at", "updated_at", "object_key"}
    propiedades = set(documento["components"]["schemas"][esquema]["properties"])

    filtrados = propiedades & internos
    assert not filtrados, f"{esquema} declara campos internos: {sorted(filtrados)}"


def test_la_referencia_a_un_medio_declara_su_campo_de_acceso(documento: dict[str, Any]) -> None:
    """Decision **D-009-O**, cerrada por `Task/010`.

    `Task/009` dejo este caso afirmando `{alt_text, width, height}` **para que
    anadir el acceso fuera una decision consciente y no un efecto colateral**.
    Esa es exactamente la condicion que se cumple ahora: el requisito cambio de
    forma documentada —api-contracts.md seccion 11 y data-model.md seccion 10
    asignan el campo a `Task/010`— y la expectativa se actualiza con el.

    El conjunto sigue siendo **cerrado**: la prueba no se relaja a "contiene
    access_url", porque entonces dejaria de detectar un campo de mas.
    """
    propiedades = set(documento["components"]["schemas"]["MedioPublico"]["properties"])

    assert propiedades == {"alt_text", "width", "height", "access_url"}


def test_el_esquema_del_medio_no_menciona_el_bucket_ni_la_region(
    documento: dict[str, Any],
) -> None:
    """El contrato publico no puede describir la infraestructura que hay detras.

    Ni el nombre del bucket, ni la region, ni la clave del objeto: son datos del
    proveedor, y publicarlos los convertiria en parte del contrato `v1`
    (api-contracts.md seccion 10, regla 2).
    """
    esquema = json.dumps(documento["components"]["schemas"]["MedioPublico"]).lower()

    for prohibido in ("bucket", "object_key", "region", "aws", "minio", "s3"):
        assert prohibido not in esquema
