"""El contrato administrativo, comprobado sobre la especificacion OpenAPI.

`api-contracts.md` seccion 11 declara la especificacion OpenAPI generada como un
**resultado** de `Task/009` y `Task/012`. Estas pruebas la tratan como tal: no
comprueban que exista, comprueban que **coincide con el contrato**.

La prueba que mas trabajo hace es `test_todo_endpoint_administrativo_exige_sesion`.
Recorre la especificacion **entera** en lugar de comprobar un endpoint concreto,
porque el defecto que importa no es que uno falle: es que **un router futuro se
monte sin proteccion y nadie se entere**. Probar endpoint a endpoint no detecta
lo que todavia no existe; recorrer el documento, si.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

#: Las **diez** rutas publicas de `Task/009` mas la sonda de vivacidad.
RUTAS_PUBLICAS = {
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

#: Los **tres** endpoints de autenticacion de `Task/011`.
ACCESO = "/api/v1/admin/auth/login"
RUTAS_DE_AUTENTICACION = {
    ACCESO,
    "/api/v1/admin/auth/logout",
    "/api/v1/admin/auth/me",
}

#: Las **23** rutas administrativas de `Task/012`, escritas una a una.
#:
#: Se escriben a mano y no se derivan de la aplicacion: derivarlas haria que la
#: prueba se adaptara sola a cualquier ruta nueva, que es justo lo que no debe
#: hacer. Aqui el contrato es la lista, y la aplicacion tiene que coincidir.
RUTAS_ADMINISTRATIVAS = {
    "/api/v1/admin/profile",
    "/api/v1/admin/posts",
    "/api/v1/admin/posts/{post_id}",
    "/api/v1/admin/posts/{post_id}/publish",
    "/api/v1/admin/posts/{post_id}/unpublish",
    "/api/v1/admin/posts/{post_id}/archive",
    "/api/v1/admin/book-reviews",
    "/api/v1/admin/book-reviews/{review_id}",
    "/api/v1/admin/book-reviews/{review_id}/publish",
    "/api/v1/admin/book-reviews/{review_id}/unpublish",
    "/api/v1/admin/book-reviews/{review_id}/archive",
    "/api/v1/admin/videos",
    "/api/v1/admin/videos/{video_id}",
    "/api/v1/admin/videos/{video_id}/publish",
    "/api/v1/admin/videos/{video_id}/archive",
    "/api/v1/admin/projects",
    "/api/v1/admin/projects/{project_id}",
    "/api/v1/admin/projects/{project_id}/publish",
    "/api/v1/admin/projects/{project_id}/archive",
    "/api/v1/admin/tags",
    "/api/v1/admin/tags/{tag_id}",
    "/api/v1/admin/media",
    "/api/v1/admin/media/{media_id}",
}


@pytest.fixture
def documento(cliente_publico: TestClient) -> dict[str, Any]:
    """Especificacion OpenAPI generada por la aplicacion."""
    contenido: dict[str, Any] = cliente_publico.get("/openapi.json").json()
    return contenido


# --- O-01: la comprobacion transversal de autorizacion ---------------------
def test_todo_endpoint_administrativo_exige_sesion(documento: dict[str, Any]) -> None:
    """Toda operacion bajo `/admin`, **salvo `login`**, declara su seguridad.

    Es la comprobacion que detectaria el defecto mas caro de esta tarea: un
    router administrativo nuevo montado sin `AdministradorRequerido`. No depende
    de que nadie se acuerde de anadirlo a una lista — recorre lo que la
    aplicacion **publica**.
    """
    sin_proteger: list[str] = []
    for ruta, operaciones in documento["paths"].items():
        if not ruta.startswith("/api/v1/admin") or ruta == ACCESO:
            continue
        for metodo, operacion in operaciones.items():
            if operacion.get("security") != [{"sesionAdministrativa": []}]:
                sin_proteger.append(f"{metodo.upper()} {ruta}")

    assert not sin_proteger, f"endpoints administrativos sin autenticacion: {sin_proteger}"


def test_la_comprobacion_transversal_inspecciona_algo(documento: dict[str, Any]) -> None:
    """Guarda anti-tautologia de la prueba anterior.

    Si el filtro dejara de encontrar rutas administrativas, la comprobacion
    pasaria **sin haber inspeccionado nada**. Se exige que encuentre al menos
    las que el contrato declara.
    """
    administrativas = {ruta for ruta in documento["paths"] if ruta.startswith("/api/v1/admin")}

    assert len(administrativas) >= len(RUTAS_ADMINISTRATIVAS)


# --- O-02: `login` sigue siendo el unico administrativo publico ------------
def test_el_acceso_sigue_siendo_el_unico_endpoint_administrativo_publico(
    documento: dict[str, Any],
) -> None:
    """security-boundaries.md seccion 2 y 11.4: `login` y nada mas."""
    publicos = [
        f"{metodo.upper()} {ruta}"
        for ruta, operaciones in documento["paths"].items()
        if ruta.startswith("/api/v1/admin")
        for metodo, operacion in operaciones.items()
        if "security" not in operacion
    ]

    assert publicos == ["POST /api/v1/admin/auth/login"]


# --- O-03: la API publica sigue siendo anonima -----------------------------
def test_ninguna_ruta_publica_declara_seguridad(documento: dict[str, Any]) -> None:
    """Regresion de `Task/009` y `Task/011`.

    Detecta el otro error caro y simetrico: proteger `/api/v1` entero por
    comodidad y convertir en privados los diez endpoints publicos.
    """
    for ruta, operaciones in documento["paths"].items():
        if ruta.startswith("/api/v1/admin"):
            continue
        for metodo, operacion in operaciones.items():
            assert "security" not in operacion, f"{metodo.upper()} {ruta} exige autenticacion"


def test_la_api_publica_sigue_siendo_de_solo_lectura(documento: dict[str, Any]) -> None:
    """Regla 1 de USER_FLOWS.md: ningun flujo publico escribe datos."""
    for ruta, operaciones in documento["paths"].items():
        if ruta.startswith("/api/v1/admin"):
            continue
        metodos = {metodo.lower() for metodo in operaciones}
        assert metodos == {"get"}, f"{ruta} declara metodos distintos de GET: {sorted(metodos)}"


# --- O-04: el conjunto exacto de rutas -------------------------------------
def test_la_especificacion_declara_exactamente_las_rutas_del_contrato(
    documento: dict[str, Any],
) -> None:
    """Las 11 publicas, las 3 de acceso y las 23 administrativas."""
    assert set(documento["paths"]) == (
        RUTAS_PUBLICAS | RUTAS_DE_AUTENTICACION | RUTAS_ADMINISTRATIVAS
    )


def test_el_contrato_publico_de_task_009_no_cambia(documento: dict[str, Any]) -> None:
    """Regresion: `Task/012` no toca ninguna ruta publica."""
    publicas = {ruta for ruta in documento["paths"] if not ruta.startswith("/api/v1/admin")}

    assert publicas == RUTAS_PUBLICAS


# --- Las transiciones que no existen, no se declaran -----------------------
@pytest.mark.parametrize(
    "ruta",
    [
        "/api/v1/admin/videos/{video_id}/unpublish",
        "/api/v1/admin/projects/{project_id}/unpublish",
    ],
)
def test_no_se_declara_la_despublicacion_donde_no_existe(
    documento: dict[str, Any], ruta: str
) -> None:
    """`MVP_SCOPE.md` 3.2: `published -> draft` es de articulos y reviews.

    `Task/008` lo expreso por **ausencia del metodo** en el dominio. Aqui se
    expresa por ausencia de la ruta, de modo que la especificacion tampoco la
    anuncia.
    """
    assert ruta not in documento["paths"]


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/v1/admin/posts/{post_id}",
        "/api/v1/admin/book-reviews/{review_id}",
        "/api/v1/admin/videos/{video_id}",
        "/api/v1/admin/projects/{project_id}",
    ],
)
def test_el_contenido_no_se_elimina(documento: dict[str, Any], ruta: str) -> None:
    """Decision **D-012-D**: `MVP_SCOPE.md` 3.1 no concede *eliminar* al contenido."""
    assert "delete" not in documento["paths"][ruta]


def test_el_perfil_no_se_crea_ni_se_elimina(documento: dict[str, Any]) -> None:
    """Decision **D-012-U**, tomada de `data-model.md` seccion 5."""
    metodos = set(documento["paths"]["/api/v1/admin/profile"])

    assert metodos == {"get", "put"}


def test_no_se_expone_ninguna_ruta_de_auditoria(documento: dict[str, Any]) -> None:
    """Invariante 8 de CONTENT_MODEL.md: un `AuditEvent` no se edita ni se borra.

    Ninguna fuente pide exponer el historial por API en el MVP, y desde luego
    ninguna pide poder modificarlo. Que no exista la ruta es la garantia mas
    barata de que no se puede llamar.
    """
    for ruta in documento["paths"]:
        assert "audit" not in ruta, f"{ruta} expone la auditoria"


# --- Ningun esquema administrativo filtra campos internos ------------------
@pytest.mark.parametrize(
    "esquema",
    [
        "PerfilAdministrativo",
        "ArticuloAdministrativo",
        "ReviewAdministrativa",
        "VideoAdministrativo",
        "ProyectoAdministrativo",
        "EtiquetaAdministrativa",
        "MedioAdministrativo",
    ],
)
def test_ningun_esquema_administrativo_declara_campos_internos(
    documento: dict[str, Any], esquema: str
) -> None:
    """El administrador ve mas que el visitante, pero no lo que es interno.

    `id`, `status` y las fechas de gestion **si** salen aqui, y cada uno tiene su
    justificacion. Lo que no sale en ningun caso es el cerrojo del *singleton*,
    las claves foraneas y la clave del objeto en el almacenamiento.
    """
    internos = {
        "is_singleton",
        "cover_id",
        "photo_id",
        "thumbnail_id",
        "object_key",
        "password_hash",
        "token_hash",
        "failed_login_attempts",
        "locked_until",
    }
    propiedades = set(documento["components"]["schemas"][esquema]["properties"])

    filtrados = propiedades & internos
    assert not filtrados, f"{esquema} declara campos internos: {sorted(filtrados)}"


def test_el_esquema_administrativo_de_medio_no_menciona_la_infraestructura(
    documento: dict[str, Any],
) -> None:
    """Ni bucket, ni region, ni proveedor: son datos de infraestructura."""
    esquema = json.dumps(documento["components"]["schemas"]["MedioAdministrativo"]).lower()

    for prohibido in ("bucket", "object_key", "region", "aws", "minio", "s3storage"):
        assert prohibido not in esquema


# --- El estado no es un campo escribible -----------------------------------
@pytest.mark.parametrize(
    "esquema",
    [
        "ArticuloParaGuardar",
        "ReviewParaGuardar",
        "VideoParaGuardar",
        "ProyectoParaGuardar",
    ],
)
def test_el_cuerpo_de_escritura_no_admite_el_estado_de_publicacion(
    documento: dict[str, Any], esquema: str
) -> None:
    """Decision **D-012-A**: el ciclo de vida vive en los subrecursos.

    Si `status` o `published_at` fueran escribibles habria **dos** caminos para
    publicar, y el del `PUT` se saltaria la validacion de campos minimos.
    """
    propiedades = set(documento["components"]["schemas"][esquema]["properties"])

    assert "status" not in propiedades
    assert "published_at" not in propiedades


def test_el_video_no_declara_contenido_markdown(documento: dict[str, Any]) -> None:
    """CONTENT_MODEL.md seccion 2 y ADR-005 decision 7."""
    for esquema in ("VideoParaGuardar", "VideoAdministrativo"):
        assert "content" not in documento["components"]["schemas"][esquema]["properties"]


def test_el_slug_de_una_etiqueta_no_es_editable(documento: dict[str, Any]) -> None:
    """Decision **D-012-S**: aparece en las URL de filtro publicas (A.9)."""
    assert "slug" not in documento["components"]["schemas"]["EtiquetaParaRenombrar"]["properties"]
    assert "slug" in documento["components"]["schemas"]["EtiquetaParaCrear"]["properties"]


# --- El filtro `status` es administrativo, y solo administrativo -----------
def test_solo_los_listados_administrativos_declaran_el_filtro_de_estado(
    documento: dict[str, Any],
) -> None:
    """`api-contracts.md` seccion 6: `status` es *"solo administrativo"*."""
    con_status: set[str] = set()
    for ruta, operaciones in documento["paths"].items():
        for operacion in operaciones.values():
            nombres = {parametro["name"] for parametro in operacion.get("parameters", [])}
            if "status" in nombres:
                con_status.add(ruta)

    assert con_status == {
        "/api/v1/admin/posts",
        "/api/v1/admin/book-reviews",
        "/api/v1/admin/videos",
        "/api/v1/admin/projects",
    }


# --- El contrato de error tambien se documenta -----------------------------
@pytest.mark.parametrize(
    ("ruta", "metodo"),
    [
        ("/api/v1/admin/posts", "post"),
        ("/api/v1/admin/posts/{post_id}/publish", "post"),
        ("/api/v1/admin/media", "post"),
        ("/api/v1/admin/tags", "post"),
    ],
)
def test_los_endpoints_administrativos_documentan_la_envoltura_de_error(
    documento: dict[str, Any], ruta: str, metodo: str
) -> None:
    """Sin esto, la especificacion describiria la forma por defecto de FastAPI."""
    referencia = documento["paths"][ruta][metodo]["responses"]["422"]["content"][
        "application/json"
    ]["schema"]["$ref"]

    assert referencia.endswith("/RespuestaDeError")


def test_la_paginacion_administrativa_es_la_del_proyecto(documento: dict[str, Any]) -> None:
    """Decision **D-012-K**: una sola envoltura para toda la API."""
    for ruta in (
        "/api/v1/admin/posts",
        "/api/v1/admin/book-reviews",
        "/api/v1/admin/videos",
        "/api/v1/admin/projects",
        "/api/v1/admin/tags",
        "/api/v1/admin/media",
    ):
        referencia = documento["paths"][ruta]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        esquema = documento["components"]["schemas"][referencia.rsplit("/", 1)[-1]]

        assert set(esquema["properties"]) == {"items", "page", "page_size", "total", "pages"}
