"""Consulta del contenido publicado que entra en el sitemap.

Aqui vive la garantia de **E-08**: *el contenido no publicado nunca aparece en
el sitemap*. Expresada como `WHERE status = 'published'` en cada rama de la
union, no hay ningun camino que la olvide — que es el mismo criterio con el que
`Task/009` protegio la invariante 19 en los listados publicos.

Los videos **no** aparecen: el contrato no tiene `GET /videos/{slug}`, asi que
no existe ninguna URL de detalle que enumerar. Su listado `/videos` ya viaja
entre las rutas estaticas.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, literal, select, union_all
from sqlalchemy.orm import Session

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import Post
from app.modules.projects.domain import ProjectStatus
from app.modules.projects.infrastructure.models import Project
from app.modules.sitemap.tipos import (
    PREFIJO_DE_ARTICULOS,
    PREFIJO_DE_PROYECTOS,
    PREFIJO_DE_REVIEWS,
    EntradaDeSitemap,
)


def _rama(*, modelo: Any, estado_publicado: Any, prefijo: str) -> Select[Any]:
    """Una rama de la union: el contenido publicado de un tipo.

    El prefijo viaja como `literal` para que la ruta publica se resuelva en la
    misma consulta y el resultado salga ya ordenado en conjunto, en lugar de
    concatenar tres listas y reordenarlas en Python.
    """
    return select(
        literal(prefijo).label("prefijo"),
        modelo.slug.label("slug"),
        modelo.published_at.label("published_at"),
    ).where(modelo.status == estado_publicado)


def listar_entradas_publicadas(sesion: Session) -> list[EntradaDeSitemap]:
    """Entradas de contenido publicado, en orden determinista.

    Sin paginacion, y no por descuido: el sitemap **no** es una coleccion de la
    API —no lo consume el frontend, sino un *crawler*— y el protocolo define su
    propio limite (50 000 URL o 50 MB), muy por encima de lo que un blog
    personal alcanza. Si algun dia se superara, la forma correcta es un indice
    de sitemaps, no `page`/`page_size`.

    El orden es `prefijo, slug` para que dos ejecuciones sobre los mismos datos
    produzcan documentos identicos: un sitemap que cambia de orden en cada
    peticion invalida cualquier cache y complica compararlos.
    """
    consulta = union_all(
        _rama(
            modelo=Post,
            estado_publicado=PostStatus.PUBLISHED,
            prefijo=PREFIJO_DE_ARTICULOS,
        ),
        _rama(
            modelo=BookReview,
            estado_publicado=BookReviewStatus.PUBLISHED,
            prefijo=PREFIJO_DE_REVIEWS,
        ),
        _rama(
            modelo=Project,
            estado_publicado=ProjectStatus.PUBLISHED,
            prefijo=PREFIJO_DE_PROYECTOS,
        ),
    ).subquery()

    filas = sesion.execute(
        select(consulta).order_by(consulta.c.prefijo, consulta.c.slug)
    ).mappings()

    return [
        EntradaDeSitemap(
            ruta=f"{fila['prefijo']}/{fila['slug']}",
            ultima_modificacion=fila["published_at"],
        )
        for fila in filas
    ]
