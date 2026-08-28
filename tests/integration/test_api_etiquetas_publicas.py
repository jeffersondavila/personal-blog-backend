"""Remediacion test-first del slice Tags."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.posts.domain import PostStatus
from app.modules.projects.domain import ProjectStatus
from app.modules.videos.domain import VideoStatus
from tests.integration.datos import articulo, etiqueta, proyecto, review, video

pytestmark = pytest.mark.integration

RUTA = "/api/v1/tags"


def _slugs(respuesta: Any) -> list[str]:
    return [item["slug"] for item in respuesta.json()["items"]]


def test_tag_de_cada_tipo_publicado_es_visible_con_campos_exactos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    tags = [
        etiqueta("post", nombre="Post", descripcion="Por post"),
        etiqueta("review", nombre="Review"),
        etiqueta("video", nombre="Video"),
        etiqueta("project", nombre="Project"),
    ]
    sesion_de_pruebas.add_all(
        [
            articulo("a", etiquetas=[tags[0]]),
            review("r", etiquetas=[tags[1]]),
            video("v", etiquetas=[tags[2]]),
            proyecto("p", etiquetas=[tags[3]]),
        ]
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(RUTA)

    assert respuesta.status_code == 200
    assert set(_slugs(respuesta)) == {"post", "review", "video", "project"}
    assert all(set(item) == {"slug", "name", "description"} for item in respuesta.json()["items"])


def test_tag_huerfano_no_aparece_con_control_de_tag_usado(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    usado = etiqueta("usado")
    sesion_de_pruebas.add_all([etiqueta("huerfano"), articulo("publico", etiquetas=[usado])])
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(RUTA)) == ["usado"]


@pytest.mark.parametrize("estado", [PostStatus.DRAFT, PostStatus.ARCHIVED])
def test_tag_solo_en_post_oculto_no_aparece_con_control_publicado(
    sesion_de_pruebas: Session,
    cliente_de_la_api: TestClient,
    estado: PostStatus,
) -> None:
    visible = etiqueta("visible")
    secreto = etiqueta("secreto")
    sesion_de_pruebas.add_all(
        [
            articulo("publico", etiquetas=[visible]),
            articulo("oculto", estado=estado, etiquetas=[secreto]),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(RUTA)) == ["visible"]


def test_las_cuatro_ramas_excluyen_tags_de_contenido_no_publicado(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    control = etiqueta("control")
    tags_ocultos = [
        etiqueta("post-oculto"),
        etiqueta("review-oculta"),
        etiqueta("video-oculto"),
        etiqueta("project-oculto"),
    ]
    sesion_de_pruebas.add_all(
        [
            articulo("publico", etiquetas=[control]),
            articulo("a", estado=PostStatus.DRAFT, etiquetas=[tags_ocultos[0]]),
            review("r", estado=BookReviewStatus.DRAFT, etiquetas=[tags_ocultos[1]]),
            video("v", estado=VideoStatus.ARCHIVED, etiquetas=[tags_ocultos[2]]),
            proyecto("p", estado=ProjectStatus.ARCHIVED, etiquetas=[tags_ocultos[3]]),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(RUTA)) == ["control"]


def test_tag_compartido_por_publicado_y_draft_aparece_una_vez(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    compartido = etiqueta("compartido")
    sesion_de_pruebas.add_all(
        [
            articulo("publico", etiquetas=[compartido]),
            articulo("borrador", estado=PostStatus.DRAFT, etiquetas=[compartido]),
            review("otra", etiquetas=[compartido]),
        ]
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(RUTA)
    assert _slugs(respuesta) == ["compartido"]
    assert respuesta.json()["total"] == 1


def test_tags_se_paginan_sobre_el_conjunto_disponible(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    for indice in range(3):
        sesion_de_pruebas.add(articulo(f"a-{indice}", etiquetas=[etiqueta(f"tag-{indice}")]))
    sesion_de_pruebas.flush()

    primera = cliente_de_la_api.get(RUTA, params={"page": 1, "page_size": 2}).json()
    segunda = cliente_de_la_api.get(RUTA, params={"page": 2, "page_size": 2}).json()
    assert (primera["total"], primera["pages"], len(primera["items"])) == (3, 2, 2)
    assert len(segunda["items"]) == 1
