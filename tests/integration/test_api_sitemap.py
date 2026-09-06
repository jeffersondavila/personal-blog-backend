"""`GET /sitemap.xml` contra PostgreSQL real (`Task/016`, requisitos E-05 y E-08).

Por que aqui y no en `tests/unit/`
-----------------------------------

**E-08** dice que *el contenido no publicado **nunca** aparece en el sitemap*, y
es la misma **invariante 19** de `data-model.md` que `Task/009` defendio para los
listados publicos. Lo que la garantiza es el `WHERE status = 'published'` que
ejecuta PostgreSQL. Un doble en memoria demostraria que el codigo de prueba
filtra, no que la consulta lo haga
(BACKEND_TESTING_STRATEGY.md seccion 8.3, y criterio **B-6** de la
Definition of Done).

La construccion del XML —pura— se prueba aparte en
`tests/unit/test_documento_de_sitemap.py`.

Casos cubiertos aqui: **S-02** a **S-07**, **S-09**, **S-10** y **S-12**.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.posts.domain import PostStatus
from app.modules.projects.domain import ProjectStatus
from app.modules.videos.domain import VideoStatus
from tests.integration.datos import articulo, proyecto, review, video

pytestmark = pytest.mark.integration

SITEMAP = "/sitemap.xml"
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _urls(respuesta: Any) -> list[str]:
    raiz = ElementTree.fromstring(respuesta.text)  # noqa: S314 - XML generado por este mismo proyecto, no entrada de terceros
    return [nodo.text or "" for nodo in raiz.iterfind(f"{{{NS}}}url/{{{NS}}}loc")]


def _rutas(respuesta: Any) -> list[str]:
    """Rutas sin el origen, para comparar sin depender del host configurado."""
    urls = _urls(respuesta)
    return [url.split("://", 1)[1].split("/", 1)[1] for url in urls]


# --- S-01: base vacia -------------------------------------------------------
def test_sin_contenido_publicado_responde_200_con_las_rutas_estaticas(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    respuesta = cliente_de_la_api.get(SITEMAP)

    assert respuesta.status_code == 200
    assert len(_urls(respuesta)) == 7


# --- S-07: tipo de contenido ------------------------------------------------
def test_el_tipo_de_contenido_es_xml(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    respuesta = cliente_de_la_api.get(SITEMAP)

    assert respuesta.headers["content-type"].startswith("application/xml")


# --- S-02: contenido publicado aparece --------------------------------------
def test_un_articulo_publicado_aparece_con_su_lastmod(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(
        articulo(
            "hola-mundo",
            estado=PostStatus.PUBLISHED,
            publicado_el=datetime(2026, 3, 14, 15, 9, 26, tzinfo=UTC),
        )
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(SITEMAP)

    assert "articulos/hola-mundo" in _rutas(respuesta)
    assert "2026-03-14" in respuesta.text


# --- S-03 y S-04: E-08, lo no publicado NUNCA aparece -----------------------
@pytest.mark.parametrize(
    ("estado", "nombre"),
    [(PostStatus.DRAFT, "borrador"), (PostStatus.ARCHIVED, "archivado")],
)
def test_un_articulo_no_publicado_no_aparece(
    sesion_de_pruebas: Session,
    cliente_de_la_api: TestClient,
    estado: PostStatus,
    nombre: str,
) -> None:
    sesion_de_pruebas.add(articulo(f"secreto-{nombre}", estado=estado))
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(SITEMAP)

    assert f"secreto-{nombre}" not in respuesta.text


def test_e08_en_los_tres_tipos_con_detalle_a_la_vez(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """El filtro debe existir en las tres ramas, no solo en la primera."""
    sesion_de_pruebas.add_all(
        [
            articulo("art-visible", estado=PostStatus.PUBLISHED),
            articulo("art-oculto", estado=PostStatus.DRAFT),
            review("rev-visible", estado=BookReviewStatus.PUBLISHED),
            review("rev-oculta", estado=BookReviewStatus.ARCHIVED),
            proyecto("pro-visible", estado=ProjectStatus.PUBLISHED),
            proyecto("pro-oculto", estado=ProjectStatus.DRAFT),
        ]
    )
    sesion_de_pruebas.flush()

    cuerpo = cliente_de_la_api.get(SITEMAP).text

    for visible in ("art-visible", "rev-visible", "pro-visible"):
        assert visible in cuerpo
    for oculto in ("art-oculto", "rev-oculta", "pro-oculto"):
        assert oculto not in cuerpo


# --- S-05: los tres tipos con detalle, con su prefijo correcto --------------
def test_cada_tipo_usa_el_prefijo_de_ruta_de_su_seccion(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("uno", estado=PostStatus.PUBLISHED),
            review("dos", estado=BookReviewStatus.PUBLISHED),
            proyecto("tres", estado=ProjectStatus.PUBLISHED),
        ]
    )
    sesion_de_pruebas.flush()

    rutas = _rutas(cliente_de_la_api.get(SITEMAP))

    assert "articulos/uno" in rutas
    assert "reviews/dos" in rutas
    assert "proyectos/tres" in rutas


# --- S-06: los videos no tienen detalle -------------------------------------
def test_un_video_publicado_no_genera_ruta_de_detalle(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """No existe `GET /videos/{slug}` en el contrato, asi que tampoco en el sitemap."""
    sesion_de_pruebas.add(video("intro-docker", estado=VideoStatus.PUBLISHED))
    sesion_de_pruebas.flush()

    rutas = _rutas(cliente_de_la_api.get(SITEMAP))

    assert "videos" in rutas
    assert "videos/intro-docker" not in rutas
    assert "intro-docker" not in cliente_de_la_api.get(SITEMAP).text


# --- S-09: URL del sitio, no del API ----------------------------------------
def test_las_urls_son_absolutas_y_del_origen_del_sitio(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(articulo("hola", estado=PostStatus.PUBLISHED))
    sesion_de_pruebas.flush()

    for url in _urls(cliente_de_la_api.get(SITEMAP)):
        assert url.startswith("http://") or url.startswith("https://")
    assert "/api/v1" not in cliente_de_la_api.get(SITEMAP).text


# --- S-10: exclusiones ------------------------------------------------------
@pytest.mark.parametrize("prohibido", ["/buscar", "/admin", "/api/v1"])
def test_no_aparecen_rutas_excluidas(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, prohibido: str
) -> None:
    sesion_de_pruebas.add(articulo("hola", estado=PostStatus.PUBLISHED))
    sesion_de_pruebas.flush()

    assert prohibido not in cliente_de_la_api.get(SITEMAP).text


# --- S-12: anti-tautologia --------------------------------------------------
def test_anti_tautologia_el_sitemap_si_enumera_contenido(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Sin esta prueba, S-03 y S-04 pasarian con un sitemap que no enumera nada.

    Una ausencia total satisface *"el borrador no aparece"* de la peor manera
    posible. Aqui se fija que el documento **si** crece con contenido publicado,
    de modo que las pruebas de E-08 esten observando un filtro y no un vacio.

    Es el mismo criterio con el que `Task/015` diseno la comprobacion P-05-3.
    """
    antes = len(_urls(cliente_de_la_api.get(SITEMAP)))

    sesion_de_pruebas.add_all(
        [
            articulo("a", estado=PostStatus.PUBLISHED),
            review("b", estado=BookReviewStatus.PUBLISHED),
            proyecto("c", estado=ProjectStatus.PUBLISHED),
        ]
    )
    sesion_de_pruebas.flush()

    despues = len(_urls(cliente_de_la_api.get(SITEMAP)))

    assert despues == antes + 3
