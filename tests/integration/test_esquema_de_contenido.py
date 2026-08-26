"""Restricciones del esquema de contenido, contra PostgreSQL real (matriz C).

Estas garantias **no se pueden demostrar sin el motor**: dependen de indices
unicos, de *check constraints*, del tipo `TIMESTAMP WITH TIME ZONE` y de cuando
PostgreSQL evalua una comparacion con `NULL`. Sustituir el motor por otro
probaria el comportamiento de ese otro motor
(BACKEND_TESTING_STRATEGY.md seccion 8.3).

Cada prueba escribe dentro de una transaccion que se revierte al terminar
(`sesion_de_pruebas`), asi que ninguna deja filas para la siguiente ni necesita
limpiar lo que creo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import Post
from app.modules.projects.domain import ProjectStatus, ProjectWorkStatus
from app.modules.projects.infrastructure.models import Project
from app.modules.videos.domain import VideoStatus
from app.modules.videos.infrastructure.models import Video

pytestmark = pytest.mark.integration

UN_INSTANTE = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)


def _articulo(slug: str, **campos: object) -> Post:
    valores: dict[str, object] = {"slug": slug, "title": f"Articulo {slug}"}
    valores.update(campos)
    return Post(**valores)


def _review(slug: str, **campos: object) -> BookReview:
    valores: dict[str, object] = {
        "slug": slug,
        "title": f"Review {slug}",
        "book_title": "Un libro de prueba",
        "book_author": "Autora de prueba",
    }
    valores.update(campos)
    return BookReview(**valores)


def _video(slug: str, **campos: object) -> Video:
    valores: dict[str, object] = {
        "slug": slug,
        "title": f"Video {slug}",
        "provider": "proveedor-de-prueba",
        "video_url": "https://ejemplo.invalid/video",
    }
    valores.update(campos)
    return Video(**valores)


def _proyecto(slug: str, **campos: object) -> Project:
    valores: dict[str, object] = {"slug": slug, "title": f"Proyecto {slug}"}
    valores.update(campos)
    return Project(**valores)


# --- C-01 ------------------------------------------------------------------
def test_dos_articulos_no_pueden_compartir_slug(sesion_de_pruebas: Session) -> None:
    sesion_de_pruebas.add(_articulo("mismo-slug"))
    sesion_de_pruebas.flush()

    sesion_de_pruebas.add(_articulo("mismo-slug"))

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- C-02 ------------------------------------------------------------------
def test_dos_tipos_distintos_si_pueden_compartir_slug(sesion_de_pruebas: Session) -> None:
    """Los *slug* son unicos **por tipo**, no globalmente.

    `/articulos/docker` y `/videos/docker` son dos URL distintas y legitimas
    (CONTENT_MODEL.md, invariante 4). Una unicidad global las prohibiria sin que
    ningun requisito lo pida.
    """
    sesion_de_pruebas.add(_articulo("docker"))
    sesion_de_pruebas.add(_video("docker"))
    sesion_de_pruebas.add(_review("docker"))
    sesion_de_pruebas.add(_proyecto("docker"))

    sesion_de_pruebas.flush()  # no debe lanzar


# --- C-03 ------------------------------------------------------------------
def test_un_estado_fuera_del_contrato_se_rechaza(sesion_de_pruebas: Session) -> None:
    """`draft`, `published` y `archived` son un contrato cerrado.

    Se escribe por SQL directo a proposito: el ORM ni siquiera dejaria construir
    el valor, y lo que se comprueba aqui es que **la base** lo rechaza.
    """
    with pytest.raises(IntegrityError):
        sesion_de_pruebas.execute(
            text(
                "INSERT INTO posts (id, slug, title, content, status, featured,"
                " created_at, updated_at)"
                " VALUES (gen_random_uuid(), 'estado-raro', 'T', '', 'borrador', false,"
                " now(), now())"
            )
        )


# --- C-04 ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("constructor", "estado"),
    [
        (_articulo, PostStatus.PUBLISHED),
        (_review, BookReviewStatus.PUBLISHED),
        (_video, VideoStatus.PUBLISHED),
        (_proyecto, ProjectStatus.PUBLISHED),
    ],
    ids=["articulo", "review", "video", "proyecto"],
)
def test_publicado_sin_fecha_se_rechaza(
    sesion_de_pruebas: Session, constructor: object, estado: object
) -> None:
    """Invariante 1 de CONTENT_MODEL.md, en los cuatro tipos publicables."""
    sesion_de_pruebas.add(constructor("sin-fecha", status=estado, published_at=None))  # type: ignore[operator]

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- C-05 ------------------------------------------------------------------
def test_un_borrador_con_fecha_de_publicacion_se_acepta(sesion_de_pruebas: Session) -> None:
    """Es el estado de un articulo despublicado (USER_FLOWS.md B.8).

    La restriccion se escribio deliberadamente en un solo sentido: si tambien
    exigiera `published_at IS NULL` para los borradores, despublicar seria
    imposible.
    """
    sesion_de_pruebas.add(
        _articulo("despublicado", status=PostStatus.DRAFT, published_at=UN_INSTANTE)
    )

    sesion_de_pruebas.flush()  # no debe lanzar


# --- C-06, C-07 ------------------------------------------------------------
@pytest.mark.parametrize("valoracion", [0, -1, 6, 100])
def test_una_valoracion_fuera_de_escala_se_rechaza(
    sesion_de_pruebas: Session, valoracion: int
) -> None:
    sesion_de_pruebas.add(_review(f"valoracion-{valoracion}", rating=valoracion))

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- C-08 ------------------------------------------------------------------
@pytest.mark.parametrize("valoracion", [1, 3, 5])
def test_una_valoracion_dentro_de_escala_se_acepta(
    sesion_de_pruebas: Session, valoracion: int
) -> None:
    sesion_de_pruebas.add(_review(f"valoracion-{valoracion}", rating=valoracion))

    sesion_de_pruebas.flush()  # no debe lanzar


# --- C-09 ------------------------------------------------------------------
def test_un_borrador_puede_no_tener_valoracion(sesion_de_pruebas: Session) -> None:
    """Un `CHECK` solo rechaza cuando la condicion es `FALSE`, no cuando es `NULL`.

    Por eso la restriccion de escala no necesita excluir el nulo a mano, y por
    eso conviene comprobarlo: es facil escribirla de una forma que si lo excluya.
    """
    sesion_de_pruebas.add(_review("sin-valoracion", rating=None))

    sesion_de_pruebas.flush()  # no debe lanzar


# --- C-10 ------------------------------------------------------------------
def test_un_estado_de_proyecto_fuera_del_conjunto_se_rechaza(sesion_de_pruebas: Session) -> None:
    with pytest.raises(IntegrityError):
        sesion_de_pruebas.execute(
            text(
                "INSERT INTO projects (id, slug, title, content, status, project_status,"
                " featured, technologies, created_at, updated_at)"
                " VALUES (gen_random_uuid(), 'proyecto-zombi', 'T', '', 'draft', 'zombi',"
                " false, '[]'::jsonb, now(), now())"
            )
        )


def test_el_estado_del_proyecto_es_independiente_de_su_publicacion(
    sesion_de_pruebas: Session,
) -> None:
    """`status` y `project_status` son ortogonales: un proyecto terminado se publica."""
    sesion_de_pruebas.add(
        _proyecto(
            "terminado-y-publicado",
            status=ProjectStatus.PUBLISHED,
            published_at=UN_INSTANTE,
            project_status=ProjectWorkStatus.COMPLETED,
        )
    )

    sesion_de_pruebas.flush()  # no debe lanzar


# --- C-11 ------------------------------------------------------------------
def test_las_marcas_de_tiempo_llevan_zona_horaria(sesion_de_pruebas: Session) -> None:
    """CONTENT_MODEL.md, invariante 10: toda fecha se almacena en UTC.

    Una columna `TIMESTAMP` sin zona devolveria un `datetime` ingenuo y nadie
    sabria a que instante corresponde.
    """
    articulo = _articulo("con-marcas")
    sesion_de_pruebas.add(articulo)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(articulo)

    assert articulo.created_at.tzinfo is not None
    assert articulo.updated_at.tzinfo is not None


# --- C-12 ------------------------------------------------------------------
def test_dentro_de_una_transaccion_las_dos_marcas_coinciden(
    sesion_de_pruebas: Session,
) -> None:
    """`now()` en PostgreSQL es la hora de **inicio de la transaccion**.

    Todo lo escrito en una misma transaccion comparte marca temporal, y eso es
    lo correcto: los cambios de una transaccion ocurren logicamente a la vez.
    Se deja escrito porque es justo la propiedad que hace que la prueba
    siguiente necesite dos transacciones y no una.

    La alternativa —`clock_timestamp()`, hora de reloj real— se descarto: es una
    funcion propia de PostgreSQL, y el proyecto usa SQL estandar para no atarse a
    un proveedor (requisito T-02). `now()` compila a `CURRENT_TIMESTAMP` fuera de
    PostgreSQL.
    """
    articulo = _articulo("misma-transaccion")
    sesion_de_pruebas.add(articulo)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(articulo)

    assert articulo.created_at == articulo.updated_at


def test_editar_en_otra_transaccion_avanza_la_marca_de_modificacion(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """`created_at` no cambia; `updated_at` si.

    Reproduce lo que ocurre de verdad: crear y editar son dos peticiones HTTP y,
    por tanto, dos transacciones (USER_FLOWS.md B.3). Esta prueba **confirma de
    verdad**, asi que limpia lo que crea en un `finally`.
    """
    identificador: uuid.UUID | None = None
    try:
        with Session(bind=database_engine) as sesion:
            articulo = _articulo("se-edita-de-verdad")
            sesion.add(articulo)
            sesion.commit()
            identificador = articulo.id
            creado_en, modificado_en = articulo.created_at, articulo.updated_at

        with Session(bind=database_engine) as sesion:
            guardado = sesion.get(Post, identificador)
            assert guardado is not None
            guardado.title = "Titulo corregido"
            sesion.commit()

            assert guardado.created_at == creado_en
            assert guardado.updated_at > modificado_en
    finally:
        if identificador is not None:
            with Session(bind=database_engine) as sesion:
                sesion.execute(delete(Post).where(Post.id == identificador))
                sesion.commit()


def test_el_contenido_se_guarda_como_markdown_fuente(sesion_de_pruebas: Session) -> None:
    """ADR-005, decision 2: se guarda el Markdown tal cual, sin renderizar."""
    markdown = "# Titulo\n\nTexto con `codigo` y un [enlace](https://ejemplo.invalid)."
    articulo = _articulo("markdown", content=markdown)
    sesion_de_pruebas.add(articulo)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(articulo)

    assert articulo.content == markdown
    assert "<h1>" not in articulo.content


def test_las_tecnologias_de_un_proyecto_conservan_su_orden(sesion_de_pruebas: Session) -> None:
    """Es la razon principal de guardarlas como lista y no como conjunto."""
    tecnologias = ["Python", "FastAPI", "PostgreSQL", "Terraform"]
    proyecto = _proyecto("con-tecnologias", technologies=tecnologias)
    sesion_de_pruebas.add(proyecto)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(proyecto)

    assert proyecto.technologies == tecnologias


def test_un_articulo_sin_titulo_se_rechaza(sesion_de_pruebas: Session) -> None:
    """`title` es el unico campo que USER_FLOWS.md B.2 exige al crear un borrador."""
    with pytest.raises(IntegrityError):
        sesion_de_pruebas.execute(
            text(
                "INSERT INTO posts (id, slug, content, status, featured, created_at, updated_at)"
                " VALUES (gen_random_uuid(), 'sin-titulo', '', 'draft', false, now(), now())"
            )
        )
