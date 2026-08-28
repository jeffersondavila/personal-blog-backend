"""Remediacion test-first del slice Profile."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.datos import medio, perfil

pytestmark = pytest.mark.integration

RUTA = "/api/v1/profile"


def test_profile_existente_expone_exactamente_la_identidad_publica(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(
        perfil(
            nombre="Ada Lovelace",
            titular="Ingeniera",
            biografia="# Biografia\n\nMarkdown fuente.",
            correo="ada@example.invalid",
            foto=medio(
                clave="privado/profile.png",
                texto_alternativo="Retrato",
                ancho=640,
                alto=640,
            ),
            seo_title="Ada",
            seo_description="Perfil profesional",
            enlaces=[("GitHub", "https://example.invalid/github", 0)],
        )
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(RUTA)

    assert respuesta.status_code == 200
    cuerpo: dict[str, Any] = respuesta.json()
    assert set(cuerpo) == {
        "full_name",
        "headline",
        "biography",
        "contact_email",
        "photo",
        "seo_title",
        "seo_description",
        "social_links",
    }
    assert cuerpo["full_name"] == "Ada Lovelace"
    assert cuerpo["biography"] == "# Biografia\n\nMarkdown fuente."
    assert cuerpo["photo"] == {"alt_text": "Retrato", "width": 640, "height": 640}
    assert "object_key" not in cuerpo["photo"]
    assert cuerpo["social_links"] == [{"label": "GitHub", "url": "https://example.invalid/github"}]


def test_profile_ausente_es_404_con_control_positivo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    ausente = cliente_de_la_api.get(RUTA)
    assert ausente.status_code == 404
    assert ausente.json()["error"]["code"] == "resource_not_found"

    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()
    assert cliente_de_la_api.get(RUTA).status_code == 200


def test_social_links_se_ordenan_y_no_exponen_display_order(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(
        perfil(
            enlaces=[
                ("Tercero", "https://example.invalid/3", 2),
                ("Primero", "https://example.invalid/1", 0),
                ("Segundo", "https://example.invalid/2", 1),
            ]
        )
    )
    sesion_de_pruebas.flush()

    enlaces = cliente_de_la_api.get(RUTA).json()["social_links"]
    assert [enlace["label"] for enlace in enlaces] == ["Primero", "Segundo", "Tercero"]
    assert all(set(enlace) == {"label", "url"} for enlace in enlaces)


def test_profile_rechaza_parametros_sin_ocultar_que_la_ruta_existe(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(RUTA).status_code == 200
    respuesta = cliente_de_la_api.get(RUTA, params={"page": 1})
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "validation_error"
