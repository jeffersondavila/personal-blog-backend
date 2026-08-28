"""API publica de reviews de libros y de proyectos (matriz D y F).

Los dos recursos comparten forma con los articulos —listado paginado, detalle
por slug, filtros y la misma regla de visibilidad—, asi que aqui no se repite lo
que ya demuestra `test_api_articulos.py`: se comprueba que **esa** regla se
cumple tambien en estas tablas, y se prueban los campos que son propios de cada
tipo.

La visibilidad se repite deliberadamente por tipo, y no se da por buena por
analogia: cada tipo tiene su propia consulta (decision D-009-R), asi que un
olvido en una de ellas no lo detectaria ninguna prueba de las otras.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.projects.domain import ProjectStatus, ProjectWorkStatus
from tests.integration.datos import (
    ANTIGUO,
    RECIENTE,
    etiqueta,
    proyecto,
    review,
)

pytestmark = pytest.mark.integration

REVIEWS = "/api/v1/book-reviews"
PROYECTOS = "/api/v1/projects"


def _slugs(respuesta: Any) -> list[str]:
    cuerpo: dict[str, Any] = respuesta.json()
    return [elemento["slug"] for elemento in cuerpo["items"]]


def _error_comparable(respuesta: Any) -> dict[str, Any]:
    error = dict(respuesta.json()["error"])
    error.pop("request_id")
    return error


# --- D: reviews de libros --------------------------------------------------
def test_el_listado_de_reviews_solo_devuelve_publicadas(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            review("publicada", estado=BookReviewStatus.PUBLISHED),
            review("borrador", estado=BookReviewStatus.DRAFT),
            review("archivada", estado=BookReviewStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(REVIEWS)) == ["publicada"]


def test_el_listado_de_reviews_lleva_libro_autor_y_valoracion(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """USER_FLOWS.md A.4: el listado muestra ademas autor del libro y valoracion."""
    sesion_de_pruebas.add(
        review(
            "una",
            titulo="Mi review",
            titulo_del_libro="El libro",
            autor_del_libro="Una Autora",
            valoracion=4,
            enlace_externo="https://ejemplo.invalid/libro",
        )
    )
    sesion_de_pruebas.flush()

    elemento: dict[str, Any] = cliente_de_la_api.get(REVIEWS).json()["items"][0]

    assert elemento["title"] == "Mi review"
    assert elemento["book_title"] == "El libro"
    assert elemento["book_author"] == "Una Autora"
    assert elemento["rating"] == 4
    # El enlace externo es una accion del detalle, no informacion de tarjeta.
    assert "external_link" not in elemento


def test_una_review_sin_valoracion_es_valida(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """`rating` admite nulo: exigirlo para publicar es validacion de `Task/012`."""
    sesion_de_pruebas.add(review("sin-nota", valoracion=None))
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(REVIEWS).json()["items"][0]["rating"] is None


def test_el_detalle_de_una_review_publicada_incluye_libro_y_enlace(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(
        review(
            "publicada",
            contenido="Cuerpo de la review.",
            titulo_del_libro="El libro",
            autor_del_libro="Una Autora",
            valoracion=5,
            enlace_externo="https://ejemplo.invalid/libro",
        )
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(f"{REVIEWS}/publicada")

    assert respuesta.status_code == 200
    cuerpo: dict[str, Any] = respuesta.json()
    assert cuerpo["book_title"] == "El libro"
    assert cuerpo["rating"] == 5
    assert cuerpo["external_link"] == "https://ejemplo.invalid/libro"
    assert cuerpo["content"] == "Cuerpo de la review."


@pytest.mark.parametrize("estado", [BookReviewStatus.DRAFT, BookReviewStatus.ARCHIVED])
def test_una_review_no_publicada_es_indistinguible_de_una_inexistente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, estado: BookReviewStatus
) -> None:
    sesion_de_pruebas.add(review("secreta", estado=estado))
    sesion_de_pruebas.flush()

    oculta = cliente_de_la_api.get(f"{REVIEWS}/secreta")
    inexistente = cliente_de_la_api.get(f"{REVIEWS}/jamas-existio")

    assert oculta.status_code == inexistente.status_code == 404
    assert _error_comparable(oculta) == _error_comparable(inexistente)


def test_el_filtro_por_etiqueta_de_reviews_no_saca_borradores(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    compartida = etiqueta("compartida")
    sesion_de_pruebas.add_all(
        [
            review("visible", etiquetas=[compartida], estado=BookReviewStatus.PUBLISHED),
            review("oculta", etiquetas=[compartida], estado=BookReviewStatus.DRAFT),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(REVIEWS, params={"tag": "compartida"})) == ["visible"]


def test_las_reviews_se_ordenan_por_fecha_descendente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [review("vieja", publicado_el=ANTIGUO), review("nueva", publicado_el=RECIENTE)]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(REVIEWS)) == ["nueva", "vieja"]


# --- F: proyectos ----------------------------------------------------------
def test_el_listado_de_proyectos_solo_devuelve_publicados(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            proyecto("publicado", estado=ProjectStatus.PUBLISHED),
            proyecto("borrador", estado=ProjectStatus.DRAFT),
            proyecto("archivado", estado=ProjectStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(PROYECTOS)) == ["publicado"]


def test_el_listado_de_proyectos_lleva_tecnologias_y_enlaces(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """USER_FLOWS.md A.7: titulo, resumen, tecnologias y enlaces."""
    sesion_de_pruebas.add(
        proyecto(
            "uno",
            resumen="Un experimento",
            tecnologias=["Python", "PostgreSQL"],
            repositorio="https://ejemplo.invalid/repo",
            demo="https://ejemplo.invalid/demo",
        )
    )
    sesion_de_pruebas.flush()

    elemento: dict[str, Any] = cliente_de_la_api.get(PROYECTOS).json()["items"][0]

    assert elemento["summary"] == "Un experimento"
    # El orden de la lista se conserva: es una lista, no un conjunto.
    assert elemento["technologies"] == ["Python", "PostgreSQL"]
    assert elemento["repository_url"] == "https://ejemplo.invalid/repo"
    assert elemento["demo_url"] == "https://ejemplo.invalid/demo"


@pytest.mark.parametrize(
    "marcha", [ProjectWorkStatus.ACTIVE, ProjectWorkStatus.PAUSED, ProjectWorkStatus.COMPLETED]
)
def test_la_marcha_del_trabajo_no_afecta_a_la_visibilidad(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, marcha: ProjectWorkStatus
) -> None:
    """CONTENT_MODEL.md seccion 3.5: `status` y `project_status` son ortogonales.

    Un proyecto **terminado** publicado sigue siendo publico. Confundir las dos
    columnas haria desaparecer del sitio los proyectos acabados, que suelen ser
    justo los que mas interesa enseñar.
    """
    sesion_de_pruebas.add(proyecto("uno", marcha=marcha, estado=ProjectStatus.PUBLISHED))
    sesion_de_pruebas.flush()

    elemento: dict[str, Any] = cliente_de_la_api.get(PROYECTOS).json()["items"][0]

    assert elemento["project_status"] == marcha.value


def test_un_proyecto_sin_tecnologias_devuelve_una_lista_vacia(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(proyecto("pelado"))
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(PROYECTOS).json()["items"][0]["technologies"] == []


def test_el_detalle_de_un_proyecto_publicado_incluye_el_cuerpo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(
        proyecto("publicado", contenido="# Proyecto\n\nDescripcion larga.", tecnologias=["Rust"])
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(f"{PROYECTOS}/publicado")

    assert respuesta.status_code == 200
    cuerpo: dict[str, Any] = respuesta.json()
    assert cuerpo["content"] == "# Proyecto\n\nDescripcion larga."
    assert cuerpo["technologies"] == ["Rust"]
    assert cuerpo["reading_time_minutes"] == 1


@pytest.mark.parametrize("estado", [ProjectStatus.DRAFT, ProjectStatus.ARCHIVED])
def test_un_proyecto_no_publicado_es_indistinguible_de_uno_inexistente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, estado: ProjectStatus
) -> None:
    sesion_de_pruebas.add(proyecto("secreto", estado=estado))
    sesion_de_pruebas.flush()

    oculto = cliente_de_la_api.get(f"{PROYECTOS}/secreto")
    inexistente = cliente_de_la_api.get(f"{PROYECTOS}/jamas-existio")

    assert oculto.status_code == inexistente.status_code == 404
    assert _error_comparable(oculto) == _error_comparable(inexistente)


def test_los_listados_de_reviews_y_proyectos_no_exponen_campos_internos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all([review("una"), proyecto("uno")])
    sesion_de_pruebas.flush()

    for ruta in (REVIEWS, PROYECTOS):
        elemento: dict[str, Any] = cliente_de_la_api.get(ruta).json()["items"][0]
        for interno in ("id", "status", "created_at", "updated_at", "cover_id", "featured"):
            assert interno not in elemento, f"{ruta} expone {interno!r}"


# --- Filtros comunes en los tipos restantes --------------------------------
#
# Los cuatro tipos tienen su **propia** consulta (decision D-009-R), asi que el
# filtro de destacados y el de etiqueta hay que ejercitarlos tipo por tipo: que
# funcionen en articulos no dice nada de si funcionan aqui. La deteccion vino de
# la cobertura, que mostraba estas ramas sin recorrer.
@pytest.mark.parametrize(("valor", "esperado"), [("true", ["destacada"]), ("false", ["normal"])])
def test_el_filtro_de_destacados_funciona_en_reviews(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, valor: str, esperado: list[str]
) -> None:
    sesion_de_pruebas.add_all(
        [review("destacada", destacado=True), review("normal", destacado=False)]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(REVIEWS, params={"featured": valor})) == esperado


@pytest.mark.parametrize(("valor", "esperado"), [("true", ["destacado"]), ("false", ["normal"])])
def test_el_filtro_de_destacados_funciona_en_proyectos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, valor: str, esperado: list[str]
) -> None:
    sesion_de_pruebas.add_all(
        [proyecto("destacado", destacado=True), proyecto("normal", destacado=False)]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(PROYECTOS, params={"featured": valor})) == esperado


def test_el_filtro_por_etiqueta_de_proyectos_no_saca_borradores(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    compartida = etiqueta("compartida")
    sesion_de_pruebas.add_all(
        [
            proyecto("visible", etiquetas=[compartida], estado=ProjectStatus.PUBLISHED),
            proyecto("oculto", etiquetas=[compartida], estado=ProjectStatus.DRAFT),
            proyecto("sin-etiqueta", estado=ProjectStatus.PUBLISHED),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(PROYECTOS, params={"tag": "compartida"})) == ["visible"]
