"""Perfil administrativo contra PostgreSQL real (matriz P de `Task/012`).

Flujo B.10 de USER_FLOWS.md: el administrador consulta y edita el perfil
"Quien soy". El perfil es un **singleton**: *"existe exactamente uno y no se crea
ni elimina"*.

Decision **D-012-U**: `Task/012` **no** lo crea. `data-model.md` seccion 5 lo
asigna por nombre —*"El perfil no se crea ni se elimina por API — `Task/012` —
solo expone lectura y edicion"*—, y la creacion real es de `Task/022` (semilla
local) y `Task/036` (produccion).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import ENTIDAD_PERFIL, AccionAuditada
from app.modules.profile.infrastructure.models import Profile, ProfileSocialLink
from tests.integration.administracion import (
    ADMIN,
    administrador_con_sesion,
    codigo_de_error,
    eventos_de,
)
from tests.integration.datos import medio, perfil

pytestmark = pytest.mark.integration

PERFIL = f"{ADMIN}/profile"

_MINIMO: dict[str, Any] = {
    "full_name": "Jefferson Davila",
    "headline": None,
    "biography": "",
    "contact_email": None,
    "photo_id": None,
    "seo_title": None,
    "seo_description": None,
    "social_links": [],
}


# --- A-01: sin sesion no se llega a ningun sitio ---------------------------
def test_sin_sesion_no_se_puede_consultar_el_perfil(cliente_administrativo: TestClient) -> None:
    respuesta = cliente_administrativo.get(PERFIL)

    assert respuesta.status_code == 401
    assert codigo_de_error(respuesta) == "unauthenticated"


def test_sin_sesion_no_se_puede_editar_el_perfil(cliente_administrativo: TestClient) -> None:
    respuesta = cliente_administrativo.put(PERFIL, json=_MINIMO)

    assert respuesta.status_code == 401


# --- P-01: consulta administrativa -----------------------------------------
def test_el_perfil_se_consulta_con_sus_enlaces_en_orden(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(
        perfil(
            nombre="Jefferson Davila",
            titular="Ingeniero",
            biografia="# Hola",
            correo="hola@example.invalid",
            enlaces=[("LinkedIn", "https://example.invalid/in", 1), ("GitHub", "https://g", 0)],
        )
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.get(PERFIL)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["full_name"] == "Jefferson Davila"
    assert cuerpo["headline"] == "Ingeniero"
    assert cuerpo["biography"] == "# Hola"
    assert cuerpo["contact_email"] == "hola@example.invalid"
    assert [enlace["label"] for enlace in cuerpo["social_links"]] == ["GitHub", "LinkedIn"]


def test_la_respuesta_administrativa_no_expone_campos_internos(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El cerrojo del *singleton* y la clave foranea de la foto son internos."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    cuerpo = cliente_administrativo.get(PERFIL).json()

    for interno in ("is_singleton", "photo_id"):
        assert interno not in cuerpo


def test_la_respuesta_administrativa_trae_las_fechas_de_gestion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """MVP_SCOPE.md 3.1: *"consultar fechas de creacion y actualizacion"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    cuerpo = cliente_administrativo.get(PERFIL).json()

    assert cuerpo["created_at"] is not None
    assert cuerpo["updated_at"] is not None


# --- P-02: edicion ---------------------------------------------------------
def test_el_perfil_se_edita(cliente_administrativo: TestClient, sesion_de_pruebas: Session) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil(nombre="Antiguo"))
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(
        PERFIL,
        json={**_MINIMO, "full_name": "Nuevo", "headline": "Titular", "biography": "## Bio"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["full_name"] == "Nuevo"
    guardado = sesion_de_pruebas.execute(select(Profile)).scalar_one()
    assert guardado.full_name == "Nuevo"
    assert guardado.biography == "## Bio"


def test_editar_el_perfil_no_crea_un_segundo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Invariante 6 de CONTENT_MODEL.md: el perfil es unico."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    cliente_administrativo.put(PERFIL, json={**_MINIMO, "full_name": "Nuevo"})

    total = sesion_de_pruebas.execute(select(func.count()).select_from(Profile)).scalar_one()
    assert total == 1


# --- P-03: los enlaces sociales se reemplazan y ordenan --------------------
def test_los_enlaces_sociales_se_reemplazan_por_completo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil(enlaces=[("Viejo", "https://viejo.invalid", 0)]))
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(
        PERFIL,
        json={
            **_MINIMO,
            "social_links": [
                {"label": "GitHub", "url": "https://github.invalid"},
                {"label": "LinkedIn", "url": "https://linkedin.invalid"},
            ],
        },
    )

    assert respuesta.status_code == 200
    assert [enlace["label"] for enlace in respuesta.json()["social_links"]] == [
        "GitHub",
        "LinkedIn",
    ]
    etiquetas = sesion_de_pruebas.execute(
        select(ProfileSocialLink.label).order_by(ProfileSocialLink.display_order)
    ).all()
    assert [fila[0] for fila in etiquetas] == ["GitHub", "LinkedIn"]


def test_el_orden_de_presentacion_sale_del_indice_del_array(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-Q**.

    `uq_profile_social_links_profile_id_display_order` haria fallar dos enlaces
    con el mismo orden. Derivarlo del array hace ese estado **irrepresentable**
    en lugar de detectarlo con un error.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    cliente_administrativo.put(
        PERFIL,
        json={
            **_MINIMO,
            "social_links": [
                {"label": "Uno", "url": "https://uno.invalid"},
                {"label": "Dos", "url": "https://dos.invalid"},
                {"label": "Tres", "url": "https://tres.invalid"},
            ],
        },
    )

    ordenes = sesion_de_pruebas.execute(
        select(ProfileSocialLink.display_order).order_by(ProfileSocialLink.display_order)
    ).all()
    assert [fila[0] for fila in ordenes] == [0, 1, 2]


def test_una_lista_vacia_retira_todos_los_enlaces(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil(enlaces=[("Uno", "https://uno.invalid", 0)]))
    sesion_de_pruebas.flush()

    cliente_administrativo.put(PERFIL, json=_MINIMO)

    total = sesion_de_pruebas.execute(
        select(func.count()).select_from(ProfileSocialLink)
    ).scalar_one()
    assert total == 0


# --- P-04: el perfil no se crea por API ------------------------------------
def test_sin_perfil_la_consulta_responde_404(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.get(PERFIL)

    assert respuesta.status_code == 404
    assert codigo_de_error(respuesta) == "resource_not_found"


def test_sin_perfil_la_edicion_responde_404_y_no_crea_ninguno(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-U**, y la mitad que de verdad importa: **no crea nada**."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.put(PERFIL, json=_MINIMO)

    assert respuesta.status_code == 404
    total = sesion_de_pruebas.execute(select(func.count()).select_from(Profile)).scalar_one()
    assert total == 0


# --- P-06: referencias desconocidas ----------------------------------------
def test_una_foto_desconocida_se_rechaza_sin_tocar_el_perfil(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-J**: `422`, y el nombre del campo en `details`."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil(nombre="Antiguo"))
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(
        PERFIL, json={**_MINIMO, "full_name": "Nuevo", "photo_id": str(uuid.uuid4())}
    )

    assert respuesta.status_code == 422
    assert codigo_de_error(respuesta) == "unknown_reference"
    guardado = sesion_de_pruebas.execute(select(Profile)).scalar_one()
    assert guardado.full_name == "Antiguo"


def test_una_foto_conocida_se_asocia_y_devuelve_su_enlace(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    imagen = medio(clave="medios/perfil/original.png", texto_alternativo="Retrato")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(PERFIL, json={**_MINIMO, "photo_id": str(imagen.id)})

    assert respuesta.status_code == 200
    foto = respuesta.json()["photo"]
    assert foto["id"] == str(imagen.id)
    assert foto["alt_text"] == "Retrato"
    assert foto["access_url"].startswith("http")
    assert "object_key" not in foto


# --- P-05: validacion ------------------------------------------------------
def test_el_perfil_exige_nombre(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(PERFIL, json={**_MINIMO, "full_name": "  "})

    assert respuesta.status_code == 422


def test_una_clave_desconocida_en_el_cuerpo_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Misma postura estricta que `Task/009` y `Task/011`: `extra="forbid"`."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(PERFIL, json={**_MINIMO, "inventado": 1})

    assert respuesta.status_code == 422


# --- AU: auditoria ---------------------------------------------------------
def test_editar_el_perfil_deja_un_evento_de_auditoria(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    actor = administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    fila = perfil()
    sesion_de_pruebas.add(fila)
    sesion_de_pruebas.flush()

    cliente_administrativo.put(PERFIL, json={**_MINIMO, "full_name": "Nuevo"})

    eventos = eventos_de(sesion_de_pruebas, AccionAuditada.PERFIL_ACTUALIZADO.value)
    assert len(eventos) == 1
    evento = eventos[0]
    assert evento.entity_type == ENTIDAD_PERFIL
    assert evento.entity_id == fila.id
    assert evento.actor_id == actor.id
    assert evento.request_id is not None
    assert evento.ip_address is not None


def test_la_auditoria_del_perfil_no_guarda_el_contenido(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-O**: metadatos minimos, nunca el Markdown."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    cliente_administrativo.put(
        PERFIL, json={**_MINIMO, "full_name": "Nuevo", "biography": "SECRETO EN MARKDOWN"}
    )

    evento = eventos_de(sesion_de_pruebas, AccionAuditada.PERFIL_ACTUALIZADO.value)[0]
    assert "SECRETO" not in str(evento.event_metadata)
    assert evento.event_metadata == {}


def test_una_edicion_rechazada_no_deja_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El historial registra lo que **paso**, no lo que se intento."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    cliente_administrativo.put(PERFIL, json={**_MINIMO, "photo_id": str(uuid.uuid4())})

    assert eventos_de(sesion_de_pruebas, AccionAuditada.PERFIL_ACTUALIZADO.value) == []


# --- RG: la vista publica refleja el cambio --------------------------------
def test_la_edicion_se_ve_en_la_api_publica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.10: *"el cambio se refleja en `/quien-soy`, `/contacto` e Inicio"*."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil(nombre="Antiguo"))
    sesion_de_pruebas.flush()

    cliente_administrativo.put(PERFIL, json={**_MINIMO, "full_name": "Nuevo"})

    publico = cliente_administrativo.get("/api/v1/profile")
    assert publico.status_code == 200
    assert publico.json()["full_name"] == "Nuevo"
