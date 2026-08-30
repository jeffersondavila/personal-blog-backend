"""API publica de articulos, contra PostgreSQL real (matriz B y C).

Estas pruebas son la **defensa principal de la invariante 19** de
`data-model.md`: *"contenido no publicado nunca sale al publico"*. `Task/008`
la dejo explicitamente asignada a `Task/009` porque es una regla de **consulta**
y ninguna restriccion de esquema puede imponerla.

Por que aqui y no en `tests/contract/`: lo que se comprueba depende del filtro
real que ejecuta PostgreSQL, de un `JOIN` sobre la tabla puente de etiquetado,
del `ORDER BY` con desempate y del `COUNT` sobre el conjunto filtrado. Ninguna
de esas cosas se demuestra con un doble
(BACKEND_TESTING_STRATEGY.md seccion 8.3).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.posts.domain import PostStatus
from app.shared.pagination import PAGE_SIZE_MAXIMO, PAGE_SIZE_POR_DEFECTO
from tests.integration.datos import (
    ANTIGUO,
    INTERMEDIO,
    RECIENTE,
    articulo,
    etiqueta,
    medio,
)

pytestmark = pytest.mark.integration

LISTADO = "/api/v1/posts"


def _slugs(respuesta: Any) -> list[str]:
    cuerpo: dict[str, Any] = respuesta.json()
    return [elemento["slug"] for elemento in cuerpo["items"]]


# --- B-01, B-02, B-03: solo contenido publicado ----------------------------
def test_el_listado_solo_devuelve_articulos_publicados(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("publicado", estado=PostStatus.PUBLISHED),
            articulo("borrador", estado=PostStatus.DRAFT),
            articulo("archivado", estado=PostStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(LISTADO)

    assert respuesta.status_code == 200
    assert _slugs(respuesta) == ["publicado"]


def test_un_borrador_previamente_publicado_tampoco_aparece(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Despublicar conserva `published_at` (USER_FLOWS.md B.8).

    Si la consulta filtrara por "tiene fecha de publicacion" en lugar de por
    `status`, este articulo volveria a ser visible. El caso existe porque el
    esquema permite —correctamente— un `draft` con fecha.
    """
    sesion_de_pruebas.add(articulo("despublicado", estado=PostStatus.DRAFT, publicado_el=RECIENTE))
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(LISTADO)) == []


# --- B-04, B-05: orden -----------------------------------------------------
def test_el_orden_por_defecto_es_por_fecha_descendente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("medio", publicado_el=INTERMEDIO),
            articulo("viejo", publicado_el=ANTIGUO),
            articulo("nuevo", publicado_el=RECIENTE),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(LISTADO)) == ["nuevo", "medio", "viejo"]


def test_el_empate_de_fecha_se_desempata_de_forma_estable(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """D-009-F. Sin desempate total, el `OFFSET` puede repetir y perder filas."""
    sesion_de_pruebas.add_all(
        [articulo(slug, publicado_el=RECIENTE) for slug in ("cereza", "arandano", "banana")]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(LISTADO)) == ["arandano", "banana", "cereza"]


def test_el_desempate_mantiene_las_paginas_disjuntas(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Con todas las fechas iguales, dos paginas no pueden solaparse."""
    sesion_de_pruebas.add_all(
        [articulo(f"articulo-{indice}", publicado_el=RECIENTE) for indice in range(5)]
    )
    sesion_de_pruebas.flush()

    primera = _slugs(cliente_de_la_api.get(LISTADO, params={"page": 1, "page_size": 2}))
    segunda = _slugs(cliente_de_la_api.get(LISTADO, params={"page": 2, "page_size": 2}))
    tercera = _slugs(cliente_de_la_api.get(LISTADO, params={"page": 3, "page_size": 2}))

    assert len(primera) == 2
    assert len(segunda) == 2
    assert len(tercera) == 1
    assert len(set(primera + segunda + tercera)) == 5


# --- B-10: sort ------------------------------------------------------------
@pytest.mark.parametrize(
    ("sort", "esperado"),
    [
        ("title", ["a", "b", "c"]),
        ("-title", ["c", "b", "a"]),
        ("published_at", ["c", "b", "a"]),
        ("-published_at", ["a", "b", "c"]),
    ],
)
def test_el_orden_alternativo_funciona_en_ambas_direcciones(
    sesion_de_pruebas: Session,
    cliente_de_la_api: TestClient,
    sort: str,
    esperado: list[str],
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("a", titulo="Alfa", publicado_el=RECIENTE),
            articulo("b", titulo="Beta", publicado_el=INTERMEDIO),
            articulo("c", titulo="Gamma", publicado_el=ANTIGUO),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(LISTADO, params={"sort": sort})) == esperado


# --- B-06, B-07, I-03, I-05, I-06, I-07: paginacion ------------------------
def test_la_envoltura_de_paginacion_es_coherente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [articulo(f"articulo-{indice}", publicado_el=RECIENTE) for indice in range(5)]
    )
    sesion_de_pruebas.flush()

    cuerpo: dict[str, Any] = cliente_de_la_api.get(
        LISTADO, params={"page": 1, "page_size": 2}
    ).json()

    assert len(cuerpo["items"]) == 2
    assert cuerpo["page"] == 1
    assert cuerpo["page_size"] == 2
    # `total` cuenta el conjunto filtrado completo, no lo devuelto tras el LIMIT.
    assert cuerpo["total"] == 5
    assert cuerpo["pages"] == 3


def test_una_pagina_fuera_de_rango_devuelve_una_coleccion_vacia(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """api-contracts.md seccion 5: `200` con `items` vacio, nunca `404`."""
    sesion_de_pruebas.add(articulo("unico"))
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(LISTADO, params={"page": 99})

    assert respuesta.status_code == 200
    cuerpo: dict[str, Any] = respuesta.json()
    assert cuerpo["items"] == []
    assert cuerpo["total"] == 1


def test_sin_contenido_no_hay_ninguna_pagina(cliente_de_la_api: TestClient) -> None:
    cuerpo: dict[str, Any] = cliente_de_la_api.get(LISTADO).json()

    assert cuerpo["items"] == []
    assert cuerpo["total"] == 0
    assert cuerpo["pages"] == 0
    assert cuerpo["page_size"] == PAGE_SIZE_POR_DEFECTO


def test_un_tamano_de_pagina_excesivo_se_recorta_al_maximo(
    cliente_de_la_api: TestClient,
) -> None:
    """No es un error, y el valor devuelto es el **aplicado**, no el pedido."""
    respuesta = cliente_de_la_api.get(LISTADO, params={"page_size": PAGE_SIZE_MAXIMO + 500})

    assert respuesta.status_code == 200
    assert respuesta.json()["page_size"] == PAGE_SIZE_MAXIMO


# --- B-08, B-12, B-13: filtro por etiqueta ---------------------------------
def test_el_filtro_por_etiqueta_usa_las_asociaciones_reales(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    docker = etiqueta("docker")
    sesion_de_pruebas.add_all(
        [
            articulo("con-docker", etiquetas=[docker], publicado_el=RECIENTE),
            articulo("tambien-docker", etiquetas=[docker], publicado_el=INTERMEDIO),
            articulo("sin-docker", publicado_el=ANTIGUO),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(LISTADO, params={"tag": "docker"})) == [
        "con-docker",
        "tambien-docker",
    ]


def test_una_etiqueta_inexistente_devuelve_una_coleccion_vacia(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """D-009-H: `tag` es un filtro de coleccion, no un segmento de ruta."""
    sesion_de_pruebas.add(articulo("cualquiera"))
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(LISTADO, params={"tag": "no-existe"})

    assert respuesta.status_code == 200
    assert respuesta.json()["items"] == []


def test_el_filtro_por_etiqueta_no_saca_borradores_ni_archivados(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Una etiqueta compartida no puede convertirse en un canal de fuga."""
    compartida = etiqueta("compartida")
    sesion_de_pruebas.add_all(
        [
            articulo("visible", etiquetas=[compartida], estado=PostStatus.PUBLISHED),
            articulo("oculto", etiquetas=[compartida], estado=PostStatus.DRAFT),
            articulo("retirado", etiquetas=[compartida], estado=PostStatus.ARCHIVED),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(LISTADO, params={"tag": "compartida"})) == ["visible"]


# --- B-09: featured --------------------------------------------------------
@pytest.mark.parametrize(("valor", "esperado"), [("true", ["destacado"]), ("false", ["normal"])])
def test_el_filtro_de_destacados_es_un_filtro_booleano_completo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, valor: str, esperado: list[str]
) -> None:
    """D-009-G: `false` significa "solo los no destacados", no "sin filtro"."""
    sesion_de_pruebas.add_all(
        [articulo("destacado", destacado=True), articulo("normal", destacado=False)]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(LISTADO, params={"featured": valor})) == esperado


def test_omitir_destacado_no_filtra(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("destacado", destacado=True, publicado_el=RECIENTE),
            articulo("normal", destacado=False, publicado_el=ANTIGUO),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs(cliente_de_la_api.get(LISTADO)) == ["destacado", "normal"]


# --- Forma del elemento de listado -----------------------------------------
def test_el_elemento_de_listado_lleva_lo_que_la_pantalla_necesita(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """USER_FLOWS.md A.2: titulo, resumen, fecha, portada y etiquetas."""
    portada = medio(clave="portadas/uno.png", texto_alternativo="Una portada", ancho=800, alto=600)
    sesion_de_pruebas.add(
        articulo(
            "completo",
            titulo="Titulo visible",
            resumen="Resumen breve",
            contenido="# Cuerpo",
            etiquetas=[etiqueta("docker")],
            portada=portada,
            publicado_el=RECIENTE,
        )
    )
    sesion_de_pruebas.flush()

    elemento: dict[str, Any] = cliente_de_la_api.get(LISTADO).json()["items"][0]

    assert elemento["slug"] == "completo"
    assert elemento["title"] == "Titulo visible"
    assert elemento["summary"] == "Resumen breve"
    assert elemento["published_at"].startswith("2026-08-01T12:00:00")
    assert elemento["tags"] == [{"slug": "docker", "name": "Docker", "description": None}]
    # `access_url` se anade en `Task/010` (D-009-O, cerrada). Se compara la parte
    # estable campo a campo y el enlace por separado: su valor lleva una firma y
    # una marca de tiempo, asi que no puede escribirse literal en una expectativa.
    portada_publica = elemento["cover"]
    assert portada_publica["alt_text"] == "Una portada"
    assert (portada_publica["width"], portada_publica["height"]) == (800, 600)
    assert set(portada_publica) == {"alt_text", "width", "height", "access_url"}
    assert portada_publica["access_url"].startswith("http")


def test_el_listado_no_transporta_el_markdown_completo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """D-009-P: cargar el cuerpo de 12 filas para mostrar resumenes viola P-08."""
    sesion_de_pruebas.add(articulo("uno", contenido="# Un cuerpo largo"))
    sesion_de_pruebas.flush()

    elemento: dict[str, Any] = cliente_de_la_api.get(LISTADO).json()["items"][0]

    assert "content" not in elemento


def test_el_listado_no_expone_campos_internos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(articulo("uno"))
    sesion_de_pruebas.flush()

    elemento: dict[str, Any] = cliente_de_la_api.get(LISTADO).json()["items"][0]

    for interno in ("id", "status", "created_at", "updated_at", "cover_id", "featured"):
        assert interno not in elemento, f"el listado publico expone {interno!r}"


def test_la_portada_no_expone_la_clave_del_objeto(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """D-009-O e invariante 9 de CONTENT_MODEL.md, **precisada en `Task/010`**.

    La invariante 9 prohibe exponer claves internas de objeto *"sin control"*, y
    hasta `Task/010` esta prueba lo comprobaba de la forma mas simple posible:
    que la clave no apareciera en ninguna parte del cuerpo. Con el campo de
    acceso ya presente eso deja de ser expresable, y no por un descuido:

    Una URL prefirmada **es** `<endpoint>/<bucket>/<object_key>?X-Amz-...`. No
    existe ninguna variante del mecanismo que omita la clave; es la ruta del
    recurso que se esta firmando. Y el mecanismo no es opcional:
    `CONTENT_MODEL.md` seccion 3.7 y `security-boundaries.md` lo imponen —el
    navegador alcanza el almacenamiento *"unicamente mediante URL prefirmada
    emitida por el backend"*—.

    La garantia real, que es la que esta prueba fija ahora (decision D-010-Q):

    1. **Ningun campo del contrato transporta la clave** como dato reutilizable.
       Eso es lo que la invariante 9 protege y lo que convertiria la clave en
       parte del contrato `v1`.
    2. Fuera del enlace firmado, la clave **no aparece**.
    3. Conocerla no da acceso: el bucket es privado, hace falta la firma, y las
       claves son no predecibles (D-010-G), asi que ver una no permite adivinar
       otra.
    """
    sesion_de_pruebas.add(articulo("con-portada", portada=medio(clave="portadas/secreta.png")))
    sesion_de_pruebas.flush()

    cuerpo: dict[str, Any] = cliente_de_la_api.get(LISTADO).json()

    portada = cuerpo["items"][0]["cover"]
    assert "object_key" not in portada
    # La clave viaja dentro del enlace firmado, y solo ahi.
    assert "portadas/secreta.png" in portada["access_url"]
    sin_enlaces = json.dumps(cuerpo).replace(portada["access_url"], "")
    assert "portadas/secreta.png" not in sin_enlaces
    assert "object_key" not in sin_enlaces


# --- C-01..C-04: detalle ---------------------------------------------------
def test_el_detalle_de_un_articulo_publicado_incluye_cuerpo_y_seo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(
        articulo(
            "publicado",
            titulo="Un articulo",
            contenido="# Titulo\n\nCuerpo en Markdown.",
            publicado_el=RECIENTE,
        )
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(f"{LISTADO}/publicado")

    assert respuesta.status_code == 200
    cuerpo: dict[str, Any] = respuesta.json()
    assert cuerpo["slug"] == "publicado"
    # Markdown **fuente**: `Task/009` no renderiza (ADR-005).
    assert cuerpo["content"] == "# Titulo\n\nCuerpo en Markdown."
    assert "seo_title" in cuerpo
    assert "seo_description" in cuerpo
    assert cuerpo["reading_time_minutes"] == 1


def test_un_slug_inexistente_devuelve_404(cliente_de_la_api: TestClient) -> None:
    respuesta = cliente_de_la_api.get(f"{LISTADO}/no-existe")

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "resource_not_found"


@pytest.mark.parametrize("estado", [PostStatus.DRAFT, PostStatus.ARCHIVED])
def test_un_articulo_no_publicado_es_indistinguible_de_uno_inexistente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, estado: PostStatus
) -> None:
    """La regla de no filtracion de api-contracts.md seccion 3.

    No basta con que ambos devuelvan `404`: el cuerpo tambien debe coincidir.
    Un mensaje distinto seria suficiente para enumerar borradores probando slugs.
    """
    sesion_de_pruebas.add(articulo("secreto", estado=estado))
    sesion_de_pruebas.flush()

    oculto = cliente_de_la_api.get(f"{LISTADO}/secreto")
    inexistente = cliente_de_la_api.get(f"{LISTADO}/jamas-existio")

    assert oculto.status_code == inexistente.status_code == 404

    def _comparable(respuesta: Any) -> dict[str, Any]:
        error = dict(respuesta.json()["error"])
        # El correlation ID cambia en cada peticion por diseno.
        error.pop("request_id")
        return error

    assert _comparable(oculto) == _comparable(inexistente)


# --- B-14: ausencia de N+1 -------------------------------------------------
def test_el_listado_no_multiplica_consultas_por_fila(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Requisito P-08: los listados evitan consultas N+1.

    Se compara el numero de consultas de un listado de 2 filas con el de 10.
    Un numero **constante** demuestra que las etiquetas y la portada se cargan
    con una estrategia explicita y no una consulta por fila. Se compara en lugar
    de fijar un numero absoluto para que la prueba no se rompa por un cambio
    interno de SQLAlchemy que no sea una regresion.

    Cada lote lleva su propia etiqueta y se consulta filtrando por ella: asi los
    dos listados son independientes sin tener que borrar filas entre medias, y
    ambos ejecutan exactamente la misma forma de consulta.
    """
    from sqlalchemy import event

    def _consultas_para(cantidad: int, marca: str) -> int:
        propia = etiqueta(marca)
        sesion_de_pruebas.add_all(
            [
                articulo(
                    f"{marca}-{indice}",
                    etiquetas=[propia],
                    portada=medio(clave=f"{marca}/{indice}.png"),
                    publicado_el=RECIENTE,
                )
                for indice in range(cantidad)
            ]
        )
        sesion_de_pruebas.flush()

        ejecutadas: list[str] = []

        def _registrar(conexion: Any, cursor: Any, sentencia: str, *resto: Any) -> None:
            ejecutadas.append(sentencia)

        event.listen(sesion_de_pruebas.bind, "before_cursor_execute", _registrar)
        try:
            respuesta = cliente_de_la_api.get(LISTADO, params={"tag": marca, "page_size": 50})
            assert len(respuesta.json()["items"]) == cantidad
        finally:
            event.remove(sesion_de_pruebas.bind, "before_cursor_execute", _registrar)
        return len(ejecutadas)

    con_dos = _consultas_para(2, "pocos")
    con_diez = _consultas_para(10, "muchos")

    # Guarda anti-tautologia: si no se ejecutara ninguna consulta —porque el
    # estado siguiera en memoria— la igualdad de abajo se cumpliria sin haber
    # medido nada.
    assert con_dos >= 3, (
        f"el listado solo ejecuto {con_dos} consultas: se esperaban al menos el "
        "conteo, la pagina y la carga de etiquetas. Con menos, esta prueba no "
        "esta observando la estrategia de carga."
    )

    assert con_dos == con_diez, (
        f"el listado ejecuto {con_dos} consultas con 2 filas y {con_diez} con 10: "
        "el numero crece con las filas, que es la firma de un N+1 (requisito P-08)."
    )
