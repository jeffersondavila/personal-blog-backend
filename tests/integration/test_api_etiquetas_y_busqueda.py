"""API publica de etiquetas y de busqueda (matriz G y H).

Los dos endpoints comparten el mismo riesgo, y es el mas serio de `Task/009`:
son los unicos que **atraviesan los cuatro tipos de contenido a la vez**, asi
que un olvido de la condicion de publicacion en cualquiera de las ramas abre una
via para inferir —o leer— lo que hay en el panel.

Por eso los casos negativos no son un extra: son el objeto de la prueba. Se
construyen escenarios donde el termino buscado o la etiqueta existen **solo** en
contenido no publicado, de modo que cualquier fuga se manifieste como un
resultado que no deberia estar.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.posts.domain import PostStatus
from app.modules.projects.domain import ProjectStatus
from app.modules.videos.domain import VideoStatus
from tests.integration.datos import (
    ANTIGUO,
    INTERMEDIO,
    RECIENTE,
    articulo,
    etiqueta,
    proyecto,
    review,
    video,
)

pytestmark = pytest.mark.integration

ETIQUETAS = "/api/v1/tags"
BUSQUEDA = "/api/v1/search"


def _slugs_de_etiquetas(respuesta: Any) -> list[str]:
    cuerpo: dict[str, Any] = respuesta.json()
    return [elemento["slug"] for elemento in cuerpo["items"]]


def _resultados(respuesta: Any) -> list[tuple[str, str]]:
    cuerpo: dict[str, Any] = respuesta.json()
    return [(elemento["type"], elemento["slug"]) for elemento in cuerpo["items"]]


# --- G: catalogo de etiquetas ----------------------------------------------
def test_una_etiqueta_con_contenido_publicado_aparece(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    usada = etiqueta("docker", nombre="Docker", descripcion="Contenedores")
    sesion_de_pruebas.add(articulo("uno", etiquetas=[usada]))
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(ETIQUETAS)

    assert respuesta.status_code == 200
    assert respuesta.json()["items"] == [
        {"slug": "docker", "name": "Docker", "description": "Contenedores"}
    ]


def test_una_etiqueta_sin_contenido_no_aparece(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Una etiqueta huerfana no es "disponible": no lleva a ninguna parte."""
    sesion_de_pruebas.add(etiqueta("huerfana"))
    sesion_de_pruebas.flush()

    assert _slugs_de_etiquetas(cliente_de_la_api.get(ETIQUETAS)) == []


@pytest.mark.parametrize("estado", [PostStatus.DRAFT, PostStatus.ARCHIVED])
def test_una_etiqueta_usada_solo_por_contenido_no_publicado_no_aparece(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, estado: PostStatus
) -> None:
    """Decision D-009-I, y el motivo por el que se tomo.

    Publicar esta etiqueta ofreceria un filtro que devuelve cero resultados **y**
    revelaria que existe contenido no publicado con ella. El catalogo de
    etiquetas no puede ser un canal para inferir lo que hay en el panel.
    """
    solo_en_borrador = etiqueta("secreta")
    sesion_de_pruebas.add(articulo("oculto", etiquetas=[solo_en_borrador], estado=estado))
    sesion_de_pruebas.flush()

    assert _slugs_de_etiquetas(cliente_de_la_api.get(ETIQUETAS)) == []


def test_una_etiqueta_compartida_aparece_por_su_contenido_publicado(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """El borrador no la oculta: basta con que **algo** publicado la use."""
    compartida = etiqueta("compartida")
    sesion_de_pruebas.add_all(
        [
            articulo("visible", etiquetas=[compartida], estado=PostStatus.PUBLISHED),
            articulo("oculto", etiquetas=[compartida], estado=PostStatus.DRAFT),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs_de_etiquetas(cliente_de_la_api.get(ETIQUETAS)) == ["compartida"]


def test_la_etiqueta_cuenta_para_los_cuatro_tipos_de_contenido(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """La condicion recorre articulos, reviews, videos y proyectos."""
    por_articulo = etiqueta("por-articulo")
    por_review = etiqueta("por-review")
    por_video = etiqueta("por-video")
    por_proyecto = etiqueta("por-proyecto")
    sesion_de_pruebas.add_all(
        [
            articulo("a", etiquetas=[por_articulo]),
            review("r", etiquetas=[por_review]),
            video("v", etiquetas=[por_video]),
            proyecto("p", etiquetas=[por_proyecto]),
        ]
    )
    sesion_de_pruebas.flush()

    assert _slugs_de_etiquetas(cliente_de_la_api.get(ETIQUETAS)) == [
        "por-articulo",
        "por-proyecto",
        "por-review",
        "por-video",
    ]


def test_el_catalogo_de_etiquetas_esta_paginado(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """USER_FLOWS.md, reglas transversales 5: toda lista esta paginada."""
    for indice in range(3):
        sesion_de_pruebas.add(
            articulo(f"articulo-{indice}", etiquetas=[etiqueta(f"etiqueta-{indice}")])
        )
    sesion_de_pruebas.flush()

    cuerpo: dict[str, Any] = cliente_de_la_api.get(
        ETIQUETAS, params={"page": 1, "page_size": 2}
    ).json()

    assert len(cuerpo["items"]) == 2
    assert cuerpo["total"] == 3
    assert cuerpo["pages"] == 2


def test_una_etiqueta_no_aparece_duplicada_por_tener_varios_contenidos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Con un `JOIN` en vez de `EXISTS`, saldria una fila por contenido."""
    compartida = etiqueta("compartida")
    sesion_de_pruebas.add_all(
        [articulo(f"articulo-{indice}", etiquetas=[compartida]) for indice in range(4)]
    )
    sesion_de_pruebas.flush()

    cuerpo: dict[str, Any] = cliente_de_la_api.get(ETIQUETAS).json()

    assert _slugs_de_etiquetas(cliente_de_la_api.get(ETIQUETAS)) == ["compartida"]
    assert cuerpo["total"] == 1


# --- H: busqueda -----------------------------------------------------------
def test_la_busqueda_encuentra_contenido_publicado(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [articulo("con-docker", titulo="Todo sobre Docker"), articulo("otro", titulo="Otra cosa")]
    )
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(BUSQUEDA, params={"q": "docker"})) == [
        ("post", "con-docker")
    ]


@pytest.mark.parametrize("estado", [PostStatus.DRAFT, PostStatus.ARCHIVED])
def test_la_busqueda_nunca_alcanza_contenido_no_publicado(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, estado: PostStatus
) -> None:
    """USER_FLOWS.md A.8: *"la busqueda **nunca** alcanza borradores ni archivados"*.

    El termino esta **solo** en el contenido oculto, asi que cualquier resultado
    seria una fuga: no hay ningun otro contenido que pudiera producirlo.
    """
    sesion_de_pruebas.add(
        articulo("oculto", titulo="Secreto absoluto sobre Kubernetes", estado=estado)
    )
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(BUSQUEDA, params={"q": "kubernetes"})

    assert respuesta.status_code == 200
    assert respuesta.json()["items"] == []


def test_la_fuga_se_comprueba_en_los_cuatro_tipos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Cada rama de la union tiene su propia condicion: se prueban las cuatro."""
    sesion_de_pruebas.add_all(
        [
            articulo("a", titulo="Termino unico", estado=PostStatus.DRAFT),
            review("r", titulo="Termino unico", estado=BookReviewStatus.DRAFT),
            video("v", titulo="Termino unico", estado=VideoStatus.DRAFT),
            proyecto("p", titulo="Termino unico", estado=ProjectStatus.DRAFT),
        ]
    )
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(BUSQUEDA, params={"q": "termino unico"}).json()["items"] == []


def test_cada_resultado_declara_su_tipo(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Decision D-009-J: coleccion plana con discriminador."""
    sesion_de_pruebas.add_all(
        [
            articulo("a", titulo="Comun", publicado_el=RECIENTE),
            review("r", titulo="Comun", publicado_el=RECIENTE),
            video("v", titulo="Comun", publicado_el=RECIENTE),
            proyecto("p", titulo="Comun", publicado_el=RECIENTE),
        ]
    )
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(BUSQUEDA, params={"q": "comun"})) == [
        ("book_review", "r"),
        ("post", "a"),
        ("project", "p"),
        ("video", "v"),
    ]


def test_la_busqueda_es_insensible_a_mayusculas(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(articulo("uno", titulo="Todo sobre Docker"))
    sesion_de_pruebas.flush()

    for termino in ("docker", "DOCKER", "DoCkEr"):
        assert len(cliente_de_la_api.get(BUSQUEDA, params={"q": termino}).json()["items"]) == 1


def test_la_busqueda_encuentra_subcadenas(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Motivo por el que se eligio `ILIKE` y no *full-text* (D-009-L).

    Quien teclea "doc" en un buscador espera encontrar "Docker". El *full-text*
    nativo, que trabaja sobre lexemas, no lo encontraria.
    """
    sesion_de_pruebas.add(articulo("uno", titulo="Todo sobre Docker"))
    sesion_de_pruebas.flush()

    assert len(cliente_de_la_api.get(BUSQUEDA, params={"q": "ocke"}).json()["items"]) == 1


def test_la_busqueda_mira_el_resumen(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(articulo("uno", titulo="Sin pistas", resumen="Habla de Docker"))
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(BUSQUEDA, params={"q": "docker"})) == [("post", "uno")]


def test_la_busqueda_no_mira_el_cuerpo_markdown(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """Decision D-009-K.

    Una coincidencia dentro del Markdown produciria un resultado donde el
    visitante no ve el termino por ninguna parte —el resultado muestra titulo y
    resumen— y pareceria un fallo.
    """
    sesion_de_pruebas.add(
        articulo("uno", titulo="Sin pistas", resumen="Tampoco aqui", contenido="Habla de Docker")
    )
    sesion_de_pruebas.flush()

    assert cliente_de_la_api.get(BUSQUEDA, params={"q": "docker"}).json()["items"] == []


def test_la_busqueda_mira_el_libro_y_su_autor(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """D-009-K: entran porque el listado de reviews los muestra (A.4)."""
    sesion_de_pruebas.add_all(
        [
            review("por-titulo", titulo="Sin pistas", titulo_del_libro="Clean Architecture"),
            review("por-autor", titulo="Tampoco", autor_del_libro="Martin Fowler"),
        ]
    )
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(BUSQUEDA, params={"q": "architecture"})) == [
        ("book_review", "por-titulo")
    ]
    assert _resultados(cliente_de_la_api.get(BUSQUEDA, params={"q": "fowler"})) == [
        ("book_review", "por-autor")
    ]


@pytest.mark.parametrize(
    ("comodin", "termino"),
    [
        # `%z` escapado busca esos dos caracteres literales y no encuentra nada.
        # Sin escapar, `%` es "cualquier cosa" y el patron pasa a ser "contiene
        # una z": devolveria el articulo, que es la fuga que se quiere impedir.
        ("%", "%z"),
        # `_` sin escapar es "un caracter cualquiera", asi que `_n` casaria con
        # cualquier titulo que lleve una `n` precedida de algo.
        ("_", "_n"),
    ],
)
def test_un_comodin_de_like_no_actua_como_comodin(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient, comodin: str, termino: str
) -> None:
    """Sin escapar, un comodin convertiria la busqueda en un listado completo.

    USER_FLOWS.md A.8 exige que el termino se trate como dato. Ligarlo como
    parametro impide la inyeccion de SQL, pero **no** impide que un comodin de
    `LIKE` se interprete como tal: hace falta escaparlo ademas.

    El titulo sembrado contiene lo que el patron **sin escapar** encontraria y
    **no** contiene el termino literal, de modo que la prueba distingue las dos
    implementaciones en lugar de pasar con cualquiera de ellas.
    """
    sesion_de_pruebas.add(articulo("analizado", titulo="Analiza bien esto"))
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(BUSQUEDA, params={"q": termino})

    assert respuesta.json()["items"] == [], (
        f"el comodin {comodin!r} se interpreto como patron en lugar de como texto"
    )


def test_un_comodin_literal_si_se_encuentra(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    """El escape no puede romper la busqueda de un `%` que si esta en el texto.

    Es la otra mitad del contrato: escapar de mas dejaria sin encontrar
    contenido perfectamente legitimo.
    """
    sesion_de_pruebas.add_all(
        [
            articulo("normal", titulo="Un titulo corriente"),
            articulo("descuento", titulo="Descuento del 50% hoy"),
        ]
    )
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(BUSQUEDA, params={"q": "50%"})) == [
        ("post", "descuento")
    ]


def test_la_busqueda_se_ordena_por_fecha_descendente(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [
            articulo("medio", titulo="Comun", publicado_el=INTERMEDIO),
            articulo("viejo", titulo="Comun", publicado_el=ANTIGUO),
            articulo("nuevo", titulo="Comun", publicado_el=RECIENTE),
        ]
    )
    sesion_de_pruebas.flush()

    assert _resultados(cliente_de_la_api.get(BUSQUEDA, params={"q": "comun"})) == [
        ("post", "nuevo"),
        ("post", "medio"),
        ("post", "viejo"),
    ]


def test_la_busqueda_esta_paginada(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add_all(
        [articulo(f"articulo-{indice}", titulo="Comun") for indice in range(5)]
    )
    sesion_de_pruebas.flush()

    cuerpo: dict[str, Any] = cliente_de_la_api.get(
        BUSQUEDA, params={"q": "comun", "page": 1, "page_size": 2}
    ).json()

    assert len(cuerpo["items"]) == 2
    assert cuerpo["total"] == 5
    assert cuerpo["pages"] == 3


def test_sin_coincidencias_la_busqueda_devuelve_una_coleccion_vacia(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(articulo("uno", titulo="Una cosa"))
    sesion_de_pruebas.flush()

    respuesta = cliente_de_la_api.get(BUSQUEDA, params={"q": "inexistente"})

    assert respuesta.status_code == 200
    cuerpo: dict[str, Any] = respuesta.json()
    assert cuerpo["items"] == []
    assert cuerpo["total"] == 0
    assert cuerpo["pages"] == 0


def test_el_termino_se_recorta_antes_de_buscar(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(articulo("uno", titulo="Todo sobre Docker"))
    sesion_de_pruebas.flush()

    assert len(cliente_de_la_api.get(BUSQUEDA, params={"q": "  docker  "}).json()["items"]) == 1


def test_los_resultados_no_exponen_campos_internos(
    sesion_de_pruebas: Session, cliente_de_la_api: TestClient
) -> None:
    sesion_de_pruebas.add(articulo("uno", titulo="Comun"))
    sesion_de_pruebas.flush()

    elemento: dict[str, Any] = cliente_de_la_api.get(BUSQUEDA, params={"q": "comun"}).json()[
        "items"
    ][0]

    assert set(elemento) == {"type", "slug", "title", "summary", "published_at"}
