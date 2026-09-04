"""Casos de uso administrativos de los articulos (`Task/012`).

Cubren los flujos B.2, B.3, B.7, B.8 y B.9 de USER_FLOWS.md. Cada operacion de
negocio es una **unidad con nombre propio** (software-architecture.md seccion
3.5, principio 3), que es lo que `Task/009` no necesitaba: sus consultas de solo
lectura no orquestaban nada y por eso este modulo no tenia capa `application`
(decision D-009-Q).

Que orquesta cada caso de uso
-----------------------------

Resolver el slug, comprobar su unicidad y su estabilidad, validar las
referencias a otros modulos —etiquetas y portada—, aplicar el ciclo de vida del
dominio y escribir en el historial. Nada de eso cabe en un endpoint delgado.

Donde esta el limite transaccional (decision D-012-V)
-----------------------------------------------------

En la **peticion**: `get_session` confirma al salir y revierte ante cualquier
excepcion, asi que crear un articulo, asociar sus etiquetas, resolver su portada
y auditar es atomico sin ningun mecanismo nuevo. `Task/011` confirma dentro del
caso de uso, pero por una razon que aqui **no** aplica: su camino de fallo debe
persistir estado defensivo. Aqui un fallo debe revertirlo todo.

Por que la repeticion entre los cuatro tipos es deliberada
-----------------------------------------------------------

Es la misma postura de **D-P** en `data-model.md` —*"una tabla por tipo,
columnas repetidas"*— y de **D-009-R** en las consultas publicas: una base comun
tendria que conocer `status`, la validacion de publicacion y las tablas puente
de los cuatro tipos, que son reglas de negocio, y alojarlas fuera de su modulo
es justo lo que ADR-004 prohibe. Los cuatro tipos **no** son el mismo: `Video`
no tiene Markdown ni se despublica, `BookReview` tiene libro y valoracion,
`Project` tiene un segundo estado.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.audit.domain.acciones import ENTIDAD_ARTICULO, AccionAuditada
from app.modules.audit.domain.puertos import ContextoDeAuditoria, RegistroDeAuditoria
from app.modules.media.domain.texto_alternativo import texto_a_escribir
from app.modules.posts.domain import (
    ArticuloPublicable,
    PostPublication,
    PostStatus,
    exigir_articulo_publicable,
)
from app.shared.errors.exceptions import ReferenciaDesconocidaError, ResourceNotFoundError
from app.shared.reloj import Reloj
from app.shared.slug import SlugDuplicadoError, SlugInmutableError, resolver_slug


@dataclass(frozen=True, slots=True)
class DatosDelArticulo:
    """Representacion completa del articulo que se quiere dejar guardada.

    **Sin `status` ni `published_at`** (decision D-012-A): el ciclo de vida vive
    en los subrecursos `publish`, `unpublish` y `archive`. Si `status` fuera un
    campo escribible existirian dos caminos para publicar, y uno de ellos —el
    del `PUT`— se saltaria la validacion de campos minimos.
    """

    title: str
    slug: str | None
    summary: str | None
    content: str
    featured: bool
    seo_title: str | None
    seo_description: str | None
    cover_id: uuid.UUID | None
    tag_ids: tuple[uuid.UUID, ...]
    #: Texto alternativo propuesto para la imagen referenciada.
    #:
    #: Se escribe **en el primer uso** (decision D-012-Y): las fuentes dicen
    #: que `alt_text` *"se escribe al usar la imagen, no al cargarla"*.
    imagen_alt_text: str | None = None


@dataclass(frozen=True, slots=True)
class ArticuloAlmacenado:
    """Lo que los casos de uso necesitan saber de un articulo ya persistido.

    No es el articulo entero: son su identidad, su estado de publicacion y los
    campos que deciden si puede publicarse. La proyeccion completa hacia HTTP la
    hace la capa de presentacion desde el modelo ORM, igual que en `Task/009`.
    """

    id: uuid.UUID
    slug: str
    status: PostStatus
    published_at: datetime | None
    title: str
    summary: str | None
    content: str
    seo_description: str | None

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
    def publicable(self) -> ArticuloPublicable:
        """Vista de dominio con la que se validan los campos minimos."""
        return ArticuloPublicable(
            title=self.title,
            slug=self.slug,
            content=self.content,
            summary=self.summary,
            seo_description=self.seo_description,
            tiene_imagen=self.tiene_imagen,
            imagen_alt_text=self.imagen_alt_text,
        )

    @property
    def publicacion(self) -> PostPublication:
        """Estado de publicacion reconstruido desde lo persistido."""
        return PostPublication.restore(self.status, self.published_at)


class RepositorioDeArticulos(Protocol):
    """Persistencia administrativa de los articulos."""

    def slug_ocupado(self, slug: str, *, excepto: uuid.UUID | None = None) -> bool:
        """Dice si otro articulo ya usa ese slug."""
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

    def crear(self, datos: DatosDelArticulo, *, slug: str) -> uuid.UUID:
        """Inserta el articulo como borrador y devuelve su identificador."""
        ...

    def obtener(
        self, identificador: uuid.UUID, *, bloqueando: bool = False
    ) -> ArticuloAlmacenado | None:
        """Carga el articulo. Con `bloqueando`, deja su fila bloqueada.

        El bloqueo de fila no es decorativo (decision D-012-P): una transicion es
        una lectura-modificacion-escritura sobre el estado, y sin el dos
        publicaciones simultaneas ganan las dos, emiten dos eventos y pueden
        fijar dos `published_at` distintos. Es el mismo mecanismo que `Task/011`
        uso para el contador de intentos fallidos (A-08), no uno nuevo.
        """
        ...

    def actualizar(self, identificador: uuid.UUID, datos: DatosDelArticulo, *, slug: str) -> None:
        """Deja el articulo con exactamente estos valores y estas etiquetas."""
        ...

    def aplicar_publicacion(self, identificador: uuid.UUID, estado: PostPublication) -> None:
        """Persiste el estado de publicacion que decidio el dominio."""
        ...


class _CasoDeUsoDeArticulos:
    """Base comun de los casos de uso: lo que **no** es regla de negocio.

    Aqui solo viven la comprobacion de referencias y la escritura del evento,
    que son identicas para las cinco operaciones de este mismo modulo. No es la
    base compartida entre tipos que ADR-004 prohibe: no sale de `posts`.
    """

    def __init__(
        self, *, repositorio: RepositorioDeArticulos, auditoria: RegistroDeAuditoria
    ) -> None:
        self._repositorio = repositorio
        self._auditoria = auditoria

    def _exigir_referencias(self, datos: DatosDelArticulo) -> None:
        """Comprueba etiquetas y portada **antes** de escribir nada.

        Se consulta en lugar de dejar que falle la clave foranea porque un
        `IntegrityError` no distingue que columna lo provoco, y el mensaje tiene
        que decir **cual** referencia esta mal (decision D-012-J).
        """
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

    def _asignar_texto_alternativo(self, datos: DatosDelArticulo) -> None:
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

    def _cargar(self, identificador: uuid.UUID, *, bloqueando: bool = False) -> ArticuloAlmacenado:
        articulo = self._repositorio.obtener(identificador, bloqueando=bloqueando)
        if articulo is None:
            raise ResourceNotFoundError("El recurso solicitado no existe.")
        return articulo

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
            entidad=ENTIDAD_ARTICULO,
            actor_id=actor_id,
            entidad_id=identificador,
            request_id=contexto.request_id,
            ip=contexto.origen,
            metadatos=metadatos,
        )


class CrearArticulo(_CasoDeUsoDeArticulos):
    """Crea un borrador (flujo B.2)."""

    def __call__(
        self, *, datos: DatosDelArticulo, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
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
            # El slug y nada mas (decision D-012-O): identifica el contenido en
            # el historial sin arrastrar su Markdown, que CONTENT_MODEL.md 3.9
            # excluye.
            metadatos={"slug": slug},
        )
        return identificador


class ActualizarArticulo(_CasoDeUsoDeArticulos):
    """Edita un articulo en cualquier estado (flujo B.3).

    **No cambia el estado de publicacion.** B.3 es explicito: *"editar un
    contenido `published` actualiza el contenido visible; no lo despublica
    implicitamente"*.
    """

    def __call__(
        self,
        *,
        identificador: uuid.UUID,
        datos: DatosDelArticulo,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> None:
        articulo = self._cargar(identificador)
        slug = resolver_slug(slug=datos.slug, titulo=datos.title)

        if slug != articulo.slug:
            # Decision D-012-F: la frontera es haber sido publico alguna vez.
            if articulo.published_at is not None:
                raise SlugInmutableError(articulo.slug)
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


class _TransicionDeArticulo(_CasoDeUsoDeArticulos):
    """Base de las tres transiciones: cargan con cerrojo, aplican y auditan."""

    def _aplicar(
        self,
        *,
        identificador: uuid.UUID,
        actual: ArticuloAlmacenado,
        nuevo: PostPublication,
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


class PublicarArticulo(_TransicionDeArticulo):
    """Publica un borrador (flujo B.7).

    El orden de las dos comprobaciones importa y es deliberado: **primero el
    estado, despues los campos**. Publicar algo que ya esta publicado es un error
    sobre la operacion; que le falte el resumen, un error sobre el contenido. Al
    contenido publicado no se le puede reprochar estar incompleto, porque para
    llegar ahi ya paso por esta misma validacion.
    """

    def __init__(
        self,
        *,
        repositorio: RepositorioDeArticulos,
        auditoria: RegistroDeAuditoria,
        reloj: Reloj,
    ) -> None:
        super().__init__(repositorio=repositorio, auditoria=auditoria)
        self._reloj = reloj

    def __call__(
        self, *, identificador: uuid.UUID, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> None:
        articulo = self._cargar(identificador, bloqueando=True)
        # Lanza `InvalidPostStateError` si no es un borrador, y calcula la fecha
        # conservando la de la primera publicacion (`data-model.md` seccion 7).
        nuevo = articulo.publicacion.publish(now=self._reloj.ahora())
        exigir_articulo_publicable(articulo.publicable)
        self._aplicar(
            identificador=identificador,
            actual=articulo,
            nuevo=nuevo,
            accion=AccionAuditada.CONTENIDO_PUBLICADO,
            actor_id=actor_id,
            contexto=contexto,
        )


class DespublicarArticulo(_TransicionDeArticulo):
    """Devuelve un articulo publicado a borrador (flujo B.8).

    **Existe solo aqui y en las reviews.** `MVP_SCOPE.md` seccion 3.2 concede
    `published -> draft` a articulos y reviews, y solo a ellos; `Video` y
    `Project` no tienen esta operacion ni la ruta que la expondria.
    """

    def __call__(
        self, *, identificador: uuid.UUID, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> None:
        articulo = self._cargar(identificador, bloqueando=True)
        nuevo = articulo.publicacion.unpublish()
        self._aplicar(
            identificador=identificador,
            actual=articulo,
            nuevo=nuevo,
            accion=AccionAuditada.CONTENIDO_DESPUBLICADO,
            actor_id=actor_id,
            contexto=contexto,
        )


class ArchivarArticulo(_TransicionDeArticulo):
    """Retira un articulo sin eliminarlo (flujo B.9)."""

    def __call__(
        self, *, identificador: uuid.UUID, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> None:
        articulo = self._cargar(identificador, bloqueando=True)
        nuevo = articulo.publicacion.archive()
        self._aplicar(
            identificador=identificador,
            actual=articulo,
            nuevo=nuevo,
            accion=AccionAuditada.CONTENIDO_ARCHIVADO,
            actor_id=actor_id,
            contexto=contexto,
        )
