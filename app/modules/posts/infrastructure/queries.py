"""Consultas de lectura publica de articulos.

**Aqui vive la invariante 19** de `data-model.md`: *"contenido no publicado
nunca sale al publico"*. `Task/008` la dejo asignada a `Task/009` porque es una
regla de **consulta**, no de esquema.

Y vive **dentro de la consulta**, no en el router. La diferencia importa: una
comprobacion posterior —cargar por slug y despues decidir si se devuelve—
funciona igual de bien hasta el dia que alguien anade un camino nuevo y se
olvida de repetirla. Expresado como `WHERE status = 'published'`, no hay ningun
camino que lo evite, porque la fila no llega a salir de PostgreSQL.

Por que cada modulo tiene su propia consulta
--------------------------------------------

**Decision D-009-R.** Un constructor generico compartido tendria que conocer
`status`, `featured` y las tablas puente de etiquetado: es decir, reglas de
negocio en `app/shared`, que las tiene prohibidas
(software-architecture.md seccion 3.4). Es el mismo criterio con el que
`Task/008` decidio no crear una superentidad `Content` (data-model.md, D-P): la
repeticion de unas cuantas lineas sale mas barata que una abstraccion que
despues hay que deshacer.

Lo que si se comparte es lo genuinamente agnostico del modelo: los parametros de
pagina y la resolucion del orden, en `app/shared/pagination`.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.filtros_publicos import FiltrosDeContenido
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import Post
from app.modules.tags.infrastructure.models import Tag, post_tags
from app.shared.pagination import ParametrosDePagina, clausula_de_orden

#: Columnas por las que se admite ordenar (D-009-D). El mapa es lo unico que
#: traduce el valor publico a una columna: el texto recibido **nunca** llega a
#: SQL, ni siquiera como nombre de columna.
COLUMNAS_ORDENABLES = {"published_at": Post.published_at, "title": Post.title}


def _condiciones(filtros: FiltrosDeContenido) -> list[ColumnElement[bool]]:
    """Condiciones `WHERE` de una consulta publica, filtros incluidos.

    Se devuelven como lista y no aplicadas a una consulta concreta porque las
    usan **dos** consultas que no tienen la misma forma: la del conteo, que
    selecciona un escalar, y la de la pagina, que selecciona entidades. Que
    ambas partan de la misma lista es lo que garantiza que `total` cuente
    exactamente el conjunto que se esta paginando.

    La primera condicion es la invariante 19 y nunca es opcional.
    """
    condiciones: list[ColumnElement[bool]] = [Post.status == PostStatus.PUBLISHED]

    if filtros.featured is not None:
        condiciones.append(Post.featured.is_(filtros.featured))

    if filtros.tag is not None:
        # Subconsulta y no `JOIN`: un contenido con varias etiquetas produciria
        # filas duplicadas en el `JOIN`, y con ellas un `total` inflado y un
        # `LIMIT` que devuelve menos elementos de los que dice.
        articulos_con_la_etiqueta = (
            select(post_tags.c.post_id)
            .join(Tag, Tag.id == post_tags.c.tag_id)
            .where(Tag.slug == filtros.tag)
        )
        condiciones.append(Post.id.in_(articulos_con_la_etiqueta))

    return condiciones


def contar_articulos_publicados(sesion: Session, *, filtros: FiltrosDeContenido) -> int:
    """Total de articulos que cumplen el filtro, **antes** de paginar.

    Se cuenta el conjunto completo y no los elementos devueltos: `total` es el
    numero de elementos que cumplen el filtro (api-contracts.md seccion 5), y de
    el depende que el cliente sepa cuantas paginas hay.
    """
    consulta = select(func.count()).select_from(Post).where(*_condiciones(filtros))
    return sesion.execute(consulta).scalar_one()


def listar_articulos_publicados(
    sesion: Session, *, parametros: ParametrosDePagina, filtros: FiltrosDeContenido
) -> Sequence[Post]:
    """Pagina de articulos publicados, ordenada de forma determinista.

    `selectinload` y `joinedload` no son adorno: sin ellos, serializar las
    etiquetas y la portada de cada fila dispararia una consulta por fila
    (requisito P-08). `selectinload` resuelve las etiquetas de la pagina entera
    en **una** consulta adicional, sea cual sea el numero de filas.
    """
    consulta = (
        select(Post)
        .where(*_condiciones(filtros))
        .options(selectinload(Post.tags), joinedload(Post.cover))
        .order_by(
            *clausula_de_orden(sort=filtros.sort, columnas=COLUMNAS_ORDENABLES, desempate=Post.slug)
        )
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).scalars().unique().all()


def obtener_articulo_publicado(sesion: Session, *, slug: str) -> Post | None:
    """Articulo publicado con ese slug, o `None`.

    El estado forma parte de la condicion, de modo que un borrador **no se
    carga**: la consulta no distingue "no existe" de "no es visible", y por eso
    la respuesta tampoco puede distinguirlos por accidente
    (api-contracts.md seccion 3).
    """
    consulta = (
        select(Post)
        .where(Post.status == PostStatus.PUBLISHED)
        .where(Post.slug == slug)
        .options(selectinload(Post.tags), joinedload(Post.cover))
    )
    return sesion.execute(consulta).scalars().unique().one_or_none()
