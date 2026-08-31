"""Acceso publico a los medios: cierre de **D-009-O**.

Que dejo abierto `Task/009`
---------------------------

`MedioPublico` salio con `alt_text`, `width` y `height` y **sin campo de
acceso**, porque la forma de ese acceso —bucket privado, URL prefirmada,
expiracion— era de `Task/010`. Tres documentos vigentes lo dicen con las mismas
palabras: `api-contracts.md` seccion 11, `data-model.md` seccion 10 punto 10 y
la decision **D-009-O** de la ficha de `Task/009`.

Que cierra `Task/010` y que no
------------------------------

| Aqui, en `Task/010` | En `Task/030` (**D-08**) |
| --- | --- |
| Que exista un campo de acceso y cual es su forma | Si hay una URL **estable** |
| Que se genere al servir y nunca se persista | La semantica de cache y el CDN |
| Que el TTL sea configuracion | El **valor** productivo del TTL |
| Que ningun campo transporte `object_key` (D-010-Q) | Bucket, CORS, *lifecycle* |
| — | Que URL usa `og:image` (`Task/016`) |

El cambio es **compatible**: se anade un campo opcional, no se retira ni se
renombra ninguno (api-contracts.md seccion 10, regla 3).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.media.infrastructure.models import MediaAsset
from tests.integration import datos

pytestmark = pytest.mark.integration

#: Los cinco DTO publicos que anidan un medio, con el nombre del campo.
RECURSOS_CON_MEDIO = [
    ("/api/v1/posts/con-medio", "cover"),
    ("/api/v1/book-reviews/con-medio", "cover"),
    ("/api/v1/projects/con-medio", "cover"),
]


def _sin_los_enlaces_firmados(cuerpo: Any) -> str:
    """Serializa la respuesta retirando el valor de cada `access_url`.

    Lo que queda es todo lo que el contrato transporta **como dato**. Si la
    clave del objeto aparece ahi, se esta filtrando de verdad.
    """
    enlaces: list[str] = []

    def _recorrer(nodo: Any) -> None:
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                if clave == "access_url" and isinstance(valor, str):
                    enlaces.append(valor)
                else:
                    _recorrer(valor)
        elif isinstance(nodo, list):
            for elemento in nodo:
                _recorrer(elemento)

    _recorrer(cuerpo)
    texto = json.dumps(cuerpo)
    for enlace in enlaces:
        texto = texto.replace(enlace, "")
    return texto


def _crear_contenido_con_portada(sesion: Session) -> MediaAsset:
    medio = datos.medio(
        clave="medios/1f0c1c62-0000-4000-8000-000000000001/original.png",
        texto_alternativo="Una portada",
        ancho=1200,
        alto=800,
    )
    articulo = datos.articulo("con-medio", titulo="Con medio", portada=medio)
    review = datos.review("con-medio", titulo="Review con medio")
    review.cover = medio
    proyecto = datos.proyecto("con-medio", titulo="Proyecto con medio")
    proyecto.cover = medio
    creado = datos.video("con-medio", titulo="Video con medio")
    creado.thumbnail = medio
    sesion.add_all([medio, articulo, review, proyecto, creado, datos.perfil(foto=medio)])
    sesion.flush()
    return medio


# --- A-01 ------------------------------------------------------------------
def test_la_portada_publica_trae_enlace_de_acceso(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    _crear_contenido_con_portada(sesion_de_pruebas)

    cuerpo = cliente_de_la_api.get("/api/v1/posts/con-medio").json()

    assert cuerpo["cover"]["access_url"].startswith("http")
    assert "X-Amz-Signature" in cuerpo["cover"]["access_url"]


def test_el_enlace_convive_con_los_campos_que_ya_existian(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """El cambio es compatible: `Task/009` no pierde nada."""
    _crear_contenido_con_portada(sesion_de_pruebas)

    portada = cliente_de_la_api.get("/api/v1/posts/con-medio").json()["cover"]

    assert portada["alt_text"] == "Una portada"
    assert (portada["width"], portada["height"]) == (1200, 800)


# --- A-02 ------------------------------------------------------------------
@pytest.mark.parametrize(
    "ruta",
    [
        "/api/v1/posts",
        "/api/v1/posts/con-medio",
        "/api/v1/book-reviews",
        "/api/v1/book-reviews/con-medio",
        "/api/v1/videos",
        "/api/v1/projects",
        "/api/v1/projects/con-medio",
        "/api/v1/profile",
    ],
)
def test_la_clave_del_objeto_no_aparece_fuera_del_enlace_firmado(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session, ruta: str
) -> None:
    """Invariante 9 de CONTENT_MODEL.md, **precisada en `Task/010`** (D-010-Q).

    Una URL prefirmada **es** `<endpoint>/<bucket>/<object_key>?X-Amz-...`: la
    clave es la ruta del recurso que se firma, y no hay variante del mecanismo
    que la omita. El mecanismo tampoco es opcional —`CONTENT_MODEL.md` 3.7 y
    `security-boundaries.md` lo imponen—, asi que "la clave no aparece en el
    cuerpo" dejo de ser una afirmacion que pueda sostenerse.

    Lo que si se sostiene, y es lo que la invariante protege al decir *"sin
    control"*: **ningun campo del contrato la transporta como dato**, y fuera
    del enlace firmado no aparece. Se inspecciona el JSON entero en texto —tras
    retirar los enlaces— y no campo a campo: un campo nuevo que la filtrara se
    detecta sin que nadie tenga que acordarse de anadirlo a una lista.
    """
    medio = _crear_contenido_con_portada(sesion_de_pruebas)

    respuesta = cliente_de_la_api.get(ruta)

    assert respuesta.status_code == 200
    texto = _sin_los_enlaces_firmados(respuesta.json())
    assert medio.object_key not in texto
    assert "object_key" not in texto
    assert "medios/" not in texto
    assert "bucket" not in texto.lower()


def test_la_prueba_anterior_mira_un_cuerpo_que_de_verdad_lleva_el_medio(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """Guarda anti-tautologia doble.

    Primero: si el medio no llegara a la respuesta, no encontrar su clave no
    demostraria nada. Segundo: si `_sin_los_enlaces_firmados` no encontrara los
    enlaces, retiraria de menos y la prueba anterior seria demasiado estricta;
    si retirara de mas —por ejemplo, el cuerpo entero— seria vacia. Aqui se
    comprueba que la clave **si** esta dentro del enlace, que es lo unico que
    hace util retirarlo.
    """
    medio = _crear_contenido_con_portada(sesion_de_pruebas)

    cuerpo = cliente_de_la_api.get("/api/v1/posts/con-medio").json()

    assert cuerpo["cover"] is not None
    assert medio.object_key in cuerpo["cover"]["access_url"]
    assert len(_sin_los_enlaces_firmados(cuerpo)) > 0


# --- A-03 ------------------------------------------------------------------
def test_la_url_emitida_no_se_persiste(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """Regla ya vigente de **D-08**: nunca se persiste una URL prefirmada.

    Caduca, asi que persistirla produciria enlaces muertos. Se comprueba sobre
    las **columnas reales** de la fila, despues de haber servido la respuesta.
    """
    medio = _crear_contenido_con_portada(sesion_de_pruebas)
    emitida = cliente_de_la_api.get("/api/v1/posts/con-medio").json()["cover"]["access_url"]

    sesion_de_pruebas.expire_all()
    fila = sesion_de_pruebas.get(MediaAsset, medio.id)

    assert fila is not None
    valores = [getattr(fila, columna.name) for columna in MediaAsset.__table__.columns]
    assert emitida not in [valor for valor in valores if isinstance(valor, str)]
    assert not any(isinstance(v, str) and v.startswith("http") for v in valores)


# --- A-04 ------------------------------------------------------------------
def test_un_contenido_sin_portada_sigue_devolviendo_null(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    sesion_de_pruebas.add(datos.articulo("sin-medio", titulo="Sin medio"))
    sesion_de_pruebas.flush()

    cuerpo = cliente_de_la_api.get("/api/v1/posts/sin-medio").json()

    assert cuerpo["cover"] is None


# --- A-05 ------------------------------------------------------------------
@pytest.mark.parametrize(("ruta", "campo"), RECURSOS_CON_MEDIO)
def test_los_detalles_que_anidan_un_medio_llevan_el_mismo_campo(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session, ruta: str, campo: str
) -> None:
    _crear_contenido_con_portada(sesion_de_pruebas)

    medio_publico = cliente_de_la_api.get(ruta).json()[campo]

    assert set(medio_publico) == {"alt_text", "width", "height", "access_url"}
    assert medio_publico["access_url"].startswith("http")


def test_el_video_y_el_perfil_tambien_llevan_el_campo(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """`Video` usa `thumbnail` y `Profile` usa `photo`: los otros dos de los cinco."""
    _crear_contenido_con_portada(sesion_de_pruebas)

    video: dict[str, Any] = cliente_de_la_api.get("/api/v1/videos").json()["items"][0]
    perfil: dict[str, Any] = cliente_de_la_api.get("/api/v1/profile").json()

    assert video["thumbnail"]["access_url"].startswith("http")
    assert perfil["photo"]["access_url"].startswith("http")


def test_el_listado_emite_un_enlace_por_elemento(
    cliente_de_la_api: TestClient, sesion_de_pruebas: Session
) -> None:
    """Cada elemento del listado necesita el suyo, y todos deben ser distintos:
    un enlace compartido significaria que apuntan al mismo objeto."""
    for indice in range(3):
        medio = datos.medio(
            clave=f"medios/1f0c1c62-0000-4000-8000-00000000000{indice + 2}/original.png"
        )
        sesion_de_pruebas.add(datos.articulo(f"listado-{indice}", portada=medio))
    sesion_de_pruebas.flush()

    elementos = cliente_de_la_api.get("/api/v1/posts").json()["items"]

    enlaces = {elemento["cover"]["access_url"] for elemento in elementos}
    assert len(enlaces) == 3
