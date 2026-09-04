"""Comportamiento **comun** a los cuatro tipos publicables (`Task/012`).

Por que este modulo existe
--------------------------

`test_api_admin_articulos.py` fija con detalle el comportamiento comun sobre
`/admin/posts`, y cada uno de los otros tres modulos fija **lo suyo**: la
valoracion de una review, la ausencia de Markdown en un video, los dos estados
de un proyecto.

Falta una tercera cosa: comprobar que ese comportamiento comun **esta de verdad
en los cuatro**. Cada tipo tiene su propio codigo —es la postura de `D-P` y
`D-009-R`, y por eso no hay una base compartida que garantice nada—, asi que
"funciona en artículos" no dice nada sobre los otros tres. Aqui se recorren los
cuatro con la misma tabla.

**No duplica** las pruebas por tipo: aquellas describen diferencias, esta
describe una regla unica aplicada cuatro veces.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.posts.infrastructure.models import Post
from app.modules.projects.infrastructure.models import Project
from app.modules.videos.infrastructure.models import Video
from tests.integration.administracion import ADMIN, administrador_con_sesion, codigo_de_error
from tests.integration.datos import etiqueta, medio

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class TipoAdministrativo:
    """Lo minimo que distingue a un tipo publicable en estas comprobaciones."""

    nombre: str
    ruta: str
    modelo: Any
    #: `cover_id` en tres de los cuatro; el video usa `thumbnail_id`.
    campo_de_imagen: str
    #: Cuerpo que produce un borrador **publicable** de ese tipo.
    #:
    #: Publicable y no minimo: varias de estas comprobaciones necesitan que la
    #: publicacion prospere, y los campos que hacen falta para eso son distintos
    #: en cada tipo (ficha 7.0.3). Que un borrador pueda nacer con **solo** el
    #: titulo se comprueba en el modulo de cada tipo, que es donde toca.
    cuerpo: dict[str, Any]


TIPOS = [
    TipoAdministrativo(
        nombre="articulo",
        ruta=f"{ADMIN}/posts",
        modelo=Post,
        campo_de_imagen="cover_id",
        cuerpo={"title": "Un titulo", "summary": "Resumen.", "content": "Cuerpo."},
    ),
    TipoAdministrativo(
        nombre="review",
        ruta=f"{ADMIN}/book-reviews",
        modelo=BookReview,
        campo_de_imagen="cover_id",
        cuerpo={
            "title": "Un titulo",
            "summary": "Resumen.",
            "content": "Cuerpo.",
            "book_title": "El libro",
            "book_author": "La autora",
            "rating": 4,
        },
    ),
    TipoAdministrativo(
        nombre="video",
        ruta=f"{ADMIN}/videos",
        modelo=Video,
        campo_de_imagen="thumbnail_id",
        cuerpo={
            "title": "Un titulo",
            "summary": "Resumen.",
            "provider": "youtube",
            "video_url": "https://example.invalid/v/1",
        },
    ),
    TipoAdministrativo(
        nombre="proyecto",
        ruta=f"{ADMIN}/projects",
        modelo=Project,
        campo_de_imagen="cover_id",
        cuerpo={"title": "Un titulo", "summary": "Resumen.", "content": "Cuerpo."},
    ),
]

#: Identificadores legibles en la salida de pytest.
IDS = [tipo.nombre for tipo in TIPOS]


def _crear(cliente: TestClient, tipo: TipoAdministrativo, **cambios: Any) -> dict[str, Any]:
    respuesta = cliente.post(tipo.ruta, json={**tipo.cuerpo, **cambios})
    assert respuesta.status_code == 201, respuesta.text
    cuerpo: dict[str, Any] = respuesta.json()
    return cuerpo


# --- Titulo en blanco -------------------------------------------------------
@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_ningun_tipo_admite_un_titulo_en_blanco(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    """`min_length=1` no basta: `"   "` lo satisface y no es un titulo."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(tipo.ruta, json={**tipo.cuerpo, "title": "   "})

    assert respuesta.status_code == 422
    assert (
        sesion_de_pruebas.execute(select(func.count()).select_from(tipo.modelo)).scalar_one() == 0
    )


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_el_titulo_se_guarda_sin_espacios_sobrantes(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert _crear(cliente_administrativo, tipo, title="  Con espacios  ")["title"] == (
        "Con espacios"
    )


# --- Detalle administrativo -------------------------------------------------
@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_el_detalle_administrativo_devuelve_el_borrador(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    """Es lo contrario de la API publica, que nunca devuelve un borrador."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, tipo)

    respuesta = cliente_administrativo.get(f"{tipo.ruta}/{creado['id']}")

    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == creado["id"]
    assert respuesta.json()["status"] == "draft"


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_un_identificador_desconocido_responde_404_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    assert cliente_administrativo.get(f"{tipo.ruta}/{uuid.uuid4()}").status_code == 404


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_publicar_algo_inexistente_responde_404(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(f"{tipo.ruta}/{uuid.uuid4()}/publish")

    assert respuesta.status_code == 404


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_archivar_algo_inexistente_responde_404(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(f"{tipo.ruta}/{uuid.uuid4()}/archive")

    assert respuesta.status_code == 404


# --- Filtro de estado -------------------------------------------------------
@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_el_filtro_de_estado_funciona_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    """`api-contracts.md` seccion 6: `status` es el filtro administrativo."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    borrador = _crear(cliente_administrativo, tipo, slug="borrador")
    publicado = _crear(cliente_administrativo, tipo, slug="publicado")
    cliente_administrativo.post(f"{tipo.ruta}/{publicado['id']}/publish")

    solo_borradores = cliente_administrativo.get(tipo.ruta, params={"status": "draft"})
    solo_publicados = cliente_administrativo.get(tipo.ruta, params={"status": "published"})

    assert [item["id"] for item in solo_borradores.json()["items"]] == [borrador["id"]]
    assert [item["id"] for item in solo_publicados.json()["items"]] == [publicado["id"]]
    assert cliente_administrativo.get(tipo.ruta).json()["total"] == 2


# --- Estabilidad del slug ---------------------------------------------------
@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_el_slug_se_puede_cambiar_mientras_no_se_haya_publicado(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    """`api-contracts.md` seccion 4, y decision **D-012-F**."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, tipo)

    respuesta = cliente_administrativo.put(
        f"{tipo.ruta}/{creado['id']}", json={**tipo.cuerpo, "slug": "slug-nuevo"}
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["slug"] == "slug-nuevo"


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_el_slug_queda_congelado_tras_la_primera_publicacion(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, tipo)
    cliente_administrativo.post(f"{tipo.ruta}/{creado['id']}/publish")

    respuesta = cliente_administrativo.put(
        f"{tipo.ruta}/{creado['id']}", json={**tipo.cuerpo, "slug": "slug-nuevo"}
    )

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "slug_is_immutable"


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_crear_con_un_slug_ocupado_es_conflicto_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    """La unicidad es **por tipo** (D-B), y cada tipo la comprueba con su tabla."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    _crear(cliente_administrativo, tipo, slug="ocupado")

    respuesta = cliente_administrativo.post(tipo.ruta, json={**tipo.cuerpo, "slug": "ocupado"})

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "slug_already_exists"
    assert (
        sesion_de_pruebas.execute(select(func.count()).select_from(tipo.modelo)).scalar_one() == 1
    )


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_editar_hacia_un_slug_ocupado_es_conflicto_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    _crear(cliente_administrativo, tipo, slug="ocupado")
    otro = _crear(cliente_administrativo, tipo, slug="libre")

    respuesta = cliente_administrativo.put(
        f"{tipo.ruta}/{otro['id']}", json={**tipo.cuerpo, "slug": "ocupado"}
    )

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "slug_already_exists"


# --- Etiquetas --------------------------------------------------------------
@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_las_etiquetas_se_asocian_y_se_reemplazan_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    docker = etiqueta("docker")
    linux = etiqueta("linux")
    sesion_de_pruebas.add_all([docker, linux])
    sesion_de_pruebas.flush()

    creado = _crear(cliente_administrativo, tipo, tag_ids=[str(docker.id)])
    assert [item["slug"] for item in creado["tags"]] == ["docker"]

    editado = cliente_administrativo.put(
        f"{tipo.ruta}/{creado['id']}",
        json={**tipo.cuerpo, "slug": creado["slug"], "tag_ids": [str(linux.id)]},
    )
    assert [item["slug"] for item in editado.json()["tags"]] == ["linux"]


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_una_etiqueta_desconocida_se_rechaza_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    inventada = str(uuid.uuid4())

    respuesta = cliente_administrativo.post(tipo.ruta, json={**tipo.cuerpo, "tag_ids": [inventada]})

    assert respuesta.status_code == 422
    assert codigo_de_error(respuesta) == "unknown_reference"
    assert respuesta.json()["error"]["details"]["campo"] == "tag_ids"
    assert (
        sesion_de_pruebas.execute(select(func.count()).select_from(tipo.modelo)).scalar_one() == 0
    )


# --- Imagen -----------------------------------------------------------------
@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_una_imagen_desconocida_se_rechaza_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(
        tipo.ruta, json={**tipo.cuerpo, tipo.campo_de_imagen: str(uuid.uuid4())}
    )

    assert respuesta.status_code == 422
    assert codigo_de_error(respuesta) == "unknown_reference"
    assert respuesta.json()["error"]["details"]["campo"] == tipo.campo_de_imagen


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_una_imagen_conocida_se_asocia_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{tipo.nombre}/original.png", texto_alternativo="Alt")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    creado = _crear(cliente_administrativo, tipo, **{tipo.campo_de_imagen: str(imagen.id)})

    campo = "thumbnail" if tipo.campo_de_imagen == "thumbnail_id" else "cover"
    assert creado[campo]["id"] == str(imagen.id)
    assert creado[campo]["alt_text"] == "Alt"


# --- Edicion y auditoria ----------------------------------------------------
@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_editar_un_publicado_no_cambia_su_estado_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    """USER_FLOWS.md B.3: editar no despublica implicitamente."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = _crear(cliente_administrativo, tipo)
    cliente_administrativo.post(f"{tipo.ruta}/{creado['id']}/publish")

    respuesta = cliente_administrativo.put(
        f"{tipo.ruta}/{creado['id']}",
        json={**tipo.cuerpo, "slug": creado["slug"], "title": "Editado"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "published"
    assert respuesta.json()["title"] == "Editado"


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_editar_algo_inexistente_responde_404_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.put(f"{tipo.ruta}/{uuid.uuid4()}", json=tipo.cuerpo)

    assert respuesta.status_code == 404


@pytest.mark.parametrize("tipo", TIPOS, ids=IDS)
def test_el_destacado_se_administra_en_los_cuatro(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session, tipo: TipoAdministrativo
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    creado = _crear(cliente_administrativo, tipo, featured=True)

    assert creado["featured"] is True
