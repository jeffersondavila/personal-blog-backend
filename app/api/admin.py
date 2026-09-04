"""Montaje y postura comun de los routers administrativos (`Task/012`).

Que hace este modulo y que **no**
----------------------------------

Hace una sola cosa: fijar la **postura de seguridad y de transporte** que todo
router bajo `/api/v1/admin` comparte. No sabe nada de articulos, reviews, videos,
proyectos, etiquetas ni medios: si lo supiera, seria el constructor generico que
la decision **D-009-R** rechazo por concentrar en `app/api` el conocimiento del
modelo de negocio que ADR-004 reparte entre modulos.

Cada router de contenido sigue viviendo en la capa `presentation` de su modulo
(software-architecture.md seccion 3.2), como los publicos.

Las cuatro dependencias comunes
-------------------------------

| Dependencia | Que aporta | Viene de |
| --- | --- | --- |
| `requiere_administrador` | **La proteccion**: sin sesion valida, `401` | `Task/011` |
| `exigir_origen_permitido` | La segunda capa de la defensa CSRF (A-11) | `Task/011` |
| `sin_cache` | `Cache-Control: no-store`, para que nada administrativo se cachee | `Task/011` |
| `rechazar_parametros_desconocidos` | Un parametro no declarado es `422` | `Task/009` |

**Se reutilizan las cuatro; no se reimplementa ninguna.** Esa es la razon de que
esta tarea no tenga codigo de autenticacion propio.

Por que la proteccion se declara en el router y no en un middleware
--------------------------------------------------------------------

Un middleware sobre `/api/v1` convertiria en privados los diez endpoints
publicos de `Task/009`. `Task/011` ya lo razono y lo dejo escrito en `main.py`:
la proteccion se aplica **endpoint a endpoint** mediante una dependencia. Aqui se
declara una vez por router en lugar de una vez por operacion, que es el mismo
mecanismo con menos repeticion — y una prueba recorre la especificacion OpenAPI
entera exigiendo que ninguna ruta administrativa se quede sin ella.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Final

from fastapi import APIRouter, Depends

from app.api.query_params import rechazar_parametros_desconocidos
from app.modules.authentication.presentation import (
    exigir_origen_permitido,
    requiere_administrador,
    sin_cache,
)
from app.shared.errors.schemas import RespuestaDeError

#: Respuestas de error que **todo** endpoint administrativo puede devolver.
#:
#: Se declaran en el router para que ninguna operacion pueda quedarse
#: documentando la forma por defecto de FastAPI, que este backend no devuelve.
RESPUESTAS_ADMINISTRATIVAS: Final[dict[int | str, dict[str, Any]]] = {
    401: {
        "model": RespuestaDeError,
        "description": "No hay sesion administrativa valida.",
    },
    403: {
        "model": RespuestaDeError,
        "description": "La peticion no procede de un origen permitido.",
    },
    422: {
        "model": RespuestaDeError,
        "description": "Cuerpo o parametros invalidos.",
    },
}


def router_administrativo(*, prefix: str, tags: list[str | Enum]) -> APIRouter:
    """Crea un `APIRouter` con la postura administrativa ya aplicada.

    Devolver el router construido —en lugar de una lista de dependencias que
    cada modulo tenga que acordarse de pasar— es lo que hace que la proteccion
    no dependa de la memoria de nadie: un router administrativo nuevo la trae
    por el hecho de crearse asi.
    """
    return APIRouter(
        prefix=prefix,
        tags=tags,
        dependencies=[
            Depends(requiere_administrador),
            Depends(exigir_origen_permitido),
            Depends(sin_cache),
            Depends(rechazar_parametros_desconocidos),
        ],
        responses=RESPUESTAS_ADMINISTRATIVAS,
    )


def routers_administrativos() -> tuple[APIRouter, ...]:
    """Los routers administrativos de `Task/012`, en el orden en que se montan.

    **Montaje incremental**, igual que hizo `app/api/public.py` en `Task/009`:
    cada router se incorpora aqui solo despues de que su *slice* haya registrado
    un RED verificable y haya alcanzado GREEN.

    Los imports viven dentro de la funcion **a proposito**: los routers importan
    `router_administrativo` de este mismo modulo, asi que importarlos en la
    cabecera crearia un ciclo.
    """
    from app.modules.book_reviews.presentation.router_admin import router as reviews
    from app.modules.media.presentation.router_admin import router as medios
    from app.modules.posts.presentation.router_admin import router as articulos
    from app.modules.profile.presentation.router_admin import router as perfil
    from app.modules.projects.presentation.router_admin import router as proyectos
    from app.modules.tags.presentation.router_admin import router as etiquetas
    from app.modules.videos.presentation.router_admin import router as videos

    return (perfil, articulos, reviews, videos, proyectos, etiquetas, medios)
