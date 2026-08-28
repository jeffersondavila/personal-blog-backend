"""Politica de parametros de consulta de la API publica (matriz I, J, K).

api-contracts.md seccion 6 dejaba la decision abierta: *"los filtros
desconocidos se ignoran o se rechazan de forma consistente; la decision se fija
en `Task/009`"*.

**Decision D-009-C: se rechazan con `422`.** El proyecto ya es estricto ante
claves desconocidas de forma consistente —`Settings` usa `extra="forbid"`,
pytest se ejecuta con `--strict-markers` y `--strict-config`—, e ignorar
convierte una errata del cliente (`?tagg=docker`) en un listado silenciosamente
sin filtrar. Rechazar hace que OpenAPI **sea** el contrato en lugar de
describirlo.

Consecuencia que interesa a la seguridad: `status` no es un parametro publico,
asi que `?status=draft` no se ignora — se rechaza. No existe ninguna forma de
pedir contenido no publicado.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.shared.pagination import PAGE_SIZE_MAXIMO, PAGE_SIZE_POR_DEFECTO

#: Los seis listados publicos comparten politica de parametros. Se prueban
#: todos: una politica aplicada solo a `posts` no seria una politica.
LISTADOS = [
    "/api/v1/posts",
    "/api/v1/book-reviews",
    "/api/v1/videos",
    "/api/v1/projects",
    "/api/v1/tags",
]

#: Listados que aceptan filtros de contenido. `tags` no los acepta.
LISTADOS_DE_CONTENIDO = [
    "/api/v1/posts",
    "/api/v1/book-reviews",
    "/api/v1/videos",
    "/api/v1/projects",
]


def _error(respuesta: Any) -> dict[str, Any]:
    cuerpo: dict[str, Any] = respuesta.json()
    return dict(cuerpo["error"])


# --- J-01: parametro desconocido -------------------------------------------
@pytest.mark.parametrize("ruta", LISTADOS)
def test_un_parametro_desconocido_se_rechaza(cliente_publico: TestClient, ruta: str) -> None:
    respuesta = cliente_publico.get(ruta, params={"parametro_inventado": "1"})

    assert respuesta.status_code == 422
    assert _error(respuesta)["code"] == "validation_error"


def test_el_error_nombra_el_parametro_rechazado(cliente_publico: TestClient) -> None:
    respuesta = cliente_publico.get("/api/v1/posts", params={"tagg": "docker"})

    detalles = str(_error(respuesta)["details"])
    assert "tagg" in detalles


# --- J-02: `status` no es publico ------------------------------------------
@pytest.mark.parametrize("ruta", LISTADOS_DE_CONTENIDO)
@pytest.mark.parametrize("valor", ["draft", "archived", "published"])
def test_status_no_es_un_parametro_publico(
    cliente_publico: TestClient, ruta: str, valor: str
) -> None:
    """No se ignora: se rechaza. No hay forma de pedir contenido no publicado."""
    respuesta = cliente_publico.get(ruta, params={"status": valor})

    assert respuesta.status_code == 422


# --- J-03: `sort` es una lista cerrada -------------------------------------
@pytest.mark.parametrize("ruta", LISTADOS_DE_CONTENIDO)
@pytest.mark.parametrize(
    "valor",
    [
        "id",
        "content",
        "status",
        "slug",
        "created_at",
        "published_at asc",
        "title; DROP TABLE posts",
        "-",
        "",
    ],
)
def test_un_orden_fuera_de_la_lista_cerrada_se_rechaza(
    cliente_publico: TestClient, ruta: str, valor: str
) -> None:
    """El valor nunca llega a SQL: el tipo `Literal` lo rechaza en el transporte."""
    respuesta = cliente_publico.get(ruta, params={"sort": valor})

    assert respuesta.status_code == 422
    assert _error(respuesta)["code"] == "validation_error"


# --- J-04: la lista de admitidos se deriva de la propia ruta ---------------
def test_los_parametros_declarados_son_admitidos(cliente_publico: TestClient) -> None:
    """Guarda anti-tautologia de la politica de rechazo.

    Si la derivacion de parametros admitidos se rompiera —por ejemplo al
    cambiar de version de FastAPI—, el rechazo pasaria a aplicarse a **todo** y
    las pruebas de arriba seguirian verdes mientras la API queda inservible.
    Esta comprobacion se pone roja en ese caso: los parametros que la operacion
    declara tienen que pasar.
    """
    respuesta = cliente_publico.get(
        "/api/v1/posts",
        params={"page": 1, "page_size": 5, "tag": "docker", "featured": "true", "sort": "title"},
    )

    assert respuesta.status_code != 422, (
        "los parametros declarados por la propia operacion fueron rechazados: "
        "la derivacion de nombres admitidos no esta funcionando y la politica "
        "de D-009-C estaria rechazando peticiones legitimas."
    )


# --- I-01, I-02, I-04: validacion de la paginacion -------------------------
@pytest.mark.parametrize("ruta", LISTADOS)
@pytest.mark.parametrize("page", ["0", "-1", "abc", "1.5", ""])
def test_una_pagina_invalida_se_rechaza(cliente_publico: TestClient, ruta: str, page: str) -> None:
    respuesta = cliente_publico.get(ruta, params={"page": page})

    assert respuesta.status_code == 422


@pytest.mark.parametrize("ruta", LISTADOS)
@pytest.mark.parametrize("page_size", ["0", "-1", "abc"])
def test_un_tamano_de_pagina_invalido_se_rechaza(
    cliente_publico: TestClient, ruta: str, page_size: str
) -> None:
    respuesta = cliente_publico.get(ruta, params={"page_size": page_size})

    assert respuesta.status_code == 422


def test_el_tamano_maximo_no_es_un_error_sino_un_recorte(cliente_publico: TestClient) -> None:
    """api-contracts.md seccion 5: por encima del maximo **se recorta**.

    Aqui solo se comprueba que **no** es un `422`; que el valor devuelto sea el
    maximo se demuestra con datos reales en `tests/integration/`.
    """
    respuesta = cliente_publico.get("/api/v1/posts", params={"page_size": PAGE_SIZE_MAXIMO + 1})

    assert respuesta.status_code != 422


# --- D-009-G: `featured` no admite coerciones ambiguas ---------------------
@pytest.mark.parametrize("ruta", LISTADOS_DE_CONTENIDO)
@pytest.mark.parametrize("valor", ["1", "0", "yes", "no", "on", "off", "True", "FALSE", ""])
def test_featured_solo_admite_los_literales_true_y_false(
    cliente_publico: TestClient, ruta: str, valor: str
) -> None:
    respuesta = cliente_publico.get(ruta, params={"featured": valor})

    assert respuesta.status_code == 422


# --- H-07: validacion de `q` -----------------------------------------------
def test_la_busqueda_exige_termino(cliente_publico: TestClient) -> None:
    respuesta = cliente_publico.get("/api/v1/search")

    assert respuesta.status_code == 422


@pytest.mark.parametrize("termino", ["", " ", "a", "  a  "])
def test_un_termino_demasiado_corto_se_rechaza(cliente_publico: TestClient, termino: str) -> None:
    """USER_FLOWS.md A.8: *"termino minimo de 2 caracteres"*, ya recortado."""
    respuesta = cliente_publico.get("/api/v1/search", params={"q": termino})

    assert respuesta.status_code == 422


def test_un_termino_desmesurado_se_rechaza(cliente_publico: TestClient) -> None:
    respuesta = cliente_publico.get("/api/v1/search", params={"q": "x" * 101})

    assert respuesta.status_code == 422


# --- K: envoltura comun de error -------------------------------------------
def test_el_error_de_validacion_usa_la_envoltura_comun(cliente_publico: TestClient) -> None:
    """api-contracts.md seccion 7. No se inventa un segundo formato de error."""
    respuesta = cliente_publico.get("/api/v1/posts", params={"page": 0})

    assert respuesta.status_code == 422
    error = _error(respuesta)
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == "validation_error"
    assert error["request_id"]


def test_el_error_no_filtra_detalles_internos(cliente_publico: TestClient) -> None:
    """Requisito S-07: ni SQL, ni trazas, ni rutas, ni nombres de clase."""
    cuerpo = cliente_publico.get("/api/v1/posts", params={"page": 0}).text.lower()

    for filtracion in ("traceback", "select ", "sqlalchemy", "psycopg", "\\app\\", "/app/"):
        assert filtracion not in cuerpo, f"la respuesta de error filtra {filtracion!r}"


def test_los_valores_por_defecto_de_la_paginacion_estan_documentados(
    cliente_publico: TestClient,
) -> None:
    """I-01: el defecto es el declarado por D-009-A, no el que herede FastAPI."""
    documento: dict[str, Any] = cliente_publico.get("/openapi.json").json()
    parametros = documento["paths"]["/api/v1/posts"]["get"]["parameters"]
    por_nombre = {parametro["name"]: parametro for parametro in parametros}

    assert por_nombre["page"]["schema"]["default"] == 1
    assert por_nombre["page_size"]["schema"]["default"] == PAGE_SIZE_POR_DEFECTO
