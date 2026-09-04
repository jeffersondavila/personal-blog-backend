"""Reviews administrativas contra PostgreSQL real (matriz BR de `Task/012`).

Se concentra en lo que **distingue** a una review de un articulo; lo comun
—proteccion, paginacion, slug, parametros desconocidos— ya esta fijado en
`test_api_admin_articulos.py` y en la prueba transversal de OpenAPI, y repetirlo
aqui seria pagar tiempo de suite por la misma garantia.

Lo propio de una review, con su fuente:

- `book_title`, `book_author` y `rating` **obligatorios al publicar**
  (CONTENT_MODEL.md 3.3, `data-model.md` D-D, USER_FLOWS.md A.4 y A.5).
- `rating` dentro de la escala **1..5**, que garantizan el dominio y el `CHECK`.
- `external_link` **opcional**, tambien al publicar.
- **Si** admite `unpublish`: `MVP_SCOPE.md` 3.2 concede `published -> draft` a
  articulos y reviews.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import ENTIDAD_REVIEW, AccionAuditada
from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.book_reviews.infrastructure.models import BookReview
from tests.integration.administracion import (
    ADMIN,
    administrador_con_sesion,
    codigo_de_error,
    eventos_de,
)
from tests.integration.datos import review

pytestmark = pytest.mark.integration

REVIEWS = f"{ADMIN}/book-reviews"


def _completa(**cambios: Any) -> dict[str, Any]:
    valores: dict[str, Any] = {
        "title": "Una review",
        "summary": "Un resumen breve.",
        "content": "# Cuerpo",
        "book_title": "El libro",
        "book_author": "La autora",
        "rating": 4,
    }
    valores.update(cambios)
    return valores


def _crear(cliente: TestClient, **cambios: Any) -> dict[str, Any]:
    respuesta = cliente.post(REVIEWS, json=_completa(**cambios))
    assert respuesta.status_code == 201, respuesta.text
    cuerpo: dict[str, Any] = respuesta.json()
    return cuerpo


def test_sin_sesion_no_se_listan_las_reviews(cliente_administrativo: TestClient) -> None:
    assert cliente_administrativo.get(REVIEWS).status_code == 401


# --- BR-01: crear un borrador incompleto es legitimo -----------------------
def test_una_review_nace_como_borrador_y_admite_datos_incompletos(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`data-model.md` 4.6: libro, autor y valoracion son nulos en un borrador."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(REVIEWS, json={"title": "Solo el titulo"})

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "draft"
    assert cuerpo["book_title"] is None
    assert cuerpo["book_author"] is None
    assert cuerpo["rating"] is None


def test_los_campos_del_libro_se_administran(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo, external_link="https://libro.invalid")

    assert cuerpo["book_title"] == "El libro"
    assert cuerpo["book_author"] == "La autora"
    assert cuerpo["rating"] == 4
    assert cuerpo["external_link"] == "https://libro.invalid"


# --- BR-02: la escala de valoracion ---------------------------------------
@pytest.mark.parametrize("valoracion", [1, 2, 3, 4, 5])
def test_la_escala_admite_de_uno_a_cinco(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, valoracion: int
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo, slug=f"review-{valoracion}", rating=valoracion)

    assert cuerpo["rating"] == valoracion


@pytest.mark.parametrize("valoracion", [0, 6, -1, 100])
def test_una_valoracion_fuera_de_la_escala_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, valoracion: int
) -> None:
    """Escala **1..5** (decision D-D). El rechazo ocurre antes de tocar la base."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(REVIEWS, json=_completa(rating=valoracion))

    assert respuesta.status_code == 422
    assert sesion_de_pruebas.execute(select(func.count()).select_from(BookReview)).scalar_one() == 0


# --- BR-03: validacion de publicacion propia ------------------------------
@pytest.mark.parametrize(
    ("campo", "faltante"),
    [
        ("book_title", "book_title"),
        ("book_author", "book_author"),
        ("rating", "rating"),
        ("content", "content"),
    ],
)
def test_no_se_puede_publicar_una_review_incompleta(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, campo: str, faltante: str
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo, **{campo: None if campo != "content" else ""})

    respuesta = cliente_administrativo.post(f"{REVIEWS}/{creada['id']}/publish")

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "cannot_publish_incomplete_draft"
    assert faltante in respuesta.json()["error"]["details"]["campos"]


def test_el_enlace_externo_no_impide_publicar(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """CONTENT_MODEL.md 3.3 lo llama *"enlace opcional"*; A.5, *"si existe"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo, external_link=None)

    respuesta = cliente_administrativo.post(f"{REVIEWS}/{creada['id']}/publish")

    assert respuesta.status_code == 200


def test_una_review_completa_se_publica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.post(f"{REVIEWS}/{creada['id']}/publish")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "published"
    assert respuesta.json()["published_at"] is not None


# --- BR-04: la review si se despublica ------------------------------------
def test_una_review_publicada_se_despublica_conservando_la_fecha(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`MVP_SCOPE.md` 3.2 concede `published -> draft` a articulos **y reviews**."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)
    publicada = cliente_administrativo.post(f"{REVIEWS}/{creada['id']}/publish").json()

    respuesta = cliente_administrativo.post(f"{REVIEWS}/{creada['id']}/unpublish")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "draft"
    assert respuesta.json()["published_at"] == publicada["published_at"]


def test_una_review_se_archiva(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.post(f"{REVIEWS}/{creada['id']}/archive")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "archived"


def test_publicar_una_review_ya_publicada_es_conflicto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{REVIEWS}/{creada['id']}/publish")

    respuesta = cliente_administrativo.post(f"{REVIEWS}/{creada['id']}/publish")

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "invalid_book_review_state"


def test_no_existe_forma_de_eliminar_una_review(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    assert cliente_administrativo.delete(f"{REVIEWS}/{creada['id']}").status_code == 405


# --- BR-05: listado y edicion ---------------------------------------------
def test_el_listado_administrativo_incluye_los_tres_estados(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add_all(
        [
            review("borrador", estado=BookReviewStatus.DRAFT),
            review("publicada", estado=BookReviewStatus.PUBLISHED),
            review("archivada", estado=BookReviewStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.get(REVIEWS)

    assert respuesta.json()["total"] == 3


def test_una_review_se_edita(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.put(
        f"{REVIEWS}/{creada['id']}",
        json=_completa(slug=creada["slug"], book_title="Otro libro", rating=5),
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["book_title"] == "Otro libro"
    assert respuesta.json()["rating"] == 5


def test_un_slug_duplicado_de_review_produce_conflicto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(review("una-review"))
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.post(REVIEWS, json=_completa())

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "slug_already_exists"


def test_una_review_desconocida_responde_404(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert cliente_administrativo.get(f"{REVIEWS}/{uuid.uuid4()}").status_code == 404


# --- BR-06: auditoria y vista publica --------------------------------------
def test_la_auditoria_de_una_review_apunta_a_su_tipo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-N**: la accion es `content.*` y el tipo lo dice `entity_type`."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    creada = _crear(cliente_administrativo)

    evento = eventos_de(sesion_de_pruebas, AccionAuditada.CONTENIDO_CREADO.value)[0]
    assert evento.entity_type == ENTIDAD_REVIEW
    assert evento.entity_id == uuid.UUID(creada["id"])


def test_publicar_una_review_la_hace_visible_en_la_api_publica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    cliente_administrativo.post(f"{REVIEWS}/{creada['id']}/publish")

    publico = cliente_administrativo.get(f"/api/v1/book-reviews/{creada['slug']}")
    assert publico.status_code == 200
    assert publico.json()["rating"] == 4
