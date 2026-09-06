"""Remediacion test-first del slice Videos."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.videos.domain import VideoStatus
from tests.integration.datos import ANTIGUO, RECIENTE, etiqueta, medio, video

pytestmark = pytest.mark.integration

RUTA = "/api/v1/videos"


def _slugs(respuesta: Any) -> list[str]:
    return [item["slug"] for item in respuesta.json()["items"]]


def test_listado_solo_publica_videos_y_lleva_datos_reproducibles(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            video(
                "visible",
                titulo="Demostracion",
                resumen="Resumen",
                proveedor="youtube",
                url="https://example.invalid/watch",
                referencia_de_embed="abc123",
                duracion=615,
                miniatura=medio(
                    clave="privado/thumbnail.png",
                    texto_alternativo="Miniatura",
                    ancho=1280,
                    alto=720,
                ),
            ),
            video("borrador", estado=VideoStatus.DRAFT),
            video("archivado", estado=VideoStatus.ARCHIVED),
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
        "thumbnail",
        "provider",
        "video_url",
        "embed_reference",
        "duration_seconds",
    }
    assert item["provider"] == "youtube"
    # `access_url` se anade en `Task/010` (D-009-O, cerrada). El enlace lleva
    # firma y marca de tiempo, asi que no puede compararse literal: se comprueba
    # su presencia y se mantiene cerrado el conjunto de campos.
    medio_publico = item["thumbnail"]
    sin_el_enlace = {
        c: v
        for c, v in medio_publico.items()
        # Dos enlaces firmados desde `Task/016`: el del original y el de la
        # miniatura (requisito P-04). Ninguno es un dato estable del contrato.
        if c not in {"access_url", "thumbnail_access_url"}
    }
    assert sin_el_enlace == {"alt_text": "Miniatura", "width": 1280, "height": 720}
    assert medio_publico["access_url"].startswith("http")
    assert "object_key" not in item["thumbnail"]


def test_videos_estan_paginados_con_orden_estable(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all([video(f"v-{indice}", publicado_el=RECIENTE) for indice in range(5)])
    sesion_de_pruebas.flush()

    paginas = [
        cliente_de_la_api.get(RUTA, params={"page": pagina, "page_size": 2}).json()
        for pagina in (1, 2, 3)
    ]
    assert (paginas[0]["total"], paginas[0]["pages"]) == (5, 3)
    slugs = [item["slug"] for pagina in paginas for item in pagina["items"]]
    assert len(slugs) == len(set(slugs)) == 5


def test_tag_y_featured_preservan_la_visibilidad_publica(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    comun = etiqueta("python")
    sesion_de_pruebas.add_all(
        [
            video("destacado", destacado=True, etiquetas=[comun]),
            video("normal", etiquetas=[comun]),
            video("oculto", estado=VideoStatus.DRAFT, destacado=True, etiquetas=[comun]),
            video("sin-tag", destacado=True),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(RUTA, params={"tag": "python"})) == [
        "destacado",
        "normal",
    ]
    assert _slugs(cliente_de_la_api.get(RUTA, params={"tag": "python", "featured": "true"})) == [
        "destacado"
    ]
    assert _slugs(cliente_de_la_api.get(RUTA, params={"tag": "python", "featured": "false"})) == [
        "normal"
    ]


def test_sort_controla_fecha_y_titulo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            video("viejo", titulo="Zulu", publicado_el=ANTIGUO),
            video("nuevo", titulo="Alpha", publicado_el=RECIENTE),
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


def test_no_hay_detalle_de_video_con_control_de_listado_existente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(video("publicado"))
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(RUTA).status_code == 200
    assert cliente_de_la_api.get(f"{RUTA}/publicado").status_code == 404
