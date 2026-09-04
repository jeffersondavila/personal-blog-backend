"""Videos administrativos contra PostgreSQL real (matriz V de `Task/012`).

Lo que distingue a un video, con su fuente:

- **No tiene `content` en Markdown** (CONTENT_MODEL.md seccion 2, ADR-005
  decision 7). Su contenido es el video externo, asi que lo que B.7 llama
  "contenido" se materializa en `video_url` y `provider`.
- **No se despublica.** `MVP_SCOPE.md` 3.2 concede `published -> draft` a
  articulos y reviews **y solo a ellos**; `Task/008` lo expreso por **ausencia
  del metodo** en el dominio, y aqui se expresa por ausencia de la ruta.
- Su imagen es `thumbnail`, no `cover` (`data-model.md` 4.7).
- El proveedor se exige **presente**, no perteneciente a una lista: la lista
  cerrada es de `Task/014` y por eso la columna no lleva `CHECK`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import ENTIDAD_VIDEO, AccionAuditada
from app.modules.videos.domain import VideoStatus
from tests.integration.administracion import (
    ADMIN,
    administrador_con_sesion,
    codigo_de_error,
    eventos_de,
)
from tests.integration.datos import medio, video

pytestmark = pytest.mark.integration

VIDEOS = f"{ADMIN}/videos"


def _completo(**cambios: Any) -> dict[str, Any]:
    valores: dict[str, Any] = {
        "title": "Un video",
        "summary": "Un resumen breve.",
        "provider": "youtube",
        "video_url": "https://example.invalid/watch?v=1",
    }
    valores.update(cambios)
    return valores


def _crear(cliente: TestClient, **cambios: Any) -> dict[str, Any]:
    respuesta = cliente.post(VIDEOS, json=_completo(**cambios))
    assert respuesta.status_code == 201, respuesta.text
    cuerpo: dict[str, Any] = respuesta.json()
    return cuerpo


def test_sin_sesion_no_se_listan_los_videos(cliente_administrativo: TestClient) -> None:
    assert cliente_administrativo.get(VIDEOS).status_code == 401


# --- V-01: el video no tiene Markdown --------------------------------------
def test_el_video_no_admite_contenido_markdown(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """ADR-005 decision 7: su contenido principal es el video externo."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(VIDEOS, json=_completo(content="# Markdown"))

    assert respuesta.status_code == 422


def test_la_respuesta_de_un_video_no_declara_contenido(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo)

    assert "content" not in cuerpo


# --- V-02: crear y editar --------------------------------------------------
def test_un_video_nace_como_borrador_con_datos_incompletos(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`data-model.md` 4.7: proveedor y URL son nulos en un borrador."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(VIDEOS, json={"title": "Solo el titulo"})

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "draft"
    assert cuerpo["provider"] is None
    assert cuerpo["video_url"] is None


def test_los_metadatos_del_video_se_administran(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo, embed_reference="abc123", duration_seconds=630)

    assert cuerpo["provider"] == "youtube"
    assert cuerpo["video_url"] == "https://example.invalid/watch?v=1"
    assert cuerpo["embed_reference"] == "abc123"
    assert cuerpo["duration_seconds"] == 630


def test_una_duracion_no_positiva_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`ck_videos_duracion_positiva`, comprobado antes de tocar la base."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(VIDEOS, json=_completo(duration_seconds=0))

    assert respuesta.status_code == 422


def test_la_miniatura_se_asocia_y_devuelve_su_enlace(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El video usa `thumbnail_id`, no `cover_id` (`data-model.md` 4.7)."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave="medios/miniatura/original.png", texto_alternativo="Miniatura")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    cuerpo = _crear(cliente_administrativo, thumbnail_id=str(imagen.id))

    assert cuerpo["thumbnail"]["id"] == str(imagen.id)
    assert cuerpo["thumbnail"]["access_url"].startswith("http")
    assert "cover" not in cuerpo


def test_una_miniatura_desconocida_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(VIDEOS, json=_completo(thumbnail_id=str(uuid.uuid4())))

    assert respuesta.status_code == 422
    assert codigo_de_error(respuesta) == "unknown_reference"
    assert respuesta.json()["error"]["details"]["campo"] == "thumbnail_id"


# --- V-03: validacion de publicacion --------------------------------------
@pytest.mark.parametrize("campo", ["provider", "video_url"])
def test_no_se_puede_publicar_un_video_sin_url_ni_proveedor(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, campo: str
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, **{campo: None})

    respuesta = cliente_administrativo.post(f"{VIDEOS}/{creado['id']}/publish")

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "cannot_publish_incomplete_draft"
    assert respuesta.json()["error"]["details"]["campos"] == [campo]


def test_cualquier_proveedor_presente_basta_para_publicar(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """La lista cerrada de proveedores permitidos es de `Task/014`."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, provider="un-proveedor")

    respuesta = cliente_administrativo.post(f"{VIDEOS}/{creado['id']}/publish")

    assert respuesta.status_code == 200


def test_un_video_completo_se_publica_y_se_archiva(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    publicado = cliente_administrativo.post(f"{VIDEOS}/{creado['id']}/publish")
    assert publicado.status_code == 200
    assert publicado.json()["published_at"] is not None

    archivado = cliente_administrativo.post(f"{VIDEOS}/{creado['id']}/archive")
    assert archivado.status_code == 200
    assert archivado.json()["status"] == "archived"
    assert archivado.json()["published_at"] == publicado.json()["published_at"]


# --- V-04: el video NO se despublica --------------------------------------
def test_el_video_no_tiene_ruta_de_despublicacion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`MVP_SCOPE.md` 3.2: la transicion no existe, asi que la ruta tampoco.

    Se comprueba con `404` de **ruta**, que es lo que devuelve una direccion que
    el router no declara. Un `405` significaria que la ruta existe con otros
    metodos; un `409`, que existe y rechaza. Aqui no existe en absoluto, que es
    justo la garantia: no puede habilitarse por descuido.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{VIDEOS}/{creado['id']}/publish")

    respuesta = cliente_administrativo.post(f"{VIDEOS}/{creado['id']}/unpublish")

    assert respuesta.status_code == 404


def test_no_existe_forma_de_eliminar_un_video(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    assert cliente_administrativo.delete(f"{VIDEOS}/{creado['id']}").status_code == 405


# --- V-05: listado, auditoria y vista publica ------------------------------
def test_el_listado_administrativo_incluye_los_tres_estados(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add_all(
        [
            video("borrador", estado=VideoStatus.DRAFT),
            video("publicado", estado=VideoStatus.PUBLISHED),
            video("archivado", estado=VideoStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    assert cliente_administrativo.get(VIDEOS).json()["total"] == 3


def test_un_video_se_edita(cliente_administrativo: TestClient, sesion_de_pruebas: Session) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.put(
        f"{VIDEOS}/{creado['id']}",
        json=_completo(slug=creado["slug"], provider="vimeo"),
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["provider"] == "vimeo"


def test_la_auditoria_de_un_video_apunta_a_su_tipo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    creado = _crear(cliente_administrativo)

    evento = eventos_de(sesion_de_pruebas, AccionAuditada.CONTENIDO_CREADO.value)[0]
    assert evento.entity_type == ENTIDAD_VIDEO
    assert evento.entity_id == uuid.UUID(creado["id"])


def test_publicar_un_video_lo_hace_visible_en_la_api_publica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    cliente_administrativo.post(f"{VIDEOS}/{creado['id']}/publish")

    publico = cliente_administrativo.get("/api/v1/videos")
    assert publico.status_code == 200
    assert [item["slug"] for item in publico.json()["items"]] == [creado["slug"]]


def test_archivar_un_video_lo_retira_de_la_api_publica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{VIDEOS}/{creado['id']}/publish")

    cliente_administrativo.post(f"{VIDEOS}/{creado['id']}/archive")

    assert cliente_administrativo.get("/api/v1/videos").json()["items"] == []
    from app.modules.videos.infrastructure.models import Video

    assert sesion_de_pruebas.execute(select(Video)).scalar_one().status is VideoStatus.ARCHIVED
