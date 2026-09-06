"""Remediacion test-first del slice Projects."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.projects.domain import ProjectStatus, ProjectWorkStatus
from tests.integration.datos import ANTIGUO, RECIENTE, etiqueta, medio, proyecto

pytestmark = pytest.mark.integration

RUTA = "/api/v1/projects"


def _slugs(respuesta: Any) -> list[str]:
    return [item["slug"] for item in respuesta.json()["items"]]


def _error_comparable(respuesta: Any) -> dict[str, Any]:
    error = dict(respuesta.json()["error"])
    error.pop("request_id")
    return error


def test_listado_publica_solo_projects_visibles_con_sus_campos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    visible = proyecto(
        "visible",
        marcha=ProjectWorkStatus.PAUSED,
        tecnologias=["Python", "PostgreSQL"],
        repositorio="https://example.invalid/repo",
        demo="https://example.invalid/demo",
    )
    visible.cover = medio(
        clave="privado/project.png",
        texto_alternativo="Portada",
        ancho=1200,
        alto=630,
    )
    sesion_de_pruebas.add_all(
        [
            visible,
            proyecto("borrador", estado=ProjectStatus.DRAFT),
            proyecto("archivado", estado=ProjectStatus.ARCHIVED),
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
        "technologies",
        "repository_url",
        "demo_url",
        "project_status",
    }
    assert item["technologies"] == ["Python", "PostgreSQL"]
    assert item["project_status"] == "paused"
    # `access_url` se anade en `Task/010` (D-009-O, cerrada). El enlace lleva
    # firma y marca de tiempo, asi que no puede compararse literal: se comprueba
    # su presencia y se mantiene cerrado el conjunto de campos.
    medio_publico = item["cover"]
    sin_el_enlace = {
        c: v
        for c, v in medio_publico.items()
        # Dos enlaces firmados desde `Task/016`: el del original y el de la
        # miniatura (requisito P-04). Ninguno es un dato estable del contrato.
        if c not in {"access_url", "thumbnail_access_url"}
    }
    assert sin_el_enlace == {"alt_text": "Portada", "width": 1200, "height": 630}
    assert medio_publico["access_url"].startswith("http")
    assert "object_key" not in item["cover"]


def test_projects_se_paginan_sin_repetir_elementos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [proyecto(f"p-{indice}", publicado_el=RECIENTE) for indice in range(5)]
    )
    sesion_de_pruebas.flush()

    paginas = [
        cliente_de_la_api.get(RUTA, params={"page": pagina, "page_size": 2}).json()
        for pagina in (1, 2, 3)
    ]
    assert (paginas[0]["total"], paginas[0]["pages"]) == (5, 3)
    slugs = [item["slug"] for pagina in paginas for item in pagina["items"]]
    assert len(slugs) == len(set(slugs)) == 5


def test_filtros_tag_y_featured_excluyen_projects_ocultos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    comun = etiqueta("backend")
    sesion_de_pruebas.add_all(
        [
            proyecto("destacado", destacado=True, etiquetas=[comun]),
            proyecto("normal", etiquetas=[comun]),
            proyecto("oculto", estado=ProjectStatus.DRAFT, destacado=True, etiquetas=[comun]),
            proyecto("sin-tag", destacado=True),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(RUTA, params={"tag": "backend"})) == [
        "destacado",
        "normal",
    ]
    assert _slugs(cliente_de_la_api.get(RUTA, params={"tag": "backend", "featured": "true"})) == [
        "destacado"
    ]
    assert _slugs(cliente_de_la_api.get(RUTA, params={"tag": "backend", "featured": "false"})) == [
        "normal"
    ]


def test_sort_ordena_fecha_y_titulo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            proyecto("viejo", titulo="Zulu", publicado_el=ANTIGUO),
            proyecto("nuevo", titulo="Alpha", publicado_el=RECIENTE),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(RUTA)) == ["nuevo", "viejo"]
    assert _slugs(cliente_de_la_api.get(RUTA, params={"sort": "title"})) == [
        "nuevo",
        "viejo",
    ]
    assert _slugs(cliente_de_la_api.get(RUTA, params={"sort": "-title"})) == [
        "viejo",
        "nuevo",
    ]


def test_detalle_publicado_conserva_markdown_y_datos_del_proyecto(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    creado = proyecto(
        "detalle",
        contenido="# Proyecto\n\n" + "palabra " * 201,
        marcha=ProjectWorkStatus.COMPLETED,
        tecnologias=["Rust"],
        repositorio="https://example.invalid/repo",
        demo="https://example.invalid/demo",
    )
    creado.seo_title = "Proyecto"
    creado.seo_description = "Descripcion"
    sesion_de_pruebas.add(creado)
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(f"{RUTA}/detalle")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["content"].startswith("# Proyecto\n\n")
    assert cuerpo["reading_time_minutes"] == 2
    assert cuerpo["project_status"] == "completed"
    assert cuerpo["technologies"] == ["Rust"]
    assert cuerpo["repository_url"] == "https://example.invalid/repo"
    assert cuerpo["demo_url"] == "https://example.invalid/demo"


@pytest.mark.parametrize("estado", [ProjectStatus.DRAFT, ProjectStatus.ARCHIVED])
def test_project_oculto_es_el_mismo_404_que_un_slug_inexistente(
    sesion_de_pruebas: Session,
    cliente_de_la_api: TestClient,
    estado: ProjectStatus,
) -> None:
    sesion_de_pruebas.add_all([proyecto("publico"), proyecto("secreto", estado=estado)])
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(f"{RUTA}/publico").status_code == 200
    oculto = cliente_de_la_api.get(f"{RUTA}/secreto")
    inexistente = cliente_de_la_api.get(f"{RUTA}/no-existe")
    assert oculto.status_code == inexistente.status_code == 404
    assert _error_comparable(oculto) == _error_comparable(inexistente)
