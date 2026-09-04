"""Articulos administrativos contra PostgreSQL real (matriz PO de `Task/012`).

Cubre los flujos B.2, B.3, B.7, B.8 y B.9 de USER_FLOWS.md sobre `/admin/posts`,
que es el tipo mas completo: es el unico junto a `BookReview` que admite las
**cinco** transiciones del ciclo de vida.

Contra PostgreSQL real y no contra un doble porque lo que se comprueba aqui
existe **en la base**: la unicidad de `slug`, el `CHECK` que exige fecha al
publicar, las claves foraneas `RESTRICT` de los medios, las tablas puente M:N y
la atomicidad de la operacion completa.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import ENTIDAD_ARTICULO, AccionAuditada
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import Post
from app.modules.tags.infrastructure.models import post_tags
from tests.integration.administracion import (
    ADMIN,
    administrador_con_sesion,
    codigo_de_error,
    eventos_de,
)
from tests.integration.datos import ANTIGUO, INTERMEDIO, RECIENTE, articulo, etiqueta, medio

pytestmark = pytest.mark.integration

ARTICULOS = f"{ADMIN}/posts"


def _completo(**cambios: Any) -> dict[str, Any]:
    """Cuerpo con todo lo que hace publicable a un articulo (ficha 7.0.3)."""
    valores: dict[str, Any] = {
        "title": "Docker en produccion",
        "summary": "Un resumen breve.",
        "content": "# Cuerpo\n\nMarkdown.",
    }
    valores.update(cambios)
    return valores


def _crear(cliente: TestClient, **cambios: Any) -> dict[str, Any]:
    respuesta = cliente.post(ARTICULOS, json=_completo(**cambios))
    assert respuesta.status_code == 201, respuesta.text
    cuerpo: dict[str, Any] = respuesta.json()
    return cuerpo


# --- A-01: proteccion ------------------------------------------------------
@pytest.mark.parametrize(
    ("metodo", "sufijo"),
    [
        ("get", ""),
        ("post", ""),
        ("get", "/00000000-0000-0000-0000-000000000000"),
        ("put", "/00000000-0000-0000-0000-000000000000"),
        ("post", "/00000000-0000-0000-0000-000000000000/publish"),
        ("post", "/00000000-0000-0000-0000-000000000000/unpublish"),
        ("post", "/00000000-0000-0000-0000-000000000000/archive"),
    ],
)
def test_sin_sesion_ningun_endpoint_de_articulos_responde(
    cliente_administrativo: TestClient, metodo: str, sufijo: str
) -> None:
    respuesta = cliente_administrativo.request(metodo, f"{ARTICULOS}{sufijo}", json={})

    assert respuesta.status_code == 401
    assert codigo_de_error(respuesta) == "unauthenticated"


# --- PO-01: crear un borrador ----------------------------------------------
def test_un_articulo_nace_como_borrador_sin_fecha(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.2: *"El contenido nace en estado `draft`"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo)

    assert cuerpo["status"] == "draft"
    assert cuerpo["published_at"] is None
    assert cuerpo["featured"] is False
    guardado = sesion_de_pruebas.execute(select(Post)).scalar_one()
    assert guardado.status is PostStatus.DRAFT


def test_solo_el_titulo_es_obligatorio_al_crear(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.2 y `data-model.md` 4.4.1: un borrador puede nacer incompleto."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(ARTICULOS, json={"title": "Solo el titulo"})

    assert respuesta.status_code == 201
    assert respuesta.json()["content"] == ""
    assert respuesta.json()["summary"] is None


def test_crear_sin_titulo_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(ARTICULOS, json={"title": "   "})

    assert respuesta.status_code == 422


def test_el_estado_no_es_un_campo_escribible(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-A**: el ciclo de vida vive en subrecursos, no en `PUT`.

    Aceptar `status` en el cuerpo daria **dos** caminos para publicar, y uno de
    ellos —el del `PUT`— se saltaria la validacion de campos minimos.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(ARTICULOS, json=_completo(status="published"))

    assert respuesta.status_code == 422


# --- PO-02: el slug se propone ---------------------------------------------
def test_sin_slug_se_deriva_del_titulo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.2: *"el slug se propone automaticamente"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo, title="Docker en Producción")

    assert cuerpo["slug"] == "docker-en-produccion"


def test_con_slug_explicito_se_respeta(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.2: *"y es editable"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo, slug="otro-slug")

    assert cuerpo["slug"] == "otro-slug"


def test_un_slug_mal_formado_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(ARTICULOS, json=_completo(slug="Mal Slug!"))

    assert respuesta.status_code == 422
    assert codigo_de_error(respuesta) == "invalid_slug"


# --- PO-03: slug duplicado -------------------------------------------------
def test_un_slug_duplicado_produce_conflicto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`api-contracts.md` seccion 8: `409` es el conflicto de estado."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(articulo("docker-en-produccion"))
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.post(ARTICULOS, json=_completo())

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "slug_already_exists"


def test_el_conflicto_de_slug_no_deja_ningun_articulo_a_medias(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(articulo("docker-en-produccion"))
    sesion_de_pruebas.flush()

    cliente_administrativo.post(ARTICULOS, json=_completo())

    total = sesion_de_pruebas.execute(select(func.count()).select_from(Post)).scalar_one()
    assert total == 1


# --- PO-04: editar ---------------------------------------------------------
def test_un_articulo_se_edita(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}",
        json=_completo(title="Otro titulo", slug=creado["slug"], content="Nuevo cuerpo"),
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["title"] == "Otro titulo"
    assert respuesta.json()["content"] == "Nuevo cuerpo"


def test_editar_un_publicado_no_lo_despublica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.3: *"editar un contenido `published`… no lo despublica implicitamente"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    respuesta = cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}", json=_completo(slug=creado["slug"], title="Editado")
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "published"
    assert respuesta.json()["published_at"] is not None


def test_editar_un_articulo_inexistente_responde_404(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.put(f"{ARTICULOS}/{uuid.uuid4()}", json=_completo())

    assert respuesta.status_code == 404


# --- PO-05 y PO-06: estabilidad del slug -----------------------------------
def test_el_slug_de_un_borrador_nunca_publicado_se_puede_cambiar(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`api-contracts.md` seccion 4: *"el slug puede cambiar mientras se edita un borrador"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}", json=_completo(slug="slug-nuevo")
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["slug"] == "slug-nuevo"


def test_el_slug_deja_de_cambiarse_tras_la_primera_publicacion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-F**: la frontera es haber sido publico alguna vez.

    Invariante 4 de CONTENT_MODEL.md: los slugs son *"estables: cambiarlos rompe
    URLs y SEO"*. Un borrador despublicado ya tuvo URL indexada, y
    `published_at` es precisamente la marca de que la tuvo.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/unpublish")

    respuesta = cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}", json=_completo(slug="slug-nuevo")
    )

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "slug_is_immutable"


def test_reenviar_el_mismo_slug_de_un_publicado_no_es_conflicto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Lo prohibido es **cambiarlo**, no volver a enviarlo: `PUT` es completo."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    respuesta = cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}", json=_completo(slug=creado["slug"], title="Editado")
    )

    assert respuesta.status_code == 200


def test_editar_hacia_un_slug_ocupado_produce_conflicto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(articulo("ocupado"))
    sesion_de_pruebas.flush()
    creado = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}", json=_completo(slug="ocupado")
    )

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "slug_already_exists"


# --- PO-07, PO-08, PO-09: listado administrativo ---------------------------
def test_el_listado_administrativo_incluye_los_tres_estados(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Es la diferencia con el listado publico, que solo muestra publicados."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add_all(
        [
            articulo("borrador", estado=PostStatus.DRAFT),
            articulo("publicado", estado=PostStatus.PUBLISHED),
            articulo("archivado", estado=PostStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.get(ARTICULOS)

    assert respuesta.status_code == 200
    assert respuesta.json()["total"] == 3
    estados = {elemento["status"] for elemento in respuesta.json()["items"]}
    assert estados == {"draft", "published", "archived"}


def test_el_listado_administrativo_filtra_por_estado(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`api-contracts.md` seccion 6: `status` es *"solo administrativo"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add_all(
        [
            articulo("borrador", estado=PostStatus.DRAFT),
            articulo("publicado", estado=PostStatus.PUBLISHED),
        ]
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.get(ARTICULOS, params={"status": "draft"})

    assert respuesta.json()["total"] == 1
    assert respuesta.json()["items"][0]["slug"] == "borrador"


def test_un_estado_inventado_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.get(ARTICULOS, params={"status": "inventado"})

    assert respuesta.status_code == 422


def test_un_parametro_desconocido_se_rechaza_tambien_en_el_panel(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision D-009-C, aplicada tambien aqui."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.get(ARTICULOS, params={"inventado": "1"})

    assert respuesta.status_code == 422


def test_el_listado_administrativo_va_del_mas_modificado_al_menos(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-L**: el panel ordena por fecha de **modificacion**.

    El orden publico no sirve aqui: un borrador no tiene `published_at` y todos
    quedarian agrupados en un extremo. MVP_SCOPE.md 3.3 describe el panel por
    *"ultimos elementos modificados"*.

    Las fechas se fijan a mano y no se obtienen editando en cadena: `updated_at`
    lo pone `now()` de PostgreSQL, que es la hora de **inicio de la
    transaccion** (decision D-H), asi que todo lo que la prueba escriba
    compartiria marca y el resultado lo decidiria el desempate.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    for slug, momento in (("antiguo", ANTIGUO), ("reciente", RECIENTE), ("medio", INTERMEDIO)):
        fila = articulo(slug, estado=PostStatus.DRAFT)
        fila.updated_at = momento
        sesion_de_pruebas.add(fila)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.get(ARTICULOS)

    assert [item["slug"] for item in respuesta.json()["items"]] == [
        "reciente",
        "medio",
        "antiguo",
    ]


def test_el_listado_administrativo_esta_paginado(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-K**: la misma envoltura que la API publica."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add_all([articulo(f"articulo-{numero}") for numero in range(5)])
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.get(ARTICULOS, params={"page": 1, "page_size": 2})

    cuerpo = respuesta.json()
    assert set(cuerpo) == {"items", "page", "page_size", "total", "pages"}
    assert cuerpo["total"] == 5
    assert cuerpo["pages"] == 3
    assert len(cuerpo["items"]) == 2


# --- PO-10: detalle --------------------------------------------------------
def test_el_detalle_administrativo_muestra_un_borrador(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.get(f"{ARTICULOS}/{creado['id']}")

    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == creado["id"]


def test_un_identificador_desconocido_responde_404(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.get(f"{ARTICULOS}/{uuid.uuid4()}")

    assert respuesta.status_code == 404


def test_un_identificador_malformado_responde_422(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.get(f"{ARTICULOS}/no-es-un-uuid")

    assert respuesta.status_code == 422


# --- PO-11 a PO-14: publicar ----------------------------------------------
def test_publicar_un_borrador_completo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.7: pasa a `published` y se fija `published_at`."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "published"
    assert respuesta.json()["published_at"] is not None


def test_no_se_puede_publicar_sin_contenido(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Invariante 18 de `data-model.md`, implementada aqui."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, content="")

    respuesta = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "cannot_publish_incomplete_draft"
    assert respuesta.json()["error"]["details"]["campos"] == ["content"]


def test_no_se_puede_publicar_sin_descripcion_resoluble(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.7, *"y SEO si corresponde"*: `seo_description` cae en `summary`."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, summary=None)

    respuesta = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["details"]["campos"] == ["summary"]


def test_un_borrador_rechazado_sigue_siendo_borrador(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, content="")

    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    guardado = sesion_de_pruebas.execute(select(Post)).scalar_one()
    assert guardado.status is PostStatus.DRAFT
    assert guardado.published_at is None


def test_publicar_algo_ya_publicado_es_conflicto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-B**: lo decidio el dominio de `Task/008`, no esta tarea."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    respuesta = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "invalid_post_state"


# --- PO-15 y PO-16: despublicar y republicar -------------------------------
def test_despublicar_devuelve_a_borrador_conservando_la_fecha(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.8: *"Se conserva `published_at` como referencia historica"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    publicado = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish").json()

    respuesta = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/unpublish")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "draft"
    assert respuesta.json()["published_at"] == publicado["published_at"]


def test_republicar_no_reescribe_la_fecha_de_la_primera_publicacion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`data-model.md` seccion 7: *"es la fecha de la primera publicacion"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    primera = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish").json()
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/unpublish")

    segunda = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish").json()

    assert segunda["published_at"] == primera["published_at"]


def test_despublicar_un_borrador_es_conflicto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/unpublish")

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "invalid_post_state"


# --- PO-17 y PO-18: archivar ----------------------------------------------
def test_archivar_retira_sin_eliminar(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.9: *"Desaparece del sitio publico pero **no se elimina**"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    respuesta = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/archive")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "archived"
    assert respuesta.json()["published_at"] is not None
    assert sesion_de_pruebas.execute(select(func.count()).select_from(Post)).scalar_one() == 1


def test_un_borrador_tambien_se_puede_archivar(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`data-model.md` seccion 7: `archived` se alcanza desde cualquier estado vivo."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/archive")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "archived"


def test_archivar_dos_veces_es_conflicto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/archive")

    respuesta = cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/archive")

    assert respuesta.status_code == 409


def test_no_existe_ninguna_forma_de_eliminar_un_articulo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-D**: `MVP_SCOPE.md` 3.1 no concede *eliminar* al contenido."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.delete(f"{ARTICULOS}/{creado['id']}")

    assert respuesta.status_code == 405


# --- PO-19 a PO-22: etiquetas y portada -----------------------------------
def test_las_etiquetas_se_asocian_al_crear(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    docker = etiqueta("docker")
    linux = etiqueta("linux")
    sesion_de_pruebas.add_all([docker, linux])
    sesion_de_pruebas.flush()

    cuerpo = _crear(cliente_administrativo, tag_ids=[str(docker.id), str(linux.id)])

    assert {item["slug"] for item in cuerpo["tags"]} == {"docker", "linux"}
    asociaciones = sesion_de_pruebas.execute(
        select(func.count()).select_from(post_tags)
    ).scalar_one()
    assert asociaciones == 2


def test_editar_reemplaza_el_conjunto_de_etiquetas(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    docker = etiqueta("docker")
    linux = etiqueta("linux")
    sesion_de_pruebas.add_all([docker, linux])
    sesion_de_pruebas.flush()
    creado = _crear(cliente_administrativo, tag_ids=[str(docker.id)])

    respuesta = cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}",
        json=_completo(slug=creado["slug"], tag_ids=[str(linux.id)]),
    )

    assert [item["slug"] for item in respuesta.json()["tags"]] == ["linux"]
    asociaciones = sesion_de_pruebas.execute(
        select(func.count()).select_from(post_tags)
    ).scalar_one()
    assert asociaciones == 1


def test_una_etiqueta_desconocida_se_rechaza_y_no_crea_nada(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-J**, y la atomicidad que exige el alcance (seccion 29)."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    inventada = str(uuid.uuid4())

    respuesta = cliente_administrativo.post(ARTICULOS, json=_completo(tag_ids=[inventada]))

    assert respuesta.status_code == 422
    assert codigo_de_error(respuesta) == "unknown_reference"
    assert respuesta.json()["error"]["details"]["valores"] == [inventada]
    assert sesion_de_pruebas.execute(select(func.count()).select_from(Post)).scalar_one() == 0


def test_una_portada_desconocida_se_rechaza_y_no_crea_nada(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(ARTICULOS, json=_completo(cover_id=str(uuid.uuid4())))

    assert respuesta.status_code == 422
    assert codigo_de_error(respuesta) == "unknown_reference"
    assert sesion_de_pruebas.execute(select(func.count()).select_from(Post)).scalar_one() == 0


def test_una_portada_conocida_se_asocia_y_devuelve_su_enlace(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave="medios/portada/original.png", texto_alternativo="Portada")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    cuerpo = _crear(cliente_administrativo, cover_id=str(imagen.id))

    assert cuerpo["cover"]["id"] == str(imagen.id)
    assert cuerpo["cover"]["access_url"].startswith("http")
    assert "object_key" not in cuerpo["cover"]


def test_la_portada_se_puede_retirar(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`PUT` es una representacion completa (D-012-C): omitirla la retira."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave="medios/portada/original.png")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()
    creado = _crear(cliente_administrativo, cover_id=str(imagen.id))

    respuesta = cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}", json=_completo(slug=creado["slug"])
    )

    assert respuesta.json()["cover"] is None


# --- PO-25: no se filtra nada interno --------------------------------------
def test_la_respuesta_administrativa_no_expone_claves_internas(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    cuerpo = _crear(cliente_administrativo)

    for interno in ("cover_id", "object_key", "password_hash", "is_singleton"):
        assert interno not in cuerpo


def test_el_destacado_se_administra(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, featured=True)

    assert creado["featured"] is True

    respuesta = cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}", json=_completo(slug=creado["slug"], featured=False)
    )
    assert respuesta.json()["featured"] is False


# --- AU: auditoria ---------------------------------------------------------
def test_cada_operacion_deja_su_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    actor = administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    identificador = uuid.UUID(creado["id"])
    cliente_administrativo.put(
        f"{ARTICULOS}/{creado['id']}", json=_completo(slug=creado["slug"], title="Editado")
    )
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/unpublish")
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/archive")

    for accion in (
        AccionAuditada.CONTENIDO_CREADO,
        AccionAuditada.CONTENIDO_ACTUALIZADO,
        AccionAuditada.CONTENIDO_PUBLICADO,
        AccionAuditada.CONTENIDO_DESPUBLICADO,
        AccionAuditada.CONTENIDO_ARCHIVADO,
    ):
        eventos = eventos_de(sesion_de_pruebas, accion.value)
        assert len(eventos) == 1, accion
        assert eventos[0].entity_type == ENTIDAD_ARTICULO
        assert eventos[0].entity_id == identificador
        assert eventos[0].actor_id == actor.id
        assert eventos[0].request_id is not None
        assert eventos[0].ip_address is not None


def test_la_transicion_registra_los_dos_estados(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-O**: metadatos utiles y minimos."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    evento = eventos_de(sesion_de_pruebas, AccionAuditada.CONTENIDO_PUBLICADO.value)[0]
    assert evento.event_metadata == {"estado_anterior": "draft", "estado_nuevo": "published"}


def test_la_auditoria_no_guarda_el_markdown(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    _crear(cliente_administrativo, content="SECRETO EN EL MARKDOWN")

    evento = eventos_de(sesion_de_pruebas, AccionAuditada.CONTENIDO_CREADO.value)[0]
    assert "SECRETO" not in str(evento.event_metadata)
    assert evento.event_metadata == {"slug": "docker-en-produccion"}


def test_una_operacion_rechazada_no_deja_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, content="")

    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    assert eventos_de(sesion_de_pruebas, AccionAuditada.CONTENIDO_PUBLICADO.value) == []


# --- RG: la API publica sigue diciendo la verdad ---------------------------
def test_publicar_hace_visible_el_articulo_en_la_api_publica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    assert cliente_administrativo.get(f"/api/v1/posts/{creado['slug']}").status_code == 404

    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    publico = cliente_administrativo.get(f"/api/v1/posts/{creado['slug']}")
    assert publico.status_code == 200
    assert publico.json()["title"] == "Docker en produccion"


@pytest.mark.parametrize("transicion", ["unpublish", "archive"])
def test_retirar_el_articulo_lo_devuelve_a_404_en_la_api_publica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, transicion: str
) -> None:
    """Invariantes 2 y 3 de CONTENT_MODEL.md, comprobadas de extremo a extremo."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/publish")

    cliente_administrativo.post(f"{ARTICULOS}/{creado['id']}/{transicion}")

    publico = cliente_administrativo.get(f"/api/v1/posts/{creado['slug']}")
    assert publico.status_code == 404
    assert codigo_de_error(publico) == "resource_not_found"
