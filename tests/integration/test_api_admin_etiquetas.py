"""Etiquetas administrativas contra PostgreSQL real (matriz T de `Task/012`).

Flujo B.11 de USER_FLOWS.md: *"el administrador consulta, crea, renombra o
elimina etiquetas. Eliminar una etiqueta en uso requiere confirmacion explicita
y desasocia el contenido; **no elimina contenido**"*.

Dos decisiones propias de este recurso:

- **D-012-S.** El `slug` de una etiqueta es **inmutable** tras crearla. B.11
  habla de *"renombrar"*, que es el nombre visible; el slug aparece en URL
  publicas compartibles (A.9) y la invariante 4 lo declara estable.
- **D-012-T.** La confirmacion de borrado es un paso de **interfaz**
  (`Task/015`). La asimetria esta en las propias fuentes: en B.5 el backend debe
  **rechazar** un medio en uso; en B.11 debe **desasociar**.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import ENTIDAD_ETIQUETA, AccionAuditada
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import Post
from app.modules.tags.infrastructure.models import Tag, post_tags
from tests.integration.administracion import (
    ADMIN,
    administrador_con_sesion,
    codigo_de_error,
    eventos_de,
)
from tests.integration.datos import articulo, etiqueta

pytestmark = pytest.mark.integration

ETIQUETAS = f"{ADMIN}/tags"


def _crear(cliente: TestClient, **cambios: Any) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {"name": "Docker"}
    cuerpo.update(cambios)
    respuesta = cliente.post(ETIQUETAS, json=cuerpo)
    assert respuesta.status_code == 201, respuesta.text
    resultado: dict[str, Any] = respuesta.json()
    return resultado


def test_sin_sesion_no_se_gestionan_etiquetas(cliente_administrativo: TestClient) -> None:
    assert cliente_administrativo.get(ETIQUETAS).status_code == 401
    assert cliente_administrativo.post(ETIQUETAS, json={"name": "x"}).status_code == 401


# --- T-01: crear -----------------------------------------------------------
def test_una_etiqueta_se_crea_con_su_slug_derivado_del_nombre(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo, name="Infraestructura como Código")

    assert cuerpo["slug"] == "infraestructura-como-codigo"
    assert cuerpo["name"] == "Infraestructura como Código"


def test_un_slug_explicito_de_etiqueta_se_respeta(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert _crear(cliente_administrativo, slug="iac")["slug"] == "iac"


def test_una_etiqueta_sin_nombre_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert cliente_administrativo.post(ETIQUETAS, json={"name": "  "}).status_code == 422


# --- T-02: slug duplicado --------------------------------------------------
def test_un_slug_de_etiqueta_duplicado_produce_conflicto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`uq_tags_slug`: la unicidad la garantiza la base; el `409`, la aplicacion."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(etiqueta("docker"))
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.post(ETIQUETAS, json={"name": "Docker"})

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "slug_already_exists"
    assert sesion_de_pruebas.execute(select(func.count()).select_from(Tag)).scalar_one() == 1


# --- T-03: renombrar, con el slug inmutable --------------------------------
def test_una_etiqueta_se_renombra(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.put(
        f"{ETIQUETAS}/{creada['id']}",
        json={"name": "Contenedores", "description": "Todo sobre contenedores."},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["name"] == "Contenedores"
    assert respuesta.json()["description"] == "Todo sobre contenedores."


def test_el_slug_de_una_etiqueta_no_es_un_campo_editable(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-012-S**: el slug aparece en URL publicas compartibles (A.9)."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.put(
        f"{ETIQUETAS}/{creada['id']}", json={"name": "Contenedores", "slug": "otro"}
    )

    assert respuesta.status_code == 422


def test_renombrar_conserva_el_slug(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.put(
        f"{ETIQUETAS}/{creada['id']}", json={"name": "Contenedores"}
    )

    assert respuesta.json()["slug"] == "docker"


def test_renombrar_con_un_nombre_en_blanco_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`min_length=1` no basta: `"   "` lo satisface y no es un nombre."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.put(f"{ETIQUETAS}/{creada['id']}", json={"name": "   "})

    assert respuesta.status_code == 422
    assert sesion_de_pruebas.get(Tag, uuid.UUID(creada["id"])).name == "Docker"  # type: ignore[union-attr]


def test_renombrar_una_etiqueta_inexistente_responde_404(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.put(f"{ETIQUETAS}/{uuid.uuid4()}", json={"name": "x"})

    assert respuesta.status_code == 404


# --- T-04 y T-05: eliminar -------------------------------------------------
def test_una_etiqueta_libre_se_elimina(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    respuesta = cliente_administrativo.delete(f"{ETIQUETAS}/{creada['id']}")

    assert respuesta.status_code == 204
    assert sesion_de_pruebas.execute(select(func.count()).select_from(Tag)).scalar_one() == 0


def test_eliminar_una_etiqueta_en_uso_desasocia_pero_no_borra_contenido(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.11: *"desasocia el contenido; **no elimina contenido**"*.

    Lo garantiza `ON DELETE CASCADE` sobre la **tabla puente** (decision D-J),
    que retira filas de asociacion y nunca contenido. Es la asimetria deliberada
    con los medios: alli el backend rechaza; aqui desasocia.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    docker = etiqueta("docker")
    sesion_de_pruebas.add(docker)
    entrada = articulo("un-articulo", estado=PostStatus.PUBLISHED, etiquetas=[docker])
    sesion_de_pruebas.add(entrada)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.delete(f"{ETIQUETAS}/{docker.id}")

    assert respuesta.status_code == 204
    assert sesion_de_pruebas.execute(select(func.count()).select_from(Tag)).scalar_one() == 0
    assert sesion_de_pruebas.execute(select(func.count()).select_from(Post)).scalar_one() == 1
    assert sesion_de_pruebas.execute(select(func.count()).select_from(post_tags)).scalar_one() == 0


def test_eliminar_una_etiqueta_inexistente_responde_404(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert cliente_administrativo.delete(f"{ETIQUETAS}/{uuid.uuid4()}").status_code == 404


# --- T-06: el listado administrativo ve mas que el publico -----------------
def test_el_listado_administrativo_incluye_etiquetas_sin_contenido_publicado(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El publico solo muestra etiquetas con contenido publicado (D-009-H).

    Aqui es al reves y tiene que serlo: el administrador necesita ver la
    etiqueta que acaba de crear para poder asignarla.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(etiqueta("sin-uso"))
    sesion_de_pruebas.flush()

    administrativo = cliente_administrativo.get(ETIQUETAS)
    publico = cliente_administrativo.get("/api/v1/tags")

    assert [item["slug"] for item in administrativo.json()["items"]] == ["sin-uso"]
    assert publico.json()["items"] == []


def test_el_listado_de_etiquetas_esta_paginado(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add_all([etiqueta(f"etiqueta-{numero}") for numero in range(4)])
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.get(ETIQUETAS, params={"page": 1, "page_size": 2})

    cuerpo = respuesta.json()
    assert set(cuerpo) == {"items", "page", "page_size", "total", "pages"}
    assert cuerpo["total"] == 4
    assert len(cuerpo["items"]) == 2


def test_el_listado_de_etiquetas_va_por_nombre(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Orden alfabetico: es una lista que el administrador **busca a ojo**."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add_all([etiqueta("zeta", nombre="Zeta"), etiqueta("alfa", nombre="Alfa")])
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.get(ETIQUETAS)

    assert [item["name"] for item in respuesta.json()["items"]] == ["Alfa", "Zeta"]


# --- AU: auditoria ---------------------------------------------------------
def test_las_tres_operaciones_dejan_su_evento(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    actor = administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)
    cliente_administrativo.put(f"{ETIQUETAS}/{creada['id']}", json={"name": "Contenedores"})
    cliente_administrativo.delete(f"{ETIQUETAS}/{creada['id']}")

    for accion in (
        AccionAuditada.ETIQUETA_CREADA,
        AccionAuditada.ETIQUETA_ACTUALIZADA,
        AccionAuditada.ETIQUETA_ELIMINADA,
    ):
        eventos = eventos_de(sesion_de_pruebas, accion.value)
        assert len(eventos) == 1, accion
        assert eventos[0].entity_type == ENTIDAD_ETIQUETA
        assert eventos[0].entity_id == uuid.UUID(creada["id"])
        assert eventos[0].actor_id == actor.id
        assert eventos[0].event_metadata == {"slug": "docker"}


def test_el_evento_de_borrado_sobrevive_a_la_etiqueta_borrada(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`data-model.md` 6.1: el historial describe **lo que paso**.

    La referencia polimorfica no tiene clave foranea precisamente para que un
    evento pueda sobrevivir al elemento que describe.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creada = _crear(cliente_administrativo)

    cliente_administrativo.delete(f"{ETIQUETAS}/{creada['id']}")

    evento = eventos_de(sesion_de_pruebas, AccionAuditada.ETIQUETA_ELIMINADA.value)[0]
    assert evento.entity_id == uuid.UUID(creada["id"])
    assert sesion_de_pruebas.get(Tag, uuid.UUID(creada["id"])) is None
