"""Casos de uso administrativos de las reviews (`Task/012`).

Misma forma que los de `posts` y **codigo propio**, por la razon que
`data-model.md` D-P y la decision D-009-R ya fijaron: una base comun entre tipos
tendria que conocer la validacion de publicacion, las tablas puente y el ciclo
de vida de los cuatro, que son reglas de negocio, y ADR-004 prohibe alojarlas
fuera de su modulo.

Lo que **no** es igual que en un articulo:

- Tres campos mas —`book_title`, `book_author`, `rating`— que ademas son
  **obligatorios al publicar** (CONTENT_MODEL.md 3.3, `data-model.md` D-D).
- `external_link`, opcional siempre.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.audit.domain.acciones import ENTIDAD_REVIEW, AccionAuditada
from app.modules.audit.domain.puertos import ContextoDeAuditoria, RegistroDeAuditoria
from app.modules.book_reviews.domain import (
    BookReviewPublication,
    BookReviewStatus,
    ReviewPublicable,
    exigir_review_publicable,
)
from app.modules.media.domain.texto_alternativo import texto_a_escribir
from app.shared.errors.exceptions import ReferenciaDesconocidaError, ResourceNotFoundError
from app.shared.reloj import Reloj
from app.shared.slug import SlugDuplicadoError, SlugInmutableError, resolver_slug


@dataclass(frozen=True, slots=True)
class DatosDeLaReview:
    """Representacion completa de la review que se quiere dejar guardada."""

    title: str
    slug: str | None
    summary: str | None
    content: str
    featured: bool
    seo_title: str | None
    seo_description: str | None
    cover_id: uuid.UUID | None
    tag_ids: tuple[uuid.UUID, ...]
    book_title: str | None
    book_author: str | None
    rating: int | None
    external_link: str | None
    #: Texto alternativo propuesto para la imagen referenciada.
    #:
    #: Se escribe **en el primer uso** (decision D-012-Y): las fuentes dicen
    #: que `alt_text` *"se escribe al usar la imagen, no al cargarla"*.
    imagen_alt_text: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewAlmacenada:
    """Lo que los casos de uso necesitan saber de una review ya persistida."""

    id: uuid.UUID
    slug: str
    status: BookReviewStatus
    published_at: datetime | None
    title: str
    summary: str | None
    content: str
    seo_description: str | None
    book_title: str | None
    book_author: str | None
    rating: int | None

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
    def publicable(self) -> ReviewPublicable:
        """Vista de dominio con la que se validan los campos minimos."""
        return ReviewPublicable(
            title=self.title,
            slug=self.slug,
            content=self.content,
            summary=self.summary,
            seo_description=self.seo_description,
            book_title=self.book_title,
            book_author=self.book_author,
            rating=self.rating,
            tiene_imagen=self.tiene_imagen,
            imagen_alt_text=self.imagen_alt_text,
        )

    @property
    def publicacion(self) -> BookReviewPublication:
        """Estado de publicacion reconstruido desde lo persistido."""
        return BookReviewPublication.restore(self.status, self.published_at)


class RepositorioDeReviews(Protocol):
    """Persistencia administrativa de las reviews."""

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

    def crear(self, datos: DatosDeLaReview, *, slug: str) -> uuid.UUID:
        """Inserta el contenido **como borrador** y devuelve su identificador."""
        ...

    def obtener(
        self, identificador: uuid.UUID, *, bloqueando: bool = False
    ) -> ReviewAlmacenada | None:
        """Carga el contenido. Con `bloqueando`, deja su fila bloqueada (D-012-P)."""
        ...

    def actualizar(self, identificador: uuid.UUID, datos: DatosDeLaReview, *, slug: str) -> None:
        """Deja el contenido con exactamente estos valores y estas etiquetas."""
        ...

    def aplicar_publicacion(self, identificador: uuid.UUID, estado: BookReviewPublication) -> None:
        """Persiste el estado de publicacion que decidio el dominio."""
        ...


class _CasoDeUsoDeReviews:
    """Base comun **dentro** del modulo: referencias y auditoria."""

    def __init__(
        self, *, repositorio: RepositorioDeReviews, auditoria: RegistroDeAuditoria
    ) -> None:
        self._repositorio = repositorio
        self._auditoria = auditoria

    def _exigir_referencias(self, datos: DatosDeLaReview) -> None:
        desconocidas = self._repositorio.etiquetas_desconocidas(datos.tag_ids)
        if desconocidas:
            raise ReferenciaDesconocidaError(
                "Alguna de las etiquetas indicadas no existe.",
                campo="tag_ids",
                valores=[str(identificador) for identificador in desconocidas],
            )
        if datos.cover_id is not None and not self._repositorio.medio_existe(datos.cover_id):
            raise ReferenciaDesconocidaError(
                "La imagen de portada indicada no existe.",
                campo="cover_id",
                valores=[str(datos.cover_id)],
            )

    def _asignar_texto_alternativo(self, datos: DatosDeLaReview) -> None:
        """Escribe el texto alternativo si este es el **primer uso** (D-012-Y).

        `data-model.md` 4.1 y **D-010-N**: *"se escribe al usar la imagen, no al
        cargarla"*. Este es ese momento. La regla —cuando escribir, cuando
        reutilizar y cuando rechazar— vive en el modulo `media`, que es el dueno
        de `alt_text`; aqui solo se aplica y se persiste.
        """
        identificador = datos.cover_id
        if identificador is None:
            return
        nuevo = texto_a_escribir(
            # Lectura **con cerrojo**: la decision es una
            # lectura-decision-escritura y sin el dos primeros usos
            # simultaneos fijarian textos distintos (D-012-Y, D-012-Z).
            actual=self._repositorio.bloquear_texto_alternativo(identificador),
            propuesto=datos.imagen_alt_text,
            campo="cover_alt_text",
        )
        if nuevo is not None:
            self._repositorio.escribir_texto_alternativo(identificador, nuevo)

    def _cargar(self, identificador: uuid.UUID, *, bloqueando: bool = False) -> ReviewAlmacenada:
        review = self._repositorio.obtener(identificador, bloqueando=bloqueando)
        if review is None:
            raise ResourceNotFoundError("El recurso solicitado no existe.")
        return review

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
            entidad=ENTIDAD_REVIEW,
            actor_id=actor_id,
            entidad_id=identificador,
            request_id=contexto.request_id,
            ip=contexto.origen,
            metadatos=metadatos,
        )


class CrearReview(_CasoDeUsoDeReviews):
    """Crea un borrador de review (flujo B.2)."""

    def __call__(
        self, *, datos: DatosDeLaReview, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
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


class ActualizarReview(_CasoDeUsoDeReviews):
    """Edita una review en cualquier estado (flujo B.3)."""

    def __call__(
        self,
        *,
        identificador: uuid.UUID,
        datos: DatosDeLaReview,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> None:
        review = self._cargar(identificador)
        slug = resolver_slug(slug=datos.slug, titulo=datos.title)

        if slug != review.slug:
            if review.published_at is not None:
                raise SlugInmutableError(review.slug)
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


class _TransicionDeReview(_CasoDeUsoDeReviews):
    """Base de las tres transiciones."""

    def _aplicar(
        self,
        *,
        identificador: uuid.UUID,
        actual: ReviewAlmacenada,
        nuevo: BookReviewPublication,
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


class PublicarReview(_TransicionDeReview):
    """Publica una review (flujo B.7), exigiendo libro, autor y valoracion."""

    def __init__(
        self,
        *,
        repositorio: RepositorioDeReviews,
        auditoria: RegistroDeAuditoria,
        reloj: Reloj,
    ) -> None:
        super().__init__(repositorio=repositorio, auditoria=auditoria)
        self._reloj = reloj

    def __call__(
        self, *, identificador: uuid.UUID, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> None:
        review = self._cargar(identificador, bloqueando=True)
        nuevo = review.publicacion.publish(now=self._reloj.ahora())
        exigir_review_publicable(review.publicable)
        self._aplicar(
            identificador=identificador,
            actual=review,
            nuevo=nuevo,
            accion=AccionAuditada.CONTENIDO_PUBLICADO,
            actor_id=actor_id,
            contexto=contexto,
        )


class DespublicarReview(_TransicionDeReview):
    """Devuelve una review publicada a borrador (flujo B.8).

    Existe aqui y en los articulos, y en ningun otro tipo: `MVP_SCOPE.md` 3.2.
    """

    def __call__(
        self, *, identificador: uuid.UUID, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> None:
        review = self._cargar(identificador, bloqueando=True)
        nuevo = review.publicacion.unpublish()
        self._aplicar(
            identificador=identificador,
            actual=review,
            nuevo=nuevo,
            accion=AccionAuditada.CONTENIDO_DESPUBLICADO,
            actor_id=actor_id,
            contexto=contexto,
        )


class ArchivarReview(_TransicionDeReview):
    """Retira una review sin eliminarla (flujo B.9)."""

    def __call__(
        self, *, identificador: uuid.UUID, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> None:
        review = self._cargar(identificador, bloqueando=True)
        nuevo = review.publicacion.archive()
        self._aplicar(
            identificador=identificador,
            actual=review,
            nuevo=nuevo,
            accion=AccionAuditada.CONTENIDO_ARCHIVADO,
            actor_id=actor_id,
            contexto=contexto,
        )
