"""API publica de videos y del perfil (matriz E y A).

Los dos son los casos **irregulares** del contrato, y por eso van juntos: el
video es el unico tipo de contenido sin endpoint de detalle, y el perfil el
unico recurso *singleton*, sin estado de publicacion y sin paginacion.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.videos.domain import VideoStatus
from tests.integration.datos import (
    ANTIGUO,
    RECIENTE,
    etiqueta,
    medio,
    perfil,
    video,
)

pytestmark = pytest.mark.integration

VIDEOS = "/api/v1/videos"
PERFIL = "/api/v1/profile"


def _slugs(respuesta: Any) -> list[str]:
    cuerpo: dict[str, Any] = respuesta.json()
    return [elemento["slug"] for elemento in cuerpo["items"]]


# --- E: videos -------------------------------------------------------------
def test_el_listado_de_videos_solo_devuelve_publicados(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            video("publicado", estado=VideoStatus.PUBLISHED),
            video("borrador", estado=VideoStatus.DRAFT),
            video("archivado", estado=VideoStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(VIDEOS)) == ["publicado"]


def test_el_listado_de_videos_basta_para_reproducirlos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """USER_FLOWS.md A.6: se reproduce por embed o se abre el enlace externo.

    Como no existe endpoint de detalle, si estos campos no viajaran aqui no
    habria ninguna otra peticion desde la que obtenerlos.
    """
    sesion_de_pruebas.add(
        video(
            "uno",
            titulo="Un video",
            resumen="Descripcion breve",
            proveedor="youtube",
            url="https://ejemplo.invalid/watch",
            referencia_de_embed="abc123",
            duracion=615,
            miniatura=medio(clave="miniaturas/uno.png", texto_alternativo="Miniatura"),
            publicado_el=RECIENTE,
        )
    )
    sesion_de_pruebas.flush()

    elemento: dict[str, Any] = cliente_de_la_api.get(VIDEOS).json()["items"][0]

    assert elemento["title"] == "Un video"
    assert elemento["summary"] == "Descripcion breve"
    assert elemento["provider"] == "youtube"
    assert elemento["video_url"] == "https://ejemplo.invalid/watch"
    assert elemento["embed_reference"] == "abc123"
    assert elemento["duration_seconds"] == 615
    assert elemento["thumbnail"] == {"alt_text": "Miniatura", "width": None, "height": None}


def test_un_video_no_tiene_contenido_markdown(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """ADR-005, decision 7: el contenido principal de un video es el video."""
    sesion_de_pruebas.add(video("uno"))
    sesion_de_pruebas.flush()

    elemento: dict[str, Any] = cliente_de_la_api.get(VIDEOS).json()["items"][0]

    assert "content" not in elemento
    assert "reading_time_minutes" not in elemento


def test_no_existe_endpoint_de_detalle_de_video(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """El contrato vigente no lo declara y `Task/009` no inventa contrato.

    Se crea un video **publicado** a proposito: asi el `404` no puede deberse a
    que no haya contenido, sino a que la ruta no existe.
    """
    sesion_de_pruebas.add(video("publicado", estado=VideoStatus.PUBLISHED))
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(f"{VIDEOS}/publicado").status_code == 404


def test_los_videos_se_filtran_por_etiqueta_sin_sacar_borradores(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    compartida = etiqueta("compartida")
    sesion_de_pruebas.add_all(
        [
            video("visible", etiquetas=[compartida], estado=VideoStatus.PUBLISHED),
            video("oculto", etiquetas=[compartida], estado=VideoStatus.DRAFT),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(VIDEOS, params={"tag": "compartida"})) == ["visible"]


def test_los_videos_se_ordenan_por_fecha_descendente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [video("viejo", publicado_el=ANTIGUO), video("nuevo", publicado_el=RECIENTE)]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(VIDEOS)) == ["nuevo", "viejo"]


# --- A: perfil -------------------------------------------------------------
def test_el_perfil_devuelve_la_identidad_publica(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(
        perfil(
            nombre="Una Persona",
            titular="Ingeniera de plataforma",
            biografia="# Quien soy\n\nTexto en Markdown.",
            correo="contacto@ejemplo.invalid",
            foto=medio(clave="perfil/foto.png", texto_alternativo="Retrato"),
            seo_title="Quien soy",
            seo_description="Perfil profesional",
        )
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(PERFIL)

    assert respuesta.status_code == 200
    cuerpo: dict[str, Any] = respuesta.json()
    assert cuerpo["full_name"] == "Una Persona"
    assert cuerpo["headline"] == "Ingeniera de plataforma"
    # Markdown fuente: `Task/009` no renderiza (ADR-005).
    assert cuerpo["biography"] == "# Quien soy\n\nTexto en Markdown."
    assert cuerpo["contact_email"] == "contacto@ejemplo.invalid"
    assert cuerpo["photo"] == {"alt_text": "Retrato", "width": None, "height": None}
    assert cuerpo["seo_title"] == "Quien soy"


def test_sin_perfil_la_respuesta_es_404(cliente_de_la_api: TestClient) -> None:
    """Decision D-009-N.

    La base recien migrada esta vacia y `Task/008` tenia prohibido sembrar el
    perfil: contiene el nombre real y el correo del autor. Devolver `200` con
    campos vacios seria inventar una identidad; `503` afirmaria que el servicio
    no funciona, y funciona. El recurso simplemente no existe todavia.
    """
    respuesta = cliente_de_la_api.get(PERFIL)

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "resource_not_found"


def test_los_enlaces_sociales_respetan_el_orden_configurado(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Se insertan desordenados: quien debe ordenar es la consulta, no el orden
    de insercion."""
    sesion_de_pruebas.add(
        perfil(
            enlaces=[
                ("Tercero", "https://ejemplo.invalid/3", 2),
                ("Primero", "https://ejemplo.invalid/1", 0),
                ("Segundo", "https://ejemplo.invalid/2", 1),
            ]
        )
    )
    sesion_de_pruebas.flush()

    enlaces: list[dict[str, Any]] = cliente_de_la_api.get(PERFIL).json()["social_links"]

    assert [enlace["label"] for enlace in enlaces] == ["Primero", "Segundo", "Tercero"]


def test_el_perfil_no_expone_identidad_interna_ni_el_cerrojo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """`is_singleton` es la restriccion del esquema hecha columna, no un dato."""
    sesion_de_pruebas.add(perfil(enlaces=[("Uno", "https://ejemplo.invalid/1", 0)]))
    sesion_de_pruebas.flush()

    cuerpo: dict[str, Any] = cliente_de_la_api.get(PERFIL).json()

    for interno in ("id", "is_singleton", "created_at", "updated_at", "photo_id"):
        assert interno not in cuerpo, f"el perfil publico expone {interno!r}"

    assert set(cuerpo["social_links"][0]) == {"label", "url"}


def test_el_perfil_no_admite_parametros(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Es un *singleton*: no se pagina ni se filtra (D-009-C)."""
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(PERFIL, params={"page": 1}).status_code == 422


@pytest.mark.parametrize(("valor", "esperado"), [("true", ["destacado"]), ("false", ["normal"])])
def test_el_filtro_de_destacados_funciona_en_videos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, valor: str, esperado: list[str]
) -> None:
    """Cada tipo tiene su propia consulta: el filtro se ejercita en todas."""
    sesion_de_pruebas.add_all([video("destacado", destacado=True), video("normal")])
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(VIDEOS, params={"featured": valor})) == esperado
