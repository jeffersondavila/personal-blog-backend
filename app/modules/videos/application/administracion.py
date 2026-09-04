"""Casos de uso administrativos de los videos (`Task/012`).

Dos diferencias con los articulos, y las dos vienen de fuentes canonicas:

- **No hay `content`.** CONTENT_MODEL.md seccion 2 y ADR-005 decision 7: el
  contenido principal de un video es el video externo. Lo que USER_FLOWS.md B.7
  llama "contenido" se materializa aqui en `video_url` y `provider`.
- **No hay `DespublicarVideo`.** `MVP_SCOPE.md` 3.2 concede `published -> draft`
  a articulos y reviews y solo a ellos. `Task/008` lo expreso por **ausencia del
  metodo** en `VideoPublication`, y aqui se expresa por ausencia del caso de
  uso: una transicion que no existe no puede invocarse por error ni habilitarse
  por descuido.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.audit.domain.acciones import ENTIDAD_VIDEO, AccionAuditada
from app.modules.audit.domain.puertos import ContextoDeAuditoria, RegistroDeAuditoria
from app.modules.media.domain.texto_alternativo import texto_a_escribir
from app.modules.videos.domain import (
    VideoPublicable,
    VideoPublication,
    VideoStatus,
    exigir_video_publicable,
)
from app.shared.errors.exceptions import ReferenciaDesconocidaError, ResourceNotFoundError
from app.shared.reloj import Reloj
from app.shared.slug import SlugDuplicadoError, SlugInmutableError, resolver_slug


@dataclass(frozen=True, slots=True)
class DatosDelVideo:
    """Representacion completa del video que se quiere dejar guardada.

    Sin `content`, y la ausencia es el diseno: la tabla no tiene esa columna.
    """

    title: str
    slug: str | None
    summary: str | None
    featured: bool
    seo_title: str | None
    seo_description: str | None
    thumbnail_id: uuid.UUID | None
    tag_ids: tuple[uuid.UUID, ...]
    provider: str | None
    video_url: str | None
    embed_reference: str | None
    duration_seconds: int | None
    #: Texto alternativo propuesto para la imagen referenciada.
    #:
    #: Se escribe **en el primer uso** (decision D-012-Y): las fuentes dicen
    #: que `alt_text` *"se escribe al usar la imagen, no al cargarla"*.
    imagen_alt_text: str | None = None


@dataclass(frozen=True, slots=True)
class VideoAlmacenado:
    """Lo que los casos de uso necesitan saber de un video ya persistido."""

    id: uuid.UUID
    slug: str
    status: VideoStatus
    published_at: datetime | None
    title: str
    summary: str | None
    seo_description: str | None
    provider: str | None
    video_url: str | None

    #: Texto alternativo de la imagen referenciada, o `None` si no hay imagen.
    #:
    #: Viaja con el estado almacenado porque la validacion de publicacion lo
    #: necesita: el requisito A-04 se exige **donde se usa** la imagen
    #: (`data-model.md` 4.1, decision D-010-N), y aqui es donde se sabe si el
    #: contenido referencia una y con que texto.
    imagen_alt_text: str | None = None
    #: Si el contenido referencia una imagen. "Sin imagen" y "imagen sin texto"
    #: son casos distintos, y solo el segundo impide publicar.
    tiene_imagen: bool = False

    @property
    def publicable(self) -> VideoPublicable:
        """Vista de dominio con la que se validan los campos minimos."""
        return VideoPublicable(
            title=self.title,
            slug=self.slug,
            summary=self.summary,
            seo_description=self.seo_description,
            provider=self.provider,
            video_url=self.video_url,
            tiene_imagen=self.tiene_imagen,
            imagen_alt_text=self.imagen_alt_text,
        )

    @property
    def publicacion(self) -> VideoPublication:
        """Estado de publicacion reconstruido desde lo persistido."""
        return VideoPublication.restore(self.status, self.published_at)


class RepositorioDeVideos(Protocol):
    """Persistencia administrativa de los videos."""

    def slug_ocupado(self, slug: str, *, excepto: uuid.UUID | None = None) -> bool:
        """Dice si otro elemento del mismo tipo ya usa ese slug."""
        ...

    def etiquetas_desconocidas(self, identificadores: Sequence[uuid.UUID]) -> list[uuid.UUID]:
        """Devuelve los identificadores de etiqueta que no existen."""
        ...

    def medio_existe(self, identificador: uuid.UUID) -> bool:
        """Dice si la imagen referenciada existe."""
        ...

    def texto_alternativo_del_medio(self, identificador: uuid.UUID | None) -> str | None:
        """Texto alternativo de la imagen referenciada, o `None`."""
        ...

    def bloquear_texto_alternativo(self, identificador: uuid.UUID) -> str | None:
        """Lee el texto alternativo del medio **bloqueando su fila** (D-012-Y)."""
        ...

    def escribir_texto_alternativo(self, identificador: uuid.UUID, texto: str) -> None:
        """Persiste el texto alternativo del medio, en esta misma transaccion."""
        ...

    def crear(self, datos: DatosDelVideo, *, slug: str) -> uuid.UUID:
        """Inserta el contenido **como borrador** y devuelve su identificador."""
        ...

    def obtener(
        self, identificador: uuid.UUID, *, bloqueando: bool = False
    ) -> VideoAlmacenado | None:
        """Carga el contenido. Con `bloqueando`, deja su fila bloqueada (D-012-P)."""
        ...

    def actualizar(self, identificador: uuid.UUID, datos: DatosDelVideo, *, slug: str) -> None:
        """Deja el contenido con exactamente estos valores y estas etiquetas."""
        ...

    def aplicar_publicacion(self, identificador: uuid.UUID, estado: VideoPublication) -> None:
        """Persiste el estado de publicacion que decidio el dominio."""
        ...


class _CasoDeUsoDeVideos:
    """Base comun **dentro** del modulo: referencias y auditoria."""

    def __init__(self, *, repositorio: RepositorioDeVideos, auditoria: RegistroDeAuditoria) -> None:
        self._repositorio = repositorio
        self._auditoria = auditoria

    def _exigir_referencias(self, datos: DatosDelVideo) -> None:
        desconocidas = self._repositorio.etiquetas_desconocidas(datos.tag_ids)
        if desconocidas:
            raise ReferenciaDesconocidaError(
                "Alguna de las etiquetas indicadas no existe.",
                campo="tag_ids",
                valores=[str(identificador) for identificador in desconocidas],
            )
        if datos.thumbnail_id is not None and not self._repositorio.medio_existe(
            datos.thumbnail_id
        ):
            raise ReferenciaDesconocidaError(
                "La miniatura indicada no existe.",
                campo="thumbnail_id",
                valores=[str(datos.thumbnail_id)],
            )

    def _asignar_texto_alternativo(self, datos: DatosDelVideo) -> None:
        """Escribe el texto alternativo si este es el **primer uso** (D-012-Y).

        `data-model.md` 4.1 y **D-010-N**: *"se escribe al usar la imagen, no al
        cargarla"*. Este es ese momento. La regla —cuando escribir, cuando
        reutilizar y cuando rechazar— vive en el modulo `media`, que es el dueno
        de `alt_text`; aqui solo se aplica y se persiste.
        """
        identificador = datos.thumbnail_id
        if identificador is None:
            return
        nuevo = texto_a_escribir(
            # Lectura **con cerrojo**: la decision es una
            # lectura-decision-escritura y sin el dos primeros usos
            # simultaneos fijarian textos distintos (D-012-Y, D-012-Z).
            actual=self._repositorio.bloquear_texto_alternativo(identificador),
            propuesto=datos.imagen_alt_text,
            campo="thumbnail_alt_text",
        )
        if nuevo is not None:
            self._repositorio.escribir_texto_alternativo(identificador, nuevo)

    def _cargar(self, identificador: uuid.UUID, *, bloqueando: bool = False) -> VideoAlmacenado:
        elemento = self._repositorio.obtener(identificador, bloqueando=bloqueando)
        if elemento is None:
            raise ResourceNotFoundError("El recurso solicitado no existe.")
        return elemento

    def _auditar(
        self,
        accion: AccionAuditada,
        *,
        identificador: uuid.UUID,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
        metadatos: dict[str, str],
    ) -> None:
        self._auditoria.registrar(
            accion.value,
            entidad=ENTIDAD_VIDEO,
            actor_id=actor_id,
            entidad_id=identificador,
            request_id=contexto.request_id,
            ip=contexto.origen,
            metadatos=metadatos,
        )


class CrearVideo(_CasoDeUsoDeVideos):
    """Crea un borrador de video (flujo B.2)."""

    def __call__(
        self, *, datos: DatosDelVideo, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> uuid.UUID:
        slug = resolver_slug(slug=datos.slug, titulo=datos.title)
        if self._repositorio.slug_ocupado(slug):
            raise SlugDuplicadoError(slug)
        self._exigir_referencias(datos)
        self._asignar_texto_alternativo(datos)

        identificador = self._repositorio.crear(datos, slug=slug)
        self._auditar(
            AccionAuditada.CONTENIDO_CREADO,
            identificador=identificador,
            actor_id=actor_id,
            contexto=contexto,
            metadatos={"slug": slug},
        )
        return identificador


class ActualizarVideo(_CasoDeUsoDeVideos):
    """Edita un video en cualquier estado (flujo B.3)."""

    def __call__(
        self,
        *,
        identificador: uuid.UUID,
        datos: DatosDelVideo,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> None:
        elemento = self._cargar(identificador)
        slug = resolver_slug(slug=datos.slug, titulo=datos.title)

        if slug != elemento.slug:
            if elemento.published_at is not None:
                raise SlugInmutableError(elemento.slug)
            if self._repositorio.slug_ocupado(slug, excepto=identificador):
                raise SlugDuplicadoError(slug)

        self._exigir_referencias(datos)
        self._asignar_texto_alternativo(datos)
        self._repositorio.actualizar(identificador, datos, slug=slug)
        self._auditar(
            AccionAuditada.CONTENIDO_ACTUALIZADO,
            identificador=identificador,
            actor_id=actor_id,
            contexto=contexto,
            metadatos={"slug": slug},
        )


class _TransicionDeVideo(_CasoDeUsoDeVideos):
    """Base de las **dos** transiciones del video."""

    def _aplicar(
        self,
        *,
        identificador: uuid.UUID,
        actual: VideoAlmacenado,
        nuevo: VideoPublication,
        accion: AccionAuditada,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> None:
        self._repositorio.aplicar_publicacion(identificador, nuevo)
        self._auditar(
            accion,
            identificador=identificador,
            actor_id=actor_id,
            contexto=contexto,
            metadatos={
                "estado_anterior": actual.status.value,
                "estado_nuevo": nuevo.status.value,
            },
        )


class PublicarVideo(_TransicionDeVideo):
    """Publica un video (flujo B.7), exigiendo proveedor y URL."""

    def __init__(
        self,
        *,
        repositorio: RepositorioDeVideos,
        auditoria: RegistroDeAuditoria,
        reloj: Reloj,
    ) -> None:
        super().__init__(repositorio=repositorio, auditoria=auditoria)
        self._reloj = reloj

    def __call__(
        self, *, identificador: uuid.UUID, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> None:
        elemento = self._cargar(identificador, bloqueando=True)
        nuevo = elemento.publicacion.publish(now=self._reloj.ahora())
        exigir_video_publicable(elemento.publicable)
        self._aplicar(
            identificador=identificador,
            actual=elemento,
            nuevo=nuevo,
            accion=AccionAuditada.CONTENIDO_PUBLICADO,
            actor_id=actor_id,
            contexto=contexto,
        )


class ArchivarVideo(_TransicionDeVideo):
    """Retira un video sin eliminarlo (flujo B.9).

    **La otra transicion no existe.** No hay `DespublicarVideo`, y esa ausencia
    es la regla: `MVP_SCOPE.md` 3.2 no concede `published -> draft` a los videos.
    """

    def __call__(
        self, *, identificador: uuid.UUID, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> None:
        elemento = self._cargar(identificador, bloqueando=True)
        nuevo = elemento.publicacion.archive()
        self._aplicar(
            identificador=identificador,
            actual=elemento,
            nuevo=nuevo,
            accion=AccionAuditada.CONTENIDO_ARCHIVADO,
            actor_id=actor_id,
            contexto=contexto,
        )
