"""Remediacion test-first del slice BookReviews."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from tests.integration.datos import ANTIGUO, INTERMEDIO, RECIENTE, etiqueta, review

pytestmark = pytest.mark.integration

RUTA = "/api/v1/book-reviews"


def _slugs(respuesta: Any) -> list[str]:
    return [item["slug"] for item in respuesta.json()["items"]]


def _error_comparable(respuesta: Any) -> dict[str, Any]:
    error = dict(respuesta.json()["error"])
    error.pop("request_id")
    return error


def test_listado_solo_publica_reviews_y_expone_campos_del_libro(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            review(
                "visible",
                titulo="Una review",
                resumen="Resumen",
                titulo_del_libro="El libro",
                autor_del_libro="La autora",
                valoracion=5,
            ),
            review("borrador", estado=BookReviewStatus.DRAFT),
            review("archivada", estado=BookReviewStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(RUTA)

    assert respuesta.status_code == 200
    assert _slugs(respuesta) == ["visible"]
    item = respuesta.json()["items"][0]
    assert set(item) == {
        "slug",
        "title",
        "summary",
        "published_at",
        "tags",
        "cover",
        "book_title",
        "book_author",
        "rating",
    }
    assert (item["book_title"], item["book_author"], item["rating"]) == (
        "El libro",
        "La autora",
        5,
    )


def test_paginacion_cuenta_el_conjunto_completo_sin_repetir(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all([review(f"r-{indice}", publicado_el=RECIENTE) for indice in range(5)])
    sesion_de_pruebas.flush()

    primera = cliente_de_la_api.get(RUTA, params={"page": 1, "page_size": 2}).json()
    segunda = cliente_de_la_api.get(RUTA, params={"page": 2, "page_size": 2}).json()
    tercera = cliente_de_la_api.get(RUTA, params={"page": 3, "page_size": 2}).json()

    assert (primera["total"], primera["pages"], primera["page_size"]) == (5, 3, 2)
    slugs = [item["slug"] for pagina in (primera, segunda, tercera) for item in pagina["items"]]
    assert len(slugs) == len(set(slugs)) == 5


def test_orden_por_fecha_y_sort_por_titulo_son_deterministas(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            review("medio", titulo="Beta", publicado_el=INTERMEDIO),
            review("viejo", titulo="Gamma", publicado_el=ANTIGUO),
            review("nuevo", titulo="Alpha", publicado_el=RECIENTE),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(RUTA)) == ["nuevo", "medio", "viejo"]
    assert _slugs(cliente_de_la_api.get(RUTA, params={"sort": "title"})) == [
        "nuevo",
        "medio",
        "viejo",
    ]
    assert _slugs(cliente_de_la_api.get(RUTA, params={"sort": "-title"})) == [
        "viejo",
        "medio",
        "nuevo",
    ]


def test_filtros_tag_y_featured_no_sacan_contenido_oculto(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    comun = etiqueta("arquitectura")
    sesion_de_pruebas.add_all(
        [
            review("destacada", destacado=True, etiquetas=[comun]),
            review("normal", destacado=False, etiquetas=[comun]),
            review("oculta", estado=BookReviewStatus.DRAFT, destacado=True, etiquetas=[comun]),
            review("sin-tag", destacado=True),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(RUTA, params={"tag": "arquitectura"})) == [
        "destacada",
        "normal",
    ]
    assert _slugs(
        cliente_de_la_api.get(RUTA, params={"tag": "arquitectura", "featured": "true"})
    ) == ["destacada"]
    assert _slugs(
        cliente_de_la_api.get(RUTA, params={"tag": "arquitectura", "featured": "false"})
    ) == ["normal"]


def test_detalle_publicado_incluye_markdown_libro_enlace_y_tiempo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    creada = review(
        "detalle",
        contenido="palabra " * 201,
        titulo_del_libro="Domain-Driven Design",
        autor_del_libro="Eric Evans",
        valoracion=4,
        enlace_externo="https://example.invalid/book",
    )
    creada.seo_title = "Review DDD"
    creada.seo_description = "Reseña"
    sesion_de_pruebas.add(creada)
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(f"{RUTA}/detalle")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["content"] == "palabra " * 201
    assert cuerpo["reading_time_minutes"] == 2
    assert cuerpo["external_link"] == "https://example.invalid/book"
    assert cuerpo["book_title"] == "Domain-Driven Design"
    assert "id" not in cuerpo and "status" not in cuerpo


@pytest.mark.parametrize("estado", [BookReviewStatus.DRAFT, BookReviewStatus.ARCHIVED])
def test_review_oculta_es_indistinguible_de_inexistente_con_control_publicado(
    sesion_de_pruebas: Session,
    cliente_de_la_api: TestClient,
    estado: BookReviewStatus,
) -> None:
    sesion_de_pruebas.add_all([review("publica"), review("secreta", estado=estado)])
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(f"{RUTA}/publica").status_code == 200
    oculta = cliente_de_la_api.get(f"{RUTA}/secreta")
    inexistente = cliente_de_la_api.get(f"{RUTA}/no-existe")
    assert oculta.status_code == inexistente.status_code == 404
    assert _error_comparable(oculta) == _error_comparable(inexistente)
