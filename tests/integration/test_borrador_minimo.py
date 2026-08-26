"""El esquema admite el borrador mínimo que define USER_FLOWS.md B.2.

Regresión de un defecto funcional detectado en la **revisión pre-approval** de
`Task/008`, después de la primera declaración `Lista para validación`.

El flujo de creación es explícito y no admite lectura alternativa:

> 1. Desde el panel, el administrador elige el tipo de contenido y crea uno nuevo.
> 2. Introduce título; el **slug se propone automáticamente** y es editable.
> 3. El contenido nace en estado `draft`.
> 4. Se registran `created_at` y `updated_at`.
>
> **Validación:** slug único por tipo de contenido; título obligatorio.

En ese instante existen exactamente **dos** valores de negocio: el título que
escribe la persona y el slug que propone la aplicación. Todo lo demás llega
después, editando (B.3).

El defecto: `book_reviews.book_title`, `book_reviews.book_author`,
`videos.provider` y `videos.video_url` eran `NOT NULL`. Crear un borrador de
esos dos tipos era **imposible** sin inventar valores que nadie había
introducido, así que el esquema contradecía el flujo que debe soportar.

Por qué estas pruebas no rellenan los campos
--------------------------------------------

Poner `"pendiente"`, `"N/A"` o una URL ficticia las pondría verdes sin probar
nada: el defecto es justo que el esquema **obliga** a inventar ese valor. Lo que
se comprueba es la nullability real.

Dónde vive la regla contraria
-----------------------------

Que un contenido **publicado** deba tener autor, proveedor o URL es una
validación de **publicación** (USER_FLOWS.md B.7: *"se validan los campos
mínimos"*), y pertenece a `Task/012`. `Task/008` solo tiene que permitir
**representar** un borrador incompleto.
"""

from __future__ import annotations

import pytest
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


# --- CASO 1 — Post ---------------------------------------------------------
def test_un_articulo_nace_solo_con_titulo_y_slug(sesion_de_pruebas: Session) -> None:
    articulo = Post(slug="borrador-minimo-articulo", title="Borrador mínimo")

    sesion_de_pruebas.add(articulo)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(articulo)

    assert articulo.id is not None
    assert articulo.status is PostStatus.DRAFT
    assert articulo.published_at is None
    assert articulo.featured is False
    assert articulo.content == ""
    assert articulo.summary is None
    assert articulo.cover_id is None
    assert articulo.created_at is not None
    assert articulo.updated_at is not None


# --- CASO 2 — BookReview ---------------------------------------------------
def test_una_review_nace_solo_con_titulo_y_slug(sesion_de_pruebas: Session) -> None:
    """Sin `book_title`, sin `book_author` y sin `rating`.

    El título del **libro** y su autor los introduce el administrador editando
    (B.3), no al crear: en B.2 todavía no los ha escrito.
    """
    review = BookReview(slug="borrador-minimo-review", title="Borrador mínimo")

    sesion_de_pruebas.add(review)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(review)

    assert review.status is BookReviewStatus.DRAFT
    assert review.book_title is None
    assert review.book_author is None
    assert review.rating is None
    assert review.external_link is None
    assert review.published_at is None


# --- CASO 3 — Video --------------------------------------------------------
def test_un_video_nace_solo_con_titulo_y_slug(sesion_de_pruebas: Session) -> None:
    """Sin `provider`, sin `video_url`, sin `embed_reference` y sin duración.

    Un vídeo se crea desde el panel igual que cualquier otro contenido; la URL y
    el proveedor se pegan después. Exigirlos al crear obligaría a inventar una
    dirección que todavía no se conoce.
    """
    video = Video(slug="borrador-minimo-video", title="Borrador mínimo")

    sesion_de_pruebas.add(video)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(video)

    assert video.status is VideoStatus.DRAFT
    assert video.provider is None
    assert video.video_url is None
    assert video.embed_reference is None
    assert video.duration_seconds is None
    assert video.thumbnail_id is None
    assert video.published_at is None


# --- CASO 4 — Project ------------------------------------------------------
def test_un_proyecto_nace_solo_con_titulo_y_slug(sesion_de_pruebas: Session) -> None:
    """Los defaults de `project_status` y `technologies` son valores reales.

    Un proyecto recién creado **está** activo, y su lista de tecnologías **está**
    vacía: ninguno de los dos es un relleno para esquivar un `NOT NULL`.
    """
    proyecto = Project(slug="borrador-minimo-proyecto", title="Borrador mínimo")

    sesion_de_pruebas.add(proyecto)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(proyecto)

    assert proyecto.status is ProjectStatus.DRAFT
    assert proyecto.project_status is ProjectWorkStatus.ACTIVE
    assert proyecto.technologies == []
    assert proyecto.repository_url is None
    assert proyecto.demo_url is None
    assert proyecto.published_at is None


# --- Guarda de la corrección ----------------------------------------------
def test_ningun_tipo_publicable_exige_al_crear_un_valor_que_nadie_ha_introducido(
    sesion_de_pruebas: Session,
) -> None:
    """Contrato explícito: qué puede exigir el esquema en el momento del `INSERT`.

    Recorre las columnas reales en lugar de una lista escrita a mano, así que una
    columna `NOT NULL` nueva entra en la comprobación por existir. Es la guarda
    que impide que el defecto vuelva por otro campo.

    Lo único que el esquema puede exigir sin default es lo que B.2 **sí**
    proporciona: la identidad que genera la aplicación, el título y el slug.
    """
    disponibles_en_b2 = {"id", "title", "slug"}

    exigidos: dict[str, list[str]] = {}
    for modelo in (Post, BookReview, Video, Project):
        sin_valor = [
            columna.name
            for columna in modelo.__table__.columns
            if not columna.nullable
            and columna.server_default is None
            and columna.default is None
            and columna.name not in disponibles_en_b2
        ]
        if sin_valor:
            exigidos[modelo.__tablename__] = sorted(sin_valor)

    assert exigidos == {}, (
        "estas columnas obligan a inventar un valor al crear un borrador, y "
        f"USER_FLOWS.md B.2 no lo proporciona: {exigidos}. O admiten nulo, o "
        "necesitan un default semánticamente real, o hace falta una fuente "
        "canónica que justifique exigirlas al crear."
    )
