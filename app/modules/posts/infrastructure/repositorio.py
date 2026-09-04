"""Persistencia administrativa de los articulos (`Task/012`).

Implementa `RepositorioDeArticulos` traduciendo entre las estructuras planas de
la capa de aplicacion y el modelo ORM, que es el patron que `Task/010` fijo con
los medios.

El `flush` de cada escritura es la convencion del proyecto desde `Task/010`: sin
el, una violacion de restriccion no aparece hasta el `commit` —fuera del alcance
del caso de uso— y la respuesta ya estaria construida.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modules.media.infrastructure.models import MediaAsset
from app.modules.posts.application.administracion import ArticuloAlmacenado, DatosDelArticulo
from app.modules.posts.domain import PostPublication, PostStatus
from app.modules.posts.infrastructure.models import Post
from app.modules.tags.infrastructure.models import Tag


class RepositorioSqlDeArticulos:
    """Repositorio administrativo de articulos sobre una sesion de SQLAlchemy."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def slug_ocupado(self, slug: str, *, excepto: uuid.UUID | None = None) -> bool:
        """Dice si **otro** articulo ya usa ese slug.

        `excepto` existe porque una edicion reenvia su propio slug: sin el, todo
        `PUT` chocaria consigo mismo. La unicidad real la garantiza el indice
        unico de la tabla; esto es lo que permite dar un `409` explicativo en
        lugar de un `IntegrityError`.
        """
        sentencia = select(Post.id).where(Post.slug == slug)
        if excepto is not None:
            sentencia = sentencia.where(Post.id != excepto)
        return self._sesion.execute(sentencia).scalar_one_or_none() is not None

    def etiquetas_desconocidas(self, identificadores: Sequence[uuid.UUID]) -> list[uuid.UUID]:
        """Devuelve los identificadores de etiqueta que no existen."""
        if not identificadores:
            return []
        existentes = set(
            self._sesion.execute(select(Tag.id).where(Tag.id.in_(identificadores))).scalars()
        )
        return [
            identificador for identificador in identificadores if identificador not in existentes
        ]

    def medio_existe(self, identificador: uuid.UUID) -> bool:
        return (
            self._sesion.execute(
                select(MediaAsset.id).where(MediaAsset.id == identificador)
            ).scalar_one_or_none()
            is not None
        )

    def crear(self, datos: DatosDelArticulo, *, slug: str) -> uuid.UUID:
        """Inserta el articulo **como borrador**.

        `status` y `published_at` no salen de `datos`: un contenido nace `draft`
        (USER_FLOWS.md B.2) y su ciclo de vida es de los subrecursos
        (decision D-012-A). Aqui no hay forma de crear algo ya publicado.
        """
        fila = Post(
            slug=slug,
            title=datos.title,
            summary=datos.summary,
            content=datos.content,
            status=PostStatus.DRAFT,
            featured=datos.featured,
            cover_id=datos.cover_id,
            seo_title=datos.seo_title,
            seo_description=datos.seo_description,
        )
        fila.tags = self._etiquetas(datos.tag_ids)
        self._sesion.add(fila)
        self._sesion.flush()
        return fila.id

    def obtener(
        self, identificador: uuid.UUID, *, bloqueando: bool = False
    ) -> ArticuloAlmacenado | None:
        """Carga el articulo; con `bloqueando`, deja su fila bloqueada.

        `with_for_update()` se traduce en `SELECT … FOR UPDATE`, que es el
        cerrojo que da el motor: funciona con varios *workers* y varias
        instancias, al contrario que cualquier cerrojo en memoria de proceso
        (decision D-012-P, mismo criterio que A-08 en `Task/011`).
        """
        sentencia = select(Post).where(Post.id == identificador)
        if bloqueando:
            sentencia = sentencia.with_for_update()
        fila = self._sesion.execute(sentencia).scalar_one_or_none()
        if fila is None:
            return None
        return ArticuloAlmacenado(
            id=fila.id,
            slug=fila.slug,
            status=fila.status,
            published_at=fila.published_at,
            title=fila.title,
            summary=fila.summary,
            content=fila.content,
            seo_description=fila.seo_description,
            tiene_imagen=fila.cover_id is not None,
            imagen_alt_text=self.texto_alternativo_del_medio(fila.cover_id),
        )

    def actualizar(self, identificador: uuid.UUID, datos: DatosDelArticulo, *, slug: str) -> None:
        """Deja el articulo con exactamente estos valores y estas etiquetas.

        **No toca `status` ni `published_at`**: editar no despublica (B.3).
        """
        fila = self._sesion.execute(
            select(Post).options(selectinload(Post.tags)).where(Post.id == identificador)
        ).scalar_one()

        fila.slug = slug
        fila.title = datos.title
        fila.summary = datos.summary
        fila.content = datos.content
        fila.featured = datos.featured
        fila.cover_id = datos.cover_id
        fila.seo_title = datos.seo_title
        fila.seo_description = datos.seo_description
        # Reemplazo completo: `PUT` transporta el conjunto resultante, no un
        # incremento. La tabla puente tiene `CASCADE`, asi que retirar una
        # etiqueta retira la **asociacion**, nunca el contenido (D-J).
        fila.tags = self._etiquetas(datos.tag_ids)
        self._sesion.flush()

    def aplicar_publicacion(self, identificador: uuid.UUID, estado: PostPublication) -> None:
        """Persiste el estado de publicacion que decidio el dominio."""
        fila = self._sesion.execute(select(Post).where(Post.id == identificador)).scalar_one()
        fila.status = estado.status
        fila.published_at = estado.published_at
        self._sesion.flush()

    def bloquear_texto_alternativo(self, identificador: uuid.UUID) -> str | None:
        """Lee el texto alternativo **bloqueando la fila** del medio.

        Es la lectura de la decision *set-on-first-use* (D-012-Y), y necesita
        el cerrojo porque esa decision es una **lectura-decision-escritura**:
        sin el, dos primeros usos simultaneos leen los dos `NULL`, concluyen
        los dos que son el primero y escriben los dos — el segundo `UPDATE`
        espera al cerrojo de fila y **pisa** al primero en cuanto confirma.
        Eso convertiria **D-012-Z** en falsa bajo concurrencia. Se comprobo:
        con la lectura sin cerrojo las dos transacciones terminaban en `ok`.

        `SELECT ... FOR UPDATE` lo resuelve entero en **READ COMMITTED**, que
        es el nivel en el que trabaja el proyecto: quien llega segundo espera
        al cerrojo y, al obtenerlo, **relee la ultima version confirmada** —no
        la instantanea con la que empezo—. Asi ve el texto del ganador y la
        regla del dominio lo convierte en conflicto, o en no-op si resulta ser
        el mismo texto. La igualdad no se convierte en error.

        El cerrojo lo da **el motor**, asi que funciona con varios *workers* y
        varias instancias: no depende del GIL ni de que haya un solo proceso.
        Es el mismo mecanismo que `Task/011` uso para el contador de intentos
        fallidos y que las transiciones de publicacion usan para su estado.

        **Solo se bloquea aqui.** `texto_alternativo_del_medio` sigue siendo
        una lectura normal: la usa la validacion de publicacion, y bloquear
        ahi penalizaria lecturas que no deciden nada. Las lecturas publicas y
        la biblioteca no tocan este camino.
        """
        return self._sesion.execute(
            select(MediaAsset.alt_text).where(MediaAsset.id == identificador).with_for_update()
        ).scalar_one_or_none()

    def escribir_texto_alternativo(self, identificador: uuid.UUID, texto: str) -> None:
        """Persiste el texto alternativo del medio, en **esta** transaccion.

        La escritura y la asociacion pertenecen a la misma transaccion de la
        peticion (decision D-012-V), asi que un fallo posterior las revierte
        juntas: no puede quedar un texto escrito para una asociacion que no
        llego a existir.
        """
        fila = self._sesion.execute(
            select(MediaAsset).where(MediaAsset.id == identificador)
        ).scalar_one()
        fila.alt_text = texto
        self._sesion.flush()

    def texto_alternativo_del_medio(self, identificador: uuid.UUID | None) -> str | None:
        """Texto alternativo de la imagen referenciada, o `None` si no hay.

        Se consulta aparte y solo cuando hay referencia. La alternativa —un
        `JOIN` en la carga— traeria la columna en **todas** las lecturas del
        contenido, y quien la necesita es solo la validacion de publicacion.
        """
        if identificador is None:
            return None
        return self._sesion.execute(
            select(MediaAsset.alt_text).where(MediaAsset.id == identificador)
        ).scalar_one_or_none()

    def _etiquetas(self, identificadores: Sequence[uuid.UUID]) -> list[Tag]:
        """Carga las etiquetas en **una** consulta.

        Una por identificador seria N+1 en la ruta de escritura mas frecuente
        del panel (requisito P-08).
        """
        if not identificadores:
            return []
        return list(
            self._sesion.execute(select(Tag).where(Tag.id.in_(identificadores))).scalars().all()
        )
