"""Persistencia de los medios sobre SQLAlchemy.

Implementa `RepositorioDeMediosCompleto` traduciendo entre las estructuras
planas de la capa de aplicacion y el modelo ORM. La aplicacion no ve `MediaAsset`
ni la `Session`, asi que sus pruebas no necesitan PostgreSQL; las de aqui si, y
se ejecutan contra PostgreSQL real, que es donde existen de verdad la clave
unica y las cinco claves foraneas.

Sobre `usos_de` y la comprobacion de uso (invariante 12 de `data-model.md`)
--------------------------------------------------------------------------

La base ya impide el borrado con `ON DELETE RESTRICT`, y esa es la barrera
infranqueable: ningun camino, ni siquiera un `DELETE` escrito a mano, puede
dejar una referencia rota. Lo que **no** hace es explicar nada: un
`IntegrityError` no dice donde se usa la imagen.

Esta consulta es la capa de arriba, la que el flujo B.5 pide: enumera los
contenidos que la referencian para que el administrador sepa **que** tiene que
editar. Las dos capas no se estorban ni se sustituyen; la de arriba da un
mensaje util y la de abajo garantiza la integridad.

Las cinco consultas se escriben una a una, sin constructor generico. Es el mismo
criterio que **D-009-R** aplico a las consultas publicas: un constructor que
conociera las cinco tablas y sus columnas de referencia concentraria en `shared`
el conocimiento del modelo de negocio, que es justo lo que ADR-004 prohibe. Son
cinco lineas declarativas y se leen como lo que son.
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.media.application.repositorio import (
    MedioParaRegistrar,
    MedioRegistrado,
    UsoDeMedio,
)
from app.modules.media.infrastructure.models import MediaAsset
from app.modules.posts.infrastructure.models import Post
from app.modules.profile.infrastructure.models import Profile
from app.modules.projects.infrastructure.models import Project
from app.modules.videos.infrastructure.models import Video

#: El perfil no tiene `slug`: es un singleton y no se navega por URL propia.
_TIPO_DEL_PERFIL: Final = "profile"


class RepositorioDeMediosSQL:
    """Repositorio de medios sobre una sesion de SQLAlchemy."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def registrar(self, medio: MedioParaRegistrar) -> uuid.UUID:
        """Inserta la fila y devuelve su identificador.

        El `flush` no es opcional: sin el, una violacion de la clave unica de
        `object_key` no aparecería hasta el `commit`, fuera del alcance del caso
        de uso, y la compensacion no llegaria a ejecutarse.
        """
        fila = MediaAsset(
            object_key=medio.object_key,
            original_filename=medio.original_filename,
            mime_type=medio.mime_type,
            size_bytes=medio.size_bytes,
            width=medio.width,
            height=medio.height,
            checksum=medio.checksum,
            alt_text=medio.alt_text,
        )
        self._sesion.add(fila)
        self._sesion.flush()
        return fila.id

    def buscar(self, identificador: uuid.UUID) -> MedioRegistrado | None:
        fila = self._sesion.get(MediaAsset, identificador)
        if fila is None:
            return None
        return MedioRegistrado(id=fila.id, object_key=fila.object_key)

    def usos_de(self, identificador: uuid.UUID) -> list[UsoDeMedio]:
        """Enumera los contenidos que referencian el medio."""
        usos: list[UsoDeMedio] = []
        for tipo, consulta in (
            ("post", self._contenidos(Post, Post.cover_id, identificador)),
            ("book_review", self._contenidos(BookReview, BookReview.cover_id, identificador)),
            ("project", self._contenidos(Project, Project.cover_id, identificador)),
            ("video", self._contenidos(Video, Video.thumbnail_id, identificador)),
        ):
            usos.extend(
                UsoDeMedio(tipo=tipo, slug=slug, titulo=titulo)
                for slug, titulo in self._sesion.execute(consulta).all()
            )

        perfiles = self._sesion.execute(
            select(Profile.full_name).where(Profile.photo_id == identificador)
        ).all()
        usos.extend(
            UsoDeMedio(tipo=_TIPO_DEL_PERFIL, slug=None, titulo=nombre) for (nombre,) in perfiles
        )
        return usos

    def eliminar(self, identificador: uuid.UUID) -> None:
        fila = self._sesion.get(MediaAsset, identificador)
        if fila is not None:
            self._sesion.delete(fila)
            self._sesion.flush()

    @staticmethod
    def _contenidos(
        modelo: type[Post] | type[BookReview] | type[Project] | type[Video],
        columna: object,
        identificador: uuid.UUID,
    ) -> Select[tuple[str, str]]:
        return select(modelo.slug, modelo.title).where(columna == identificador)  # type: ignore[arg-type]
