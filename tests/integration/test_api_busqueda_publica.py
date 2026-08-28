"""Remediacion test-first del slice Search."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.posts.domain import PostStatus
from app.modules.projects.domain import ProjectStatus
from app.modules.videos.domain import VideoStatus
from tests.integration.datos import (
    ANTIGUO,
    INTERMEDIO,
    RECIENTE,
    articulo,
    proyecto,
    review,
    video,
)

pytestmark = pytest.mark.integration

RUTA = "/api/v1/search"


def _resultados(respuesta: Any) -> list[tuple[str, str]]:
    return [(item["type"], item["slug"]) for item in respuesta.json()["items"]]


def test_q_encuentra_subcadena_publicada_sin_distinguir_mayusculas(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("docker", titulo="Guia de Docker"),
            articulo("otro", titulo="Sin coincidencia"),
        ]
    )
    sesion_de_pruebas.flush()

    for termino in ("docker", "DOCKER", "ocke"):
        assert _resultados(cliente_de_la_api.get(RUTA, params={"q": termino})) == [
            ("post", "docker")
        ]


@pytest.mark.parametrize("estado", [PostStatus.DRAFT, PostStatus.ARCHIVED])
def test_coincidencia_oculta_no_aparece_con_control_publicado(
    sesion_de_pruebas: Session,
    cliente_de_la_api: TestClient,
    estado: PostStatus,
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("publico", titulo="Termino control"),
            articulo("secreto", titulo="Termino secreto", estado=estado),
        ]
    )
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(RUTA, params={"q": "control"})) == [
        ("post", "publico")
    ]
    assert cliente_de_la_api.get(RUTA, params={"q": "secreto"}).json()["items"] == []


def test_las_cuatro_ramas_excluyen_contenido_no_publicado(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("control", titulo="Publico unico"),
            articulo("a", titulo="Secreto comun", estado=PostStatus.DRAFT),
            review("r", titulo="Secreto comun", estado=BookReviewStatus.DRAFT),
            video("v", titulo="Secreto comun", estado=VideoStatus.ARCHIVED),
            proyecto("p", titulo="Secreto comun", estado=ProjectStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(RUTA, params={"q": "publico unico"})) == [
        ("post", "control")
    ]
    assert cliente_de_la_api.get(RUTA, params={"q": "secreto comun"}).json()["items"] == []


def test_resultados_de_los_cuatro_tipos_llevan_discriminador_y_campos_exactos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("a", titulo="Comun", publicado_el=RECIENTE),
            review("r", titulo="Comun", publicado_el=RECIENTE),
            video("v", titulo="Comun", publicado_el=RECIENTE),
            proyecto("p", titulo="Comun", publicado_el=RECIENTE),
        ]
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(RUTA, params={"q": "comun"})
    assert _resultados(respuesta) == [
        ("book_review", "r"),
        ("post", "a"),
        ("project", "p"),
        ("video", "v"),
    ]
    assert all(
        set(item) == {"type", "slug", "title", "summary", "published_at"}
        for item in respuesta.json()["items"]
    )


def test_busca_resumen_y_datos_del_libro_pero_no_markdown(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("resumen", titulo="Sin pista", resumen="Habla de Kubernetes"),
            articulo("markdown", titulo="Nada", resumen="Nada", contenido="Kubernetes"),
            review(
                "libro",
                titulo="Otra cosa",
                titulo_del_libro="Clean Architecture",
                autor_del_libro="Robert Martin",
            ),
        ]
    )
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(RUTA, params={"q": "kubernetes"})) == [
        ("post", "resumen")
    ]
    assert _resultados(cliente_de_la_api.get(RUTA, params={"q": "architecture"})) == [
        ("book_review", "libro")
    ]
    assert _resultados(cliente_de_la_api.get(RUTA, params={"q": "martin"})) == [
        ("book_review", "libro")
    ]


def test_busqueda_se_pagina_y_ordena_establemente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("nuevo", titulo="Comun", publicado_el=RECIENTE),
            video("medio", titulo="Comun", publicado_el=INTERMEDIO),
            proyecto("viejo", titulo="Comun", publicado_el=ANTIGUO),
            review("a", titulo="Comun", publicado_el=RECIENTE),
            articulo("b", titulo="Comun", publicado_el=RECIENTE),
        ]
    )
    sesion_de_pruebas.flush()

    primera = cliente_de_la_api.get(RUTA, params={"q": "comun", "page_size": 2}).json()
    segunda = cliente_de_la_api.get(RUTA, params={"q": "comun", "page": 2, "page_size": 2}).json()
    tercera = cliente_de_la_api.get(RUTA, params={"q": "comun", "page": 3, "page_size": 2}).json()
    assert (primera["total"], primera["pages"]) == (5, 3)
    combinados = [
        item["slug"] for pagina in (primera, segunda, tercera) for item in pagina["items"]
    ]
    assert len(combinados) == len(set(combinados)) == 5
    assert combinados[:3] == ["a", "b", "nuevo"]


@pytest.mark.parametrize(("termino", "titulo"), [("%z", "Analiza"), ("_n", "Analiza")])
def test_comodines_like_se_tratan_como_texto_literal(
    sesion_de_pruebas: Session,
    cliente_de_la_api: TestClient,
    termino: str,
    titulo: str,
) -> None:
    sesion_de_pruebas.add(articulo("analizado", titulo=titulo))
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(RUTA, params={"q": termino}).json()["items"] == []


def test_porcentaje_literal_real_si_se_encuentra(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(articulo("descuento", titulo="Descuento del 50%"))
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(RUTA, params={"q": "50%"})) == [("post", "descuento")]


def test_q_se_recorta_y_texto_de_inyeccion_no_altera_la_consulta(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(articulo("docker", titulo="Docker"))
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(RUTA, params={"q": "  docker  "})) == [
        ("post", "docker")
    ]
    respuesta = cliente_de_la_api.get(RUTA, params={"q": "' OR 1=1 --"})
    assert respuesta.status_code == 200
    assert respuesta.json()["items"] == []


def test_q_invalido_es_422_y_cero_resultados_es_coleccion_vacia(
    cliente_de_la_api: TestClient,
) -> None:
    assert cliente_de_la_api.get(RUTA).status_code == 422
    assert cliente_de_la_api.get(RUTA, params={"q": "a"}).status_code == 422
    vacio = cliente_de_la_api.get(RUTA, params={"q": "inexistente"})
    assert vacio.status_code == 200
    assert vacio.json()["items"] == []
    assert (vacio.json()["total"], vacio.json()["pages"]) == (0, 0)
