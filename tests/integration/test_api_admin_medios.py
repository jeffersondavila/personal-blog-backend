"""Medios administrativos contra PostgreSQL y MinIO reales (matriz M de `Task/012`).

Flujos B.4 y B.5 de USER_FLOWS.md. `api-contracts.md` seccion 4 concede a este
recurso exactamente tres operaciones: *"carga, listado y borrado controlado de
imagenes"*.

Lo que `Task/012` **aporta** y lo que **reutiliza**
---------------------------------------------------

Aporta los tres endpoints HTTP. **No aporta ni una regla de negocio de medios**:
la validacion por decodificacion, la clave no predecible, la miniatura, la
compensacion ante fallo parcial y la comprobacion de uso son de `Task/010`, y se
invocan tal cual. `data-model.md` invariante 12 lo dice por escrito: el
comportamiento vive alli y *"`Task/012` lo expondra por HTTP"*.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import ENTIDAD_MEDIO, AccionAuditada
from app.modules.media.infrastructure.models import MediaAsset
from tests.imagenes import imagen
from tests.integration.administracion import (
    ADMIN,
    administrador_con_sesion,
    codigo_de_error,
    eventos_de,
)
from tests.integration.datos import ANTIGUO, INTERMEDIO, RECIENTE, articulo, medio, perfil

pytestmark = pytest.mark.integration

MEDIOS = f"{ADMIN}/media"


def _subir(cliente: TestClient, *, nombre: str = "foto.png", **datos: str) -> dict[str, object]:
    respuesta = cliente.post(
        MEDIOS,
        files={"archivo": (nombre, imagen(ancho=64, alto=48), "image/png")},
        data=datos,
    )
    assert respuesta.status_code == 201, respuesta.text
    cuerpo: dict[str, object] = respuesta.json()
    return cuerpo


def test_sin_sesion_no_se_gestionan_medios(
    cliente_administrativo_con_medios: TestClient,
) -> None:
    assert cliente_administrativo_con_medios.get(MEDIOS).status_code == 401


# --- M-01: carga -----------------------------------------------------------
def test_una_imagen_valida_se_carga_y_devuelve_sus_metadatos(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.4: el backend valida, almacena y persiste **metadatos y clave**."""
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    cuerpo = _subir(cliente_administrativo_con_medios, alt_text="Un retrato")

    assert cuerpo["original_filename"] == "foto.png"
    assert cuerpo["mime_type"] == "image/png"
    assert cuerpo["width"] == 64
    assert cuerpo["height"] == 48
    assert cuerpo["alt_text"] == "Un retrato"
    assert isinstance(cuerpo["access_url"], str)
    assert cuerpo["access_url"].startswith("http")


def test_la_respuesta_de_carga_no_expone_la_clave_del_objeto(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """Invariante 9 de CONTENT_MODEL.md, tambien para el administrador.

    La clave viaja **dentro** del enlace firmado —es la ruta que se firma y no
    puede omitirse— pero no como campo del contrato.
    """
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    cuerpo = _subir(cliente_administrativo_con_medios)

    assert "object_key" not in cuerpo


def test_la_carga_persiste_la_clave_y_nunca_la_url(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """Invariante 13 de `data-model.md`, comprobada sobre la columna real."""
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    cuerpo = _subir(cliente_administrativo_con_medios)

    fila = sesion_de_pruebas.get(MediaAsset, uuid.UUID(str(cuerpo["id"])))
    assert fila is not None
    assert fila.object_key.startswith("medios/")
    assert "X-Amz-Signature" not in fila.object_key
    assert "http" not in fila.object_key


def test_el_texto_alternativo_es_opcional_al_cargar(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """Decision **D-010-N**, que `Task/012` no cambia."""
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    assert _subir(cliente_administrativo_con_medios)["alt_text"] is None


# --- M-02 y M-03: entradas invalidas ---------------------------------------
def test_un_archivo_que_no_es_imagen_se_rechaza(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """`Task/010` valida **decodificando**, no por la extension ni por el MIME."""
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    respuesta = cliente_administrativo_con_medios.post(
        MEDIOS, files={"archivo": ("falsa.png", b"no soy una imagen", "image/png")}
    )

    assert respuesta.status_code == 422
    assert codigo_de_error(respuesta) == "invalid_image"
    assert sesion_de_pruebas.execute(select(func.count()).select_from(MediaAsset)).scalar_one() == 0


def test_un_formato_no_permitido_se_rechaza_con_415(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """`api-contracts.md` seccion 8: `415` es el tipo MIME no permitido."""
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    respuesta = cliente_administrativo_con_medios.post(
        MEDIOS, files={"archivo": ("animacion.gif", imagen(formato="GIF"), "image/gif")}
    )

    assert respuesta.status_code == 415
    assert codigo_de_error(respuesta) == "unsupported_image_type"


def test_una_peticion_sin_archivo_se_rechaza(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    assert cliente_administrativo_con_medios.post(MEDIOS).status_code == 422


# --- M-04: listado ---------------------------------------------------------
def test_la_biblioteca_se_lista_paginada(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """B.5: *"el administrador consulta la biblioteca de medios ya cargados"*."""
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)
    sesion_de_pruebas.add_all([medio(clave=f"medios/{numero}/original.png") for numero in range(3)])
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo_con_medios.get(MEDIOS, params={"page_size": 2})

    cuerpo = respuesta.json()
    assert set(cuerpo) == {"items", "page", "page_size", "total", "pages"}
    assert cuerpo["total"] == 3
    assert len(cuerpo["items"]) == 2
    assert all("object_key" not in item for item in cuerpo["items"])


def test_el_listado_de_medios_va_del_mas_reciente_al_mas_antiguo(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """La biblioteca se usa para elegir **lo que se acaba de subir**.

    Las fechas se fijan a mano y no se obtienen subiendo dos imagenes seguidas.
    `created_at` lo pone `now()` de PostgreSQL, que es la hora de **inicio de la
    transaccion** (decision D-H), asi que dos cargas dentro de la transaccion de
    la prueba comparten marca y el resultado lo decidiria el desempate por
    `object_key`, que es azar. Se comprobo: la primera version de esta prueba
    fallaba **cuatro de cada seis ejecuciones**.
    """
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)
    sesion_de_pruebas.add_all(
        [
            medio(clave="medios/antiguo/original.png", cargado_el=ANTIGUO),
            medio(clave="medios/reciente/original.png", cargado_el=RECIENTE),
            medio(clave="medios/intermedio/original.png", cargado_el=INTERMEDIO),
        ]
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo_con_medios.get(MEDIOS)

    nombres = [item["access_url"] for item in respuesta.json()["items"]]
    assert "reciente" in nombres[0]
    assert "intermedio" in nombres[1]
    assert "antiguo" in nombres[2]


# --- M-05 y M-06: borrado ---------------------------------------------------
def test_un_medio_libre_se_elimina_con_sus_objetos(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)
    cargado = _subir(cliente_administrativo_con_medios)

    respuesta = cliente_administrativo_con_medios.delete(f"{MEDIOS}/{cargado['id']}")

    assert respuesta.status_code == 204
    assert sesion_de_pruebas.execute(select(func.count()).select_from(MediaAsset)).scalar_one() == 0


def test_un_medio_en_uso_no_se_elimina_y_el_rechazo_dice_donde(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """Invariante 5 de CONTENT_MODEL.md y flujo B.5.

    El comportamiento —incluida la enumeracion de los usos— es de `Task/010`;
    aqui se comprueba que el endpoint lo **expone** sin reimplementarlo.
    """
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)
    cargado = _subir(cliente_administrativo_con_medios)
    imagen_guardada = sesion_de_pruebas.get(MediaAsset, uuid.UUID(str(cargado["id"])))
    sesion_de_pruebas.add(articulo("con-portada", portada=imagen_guardada))
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo_con_medios.delete(f"{MEDIOS}/{cargado['id']}")

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "media_in_use"
    usos = respuesta.json()["error"]["details"]["usos"]
    assert usos == [{"tipo": "post", "slug": "con-portada", "titulo": "Articulo con-portada"}]
    assert sesion_de_pruebas.execute(select(func.count()).select_from(MediaAsset)).scalar_one() == 1


def test_el_uso_desde_el_perfil_tambien_impide_el_borrado(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """El perfil es uno de los cinco origenes de referencia que enumera `Task/010`."""
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)
    cargado = _subir(cliente_administrativo_con_medios)
    imagen_guardada = sesion_de_pruebas.get(MediaAsset, uuid.UUID(str(cargado["id"])))
    sesion_de_pruebas.add(perfil(nombre="Autor", foto=imagen_guardada))
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo_con_medios.delete(f"{MEDIOS}/{cargado['id']}")

    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["details"]["usos"][0]["tipo"] == "profile"


def test_el_rechazo_por_uso_no_filtra_nombres_internos(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """Requisito S-07: ni tablas, ni columnas, ni claves de objeto."""
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)
    cargado = _subir(cliente_administrativo_con_medios)
    imagen_guardada = sesion_de_pruebas.get(MediaAsset, uuid.UUID(str(cargado["id"])))
    sesion_de_pruebas.add(articulo("con-portada", portada=imagen_guardada))
    sesion_de_pruebas.flush()

    cuerpo = cliente_administrativo_con_medios.delete(f"{MEDIOS}/{cargado['id']}").text

    for prohibido in ("media_assets", "cover_id", "object_key", "SELECT", "medios/"):
        assert prohibido not in cuerpo


def test_eliminar_un_medio_inexistente_responde_404(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    assert cliente_administrativo_con_medios.delete(f"{MEDIOS}/{uuid.uuid4()}").status_code == 404


# --- AU: auditoria ---------------------------------------------------------
def test_la_carga_y_el_borrado_dejan_su_evento(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """Regla transversal 3 de USER_FLOWS.md: todo lo que modifica datos se audita."""
    actor = administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)
    cargado = _subir(cliente_administrativo_con_medios)
    cliente_administrativo_con_medios.delete(f"{MEDIOS}/{cargado['id']}")

    for accion in (AccionAuditada.MEDIO_CARGADO, AccionAuditada.MEDIO_ELIMINADO):
        eventos = eventos_de(sesion_de_pruebas, accion.value)
        assert len(eventos) == 1, accion
        assert eventos[0].entity_type == ENTIDAD_MEDIO
        assert eventos[0].entity_id == uuid.UUID(str(cargado["id"]))
        assert eventos[0].actor_id == actor.id
        assert eventos[0].event_metadata == {"original_filename": "foto.png"}


def test_la_auditoria_de_medios_no_guarda_la_clave_del_objeto(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    _subir(cliente_administrativo_con_medios)

    evento = eventos_de(sesion_de_pruebas, AccionAuditada.MEDIO_CARGADO.value)[0]
    assert "medios/" not in str(evento.event_metadata)


def test_un_borrado_rechazado_no_borra_absolutamente_nada(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """Un rechazo por uso deja la fila y sus objetos exactamente como estaban.

    Esta prueba mide lo que **HTTP puede observar**. Que un rechazo tampoco deje
    un evento de auditoria durable depende de que la peticion revierta, y eso lo
    fija `test_fallo_de_auditoria_de_medios.py`, que modela la transaccion con un
    `SAVEPOINT`: aqui no se puede, porque el harness sustituye `get_session` por
    la sesion de la prueba y una peticion fallida **no** revierte.
    """
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)
    cargado = _subir(cliente_administrativo_con_medios)
    identificador = uuid.UUID(str(cargado["id"]))
    imagen_guardada = sesion_de_pruebas.get(MediaAsset, identificador)
    assert imagen_guardada is not None
    clave = imagen_guardada.object_key
    sesion_de_pruebas.add(articulo("con-portada", portada=imagen_guardada))
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo_con_medios.delete(f"{MEDIOS}/{cargado['id']}")

    assert respuesta.status_code == 409
    assert sesion_de_pruebas.get(MediaAsset, identificador) is not None
    assert sesion_de_pruebas.execute(select(func.count()).select_from(MediaAsset)).scalar_one() == 1
    assert clave.startswith("medios/")


# --- El medio cargado es usable de inmediato -------------------------------
def test_un_medio_recien_cargado_puede_usarse_como_portada(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """Recorrido completo de B.4 y B.5: se sube, se selecciona y se ve."""
    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)
    cargado = _subir(cliente_administrativo_con_medios, alt_text="Portada")

    creado = cliente_administrativo_con_medios.post(
        f"{ADMIN}/posts",
        json={
            "title": "Con portada",
            "summary": "Un resumen.",
            "content": "Cuerpo.",
            "cover_id": cargado["id"],
        },
    )

    assert creado.status_code == 201
    assert creado.json()["cover"]["id"] == cargado["id"]
    assert creado.json()["cover"]["alt_text"] == "Portada"
