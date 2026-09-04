"""Proyectos administrativos contra PostgreSQL real (matriz PR de `Task/012`).

Lo propio de un proyecto, con su fuente:

- **`project_status` es otra cosa que `status`.** CONTENT_MODEL.md 3.5 advierte
  de no mezclarlos: publicacion y marcha del trabajo son ortogonales, *"un
  proyecto terminado puede estar publicado"* (`data-model.md` D-E).
- `technologies` es una lista de cadenas que **solo se muestra** (D-G).
- `repository_url` y `demo_url` son opcionales, tambien al publicar.
- **No se despublica** (`MVP_SCOPE.md` 3.2).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import ENTIDAD_PROYECTO, AccionAuditada
from app.modules.projects.domain import ProjectStatus, ProjectWorkStatus
from app.modules.projects.infrastructure.models import Project
from tests.integration.administracion import (
    ADMIN,
    administrador_con_sesion,
    codigo_de_error,
    eventos_de,
)
from tests.integration.datos import proyecto

pytestmark = pytest.mark.integration

PROYECTOS = f"{ADMIN}/projects"


def _completo(**cambios: Any) -> dict[str, Any]:
    valores: dict[str, Any] = {
        "title": "Laboratorio casero",
        "summary": "Un resumen breve.",
        "content": "# Cuerpo",
    }
    valores.update(cambios)
    return valores


def _crear(cliente: TestClient, **cambios: Any) -> dict[str, Any]:
    respuesta = cliente.post(PROYECTOS, json=_completo(**cambios))
    assert respuesta.status_code == 201, respuesta.text
    cuerpo: dict[str, Any] = respuesta.json()
    return cuerpo


def test_sin_sesion_no_se_listan_los_proyectos(cliente_administrativo: TestClient) -> None:
    assert cliente_administrativo.get(PROYECTOS).status_code == 401


# --- PR-01: crear con sus valores por defecto reales -----------------------
def test_un_proyecto_nace_como_borrador_activo_y_sin_tecnologias(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`data-model.md` 4.4.1: los *defaults* son valores **semanticamente reales**."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(PROYECTOS, json={"title": "Solo el titulo"})

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "draft"
    assert cuerpo["project_status"] == "active"
    assert cuerpo["technologies"] == []


# --- PR-02: los dos estados no se mezclan ---------------------------------
@pytest.mark.parametrize("marcha", ["active", "paused", "completed"])
def test_el_estado_del_trabajo_se_administra(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, marcha: str
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo, slug=f"proyecto-{marcha}", project_status=marcha)

    assert cuerpo["project_status"] == marcha
    assert cuerpo["status"] == "draft"


def test_un_estado_de_trabajo_inventado_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`ck_projects_project_work_status` admite tres valores (decision D-E)."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(PROYECTOS, json=_completo(project_status="inventado"))

    assert respuesta.status_code == 422


def test_un_proyecto_terminado_puede_estar_publicado(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """CONTENT_MODEL.md 3.5: los dos estados son **ortogonales**."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, project_status="completed")

    respuesta = cliente_administrativo.post(f"{PROYECTOS}/{creado['id']}/publish")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "published"
    assert respuesta.json()["project_status"] == "completed"


# --- PR-03: tecnologias y enlaces -----------------------------------------
def test_las_tecnologias_se_administran_como_lista_ordenada(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision D-G: lista de cadenas en `JSONB`, y el orden se conserva."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo, technologies=["Docker", "Terraform", "Python"])

    assert cuerpo["technologies"] == ["Docker", "Terraform", "Python"]
    guardado = sesion_de_pruebas.execute(select(Project)).scalar_one()
    assert guardado.technologies == ["Docker", "Terraform", "Python"]


def test_las_tecnologias_se_reemplazan_al_editar(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`data-model.md` deuda 8: SQLAlchemy no detecta mutaciones **en sitio** de un `JSONB`.

    Por eso la actualizacion asigna una lista **nueva** en lugar de modificar la
    existente; si no lo hiciera, el cambio no llegaria a persistirse.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, technologies=["Docker"])

    respuesta = cliente_administrativo.put(
        f"{PROYECTOS}/{creado['id']}",
        json=_completo(slug=creado["slug"], technologies=["Ansible", "Bash"]),
    )

    assert respuesta.json()["technologies"] == ["Ansible", "Bash"]
    sesion_de_pruebas.expire_all()
    assert sesion_de_pruebas.execute(select(Project)).scalar_one().technologies == [
        "Ansible",
        "Bash",
    ]


@pytest.mark.parametrize("invalida", ["", "   "])
def test_una_tecnologia_en_blanco_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, invalida: str
) -> None:
    """`JSONB` no impone nada sobre el contenido de la lista (D-G lo acepta).

    Lo impone el contrato de entrada: una cadena vacia dentro de la lista no es
    una tecnologia, y persistirla dejaria un hueco visible en el sitio publico.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(
        PROYECTOS, json=_completo(technologies=["Docker", invalida])
    )

    assert respuesta.status_code == 422


def test_una_tecnologia_desmesurada_se_rechaza(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(PROYECTOS, json=_completo(technologies=["x" * 100]))

    assert respuesta.status_code == 422


def test_las_tecnologias_se_guardan_sin_espacios_sobrantes(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(cliente_administrativo, technologies=["  Docker  "])

    assert cuerpo["technologies"] == ["Docker"]


def test_los_enlaces_del_proyecto_se_administran(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    cuerpo = _crear(
        cliente_administrativo,
        repository_url="https://repo.invalid",
        demo_url="https://demo.invalid",
    )

    assert cuerpo["repository_url"] == "https://repo.invalid"
    assert cuerpo["demo_url"] == "https://demo.invalid"


# --- PR-04: publicacion ----------------------------------------------------
def test_no_se_puede_publicar_un_proyecto_sin_contenido(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, content="")

    respuesta = cliente_administrativo.post(f"{PROYECTOS}/{creado['id']}/publish")

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "cannot_publish_incomplete_draft"
    assert respuesta.json()["error"]["details"]["campos"] == ["content"]


def test_repositorio_y_demo_no_impiden_publicar(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """CONTENT_MODEL.md 3.5 los declara *"opcional"* a los dos."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    assert cliente_administrativo.post(f"{PROYECTOS}/{creado['id']}/publish").status_code == 200


def test_el_proyecto_no_tiene_ruta_de_despublicacion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """`MVP_SCOPE.md` 3.2: los proyectos se archivan, no se despublican."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    cliente_administrativo.post(f"{PROYECTOS}/{creado['id']}/publish")

    respuesta = cliente_administrativo.post(f"{PROYECTOS}/{creado['id']}/unpublish")

    assert respuesta.status_code == 404


def test_un_proyecto_se_archiva_conservando_la_fecha(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)
    publicado = cliente_administrativo.post(f"{PROYECTOS}/{creado['id']}/publish").json()

    respuesta = cliente_administrativo.post(f"{PROYECTOS}/{creado['id']}/archive")

    assert respuesta.json()["status"] == "archived"
    assert respuesta.json()["published_at"] == publicado["published_at"]


def test_no_existe_forma_de_eliminar_un_proyecto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo)

    assert cliente_administrativo.delete(f"{PROYECTOS}/{creado['id']}").status_code == 405


# --- PR-05: listado, auditoria y vista publica -----------------------------
def test_el_listado_administrativo_incluye_los_tres_estados(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add_all(
        [
            proyecto("borrador", estado=ProjectStatus.DRAFT),
            proyecto("publicado", estado=ProjectStatus.PUBLISHED),
            proyecto("archivado", estado=ProjectStatus.ARCHIVED, marcha=ProjectWorkStatus.PAUSED),
        ]
    )
    sesion_de_pruebas.flush()

    assert cliente_administrativo.get(PROYECTOS).json()["total"] == 3


def test_un_proyecto_desconocido_responde_404(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert cliente_administrativo.get(f"{PROYECTOS}/{uuid.uuid4()}").status_code == 404


def test_la_auditoria_de_un_proyecto_apunta_a_su_tipo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    creado = _crear(cliente_administrativo)

    evento = eventos_de(sesion_de_pruebas, AccionAuditada.CONTENIDO_CREADO.value)[0]
    assert evento.entity_type == ENTIDAD_PROYECTO
    assert evento.entity_id == uuid.UUID(creado["id"])


def test_publicar_un_proyecto_lo_hace_visible_en_la_api_publica(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, technologies=["Docker"])

    cliente_administrativo.post(f"{PROYECTOS}/{creado['id']}/publish")

    publico = cliente_administrativo.get(f"/api/v1/projects/{creado['slug']}")
    assert publico.status_code == 200
    assert publico.json()["technologies"] == ["Docker"]
