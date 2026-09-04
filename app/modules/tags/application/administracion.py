"""Casos de uso administrativos de las etiquetas (`Task/012`, flujo B.11).

USER_FLOWS.md B.11: *"el administrador consulta, crea, renombra o elimina
etiquetas. Eliminar una etiqueta en uso requiere confirmacion explicita y
desasocia el contenido; **no elimina contenido**"*.

Dos decisiones propias
----------------------

- **D-012-S: el `slug` es inmutable.** B.11 habla de *renombrar*, que es el
  nombre visible. El slug de una etiqueta aparece en las URL de filtro que un
  visitante puede compartir (A.9), y la invariante 4 de CONTENT_MODEL.md declara
  los slugs *"estables"*. Por eso no es un campo del cuerpo de edicion: no hay
  forma de cambiarlo, en lugar de una comprobacion que lo rechace.
- **D-012-T: la confirmacion es de la interfaz.** El backend borra y desasocia.
  La asimetria con los medios esta en las propias fuentes: B.5 obliga al backend
  a **rechazar** un medio en uso; B.11 le obliga a **desasociar**. Ninguna de las
  dos es una preferencia de esta tarea.

**Quien desasocia realmente es la base**: `ON DELETE CASCADE` sobre las cuatro
tablas puente (decision D-J), que retira filas de asociacion y nunca contenido.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.modules.audit.domain.acciones import ENTIDAD_ETIQUETA, AccionAuditada
from app.modules.audit.domain.puertos import ContextoDeAuditoria, RegistroDeAuditoria
from app.shared.errors.exceptions import ResourceNotFoundError
from app.shared.slug import SlugDuplicadoError, resolver_slug


@dataclass(frozen=True, slots=True)
class DatosDeLaEtiqueta:
    """Etiqueta que se quiere crear.

    `slug` es opcional: si falta, se propone a partir del nombre, igual que el
    de un contenido se propone del titulo (decision D-012-E).
    """

    name: str
    slug: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class RenombradoDeLaEtiqueta:
    """Lo que una edicion puede cambiar. **El slug no esta**, y esa es la regla."""

    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class EtiquetaAlmacenada:
    """Etiqueta ya persistida, en la forma minima que necesitan los casos de uso."""

    id: uuid.UUID
    slug: str


class RepositorioDeEtiquetas(Protocol):
    """Persistencia administrativa de las etiquetas."""

    def slug_ocupado(self, slug: str) -> bool:
        """Dice si ya existe una etiqueta con ese slug."""
        ...

    def crear(self, datos: DatosDeLaEtiqueta, *, slug: str) -> uuid.UUID:
        """Inserta la etiqueta y devuelve su identificador."""
        ...

    def obtener(self, identificador: uuid.UUID) -> EtiquetaAlmacenada | None:
        """Devuelve la etiqueta, o `None` si no existe."""
        ...

    def renombrar(self, identificador: uuid.UUID, datos: RenombradoDeLaEtiqueta) -> None:
        """Cambia el nombre y la descripcion. **No toca el slug.**"""
        ...

    def eliminar(self, identificador: uuid.UUID) -> None:
        """Borra la etiqueta. Las asociaciones caen con ella (`CASCADE`)."""
        ...


class _CasoDeUsoDeEtiquetas:
    """Base comun **dentro** del modulo."""

    def __init__(
        self, *, repositorio: RepositorioDeEtiquetas, auditoria: RegistroDeAuditoria
    ) -> None:
        self._repositorio = repositorio
        self._auditoria = auditoria

    def _cargar(self, identificador: uuid.UUID) -> EtiquetaAlmacenada:
        etiqueta = self._repositorio.obtener(identificador)
        if etiqueta is None:
            raise ResourceNotFoundError("El recurso solicitado no existe.")
        return etiqueta

    def _auditar(
        self,
        accion: AccionAuditada,
        *,
        identificador: uuid.UUID,
        slug: str,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> None:
        self._auditoria.registrar(
            accion.value,
            entidad=ENTIDAD_ETIQUETA,
            actor_id=actor_id,
            entidad_id=identificador,
            request_id=contexto.request_id,
            ip=contexto.origen,
            # El slug, y nada mas (decision D-012-O). En el evento de borrado es
            # ademas lo unico que quedara: la fila ya no existe, y el historial
            # debe seguir diciendo **que** se borro.
            metadatos={"slug": slug},
        )


class CrearEtiqueta(_CasoDeUsoDeEtiquetas):
    """Crea una etiqueta (flujo B.11)."""

    def __call__(
        self, *, datos: DatosDeLaEtiqueta, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> uuid.UUID:
        slug = resolver_slug(slug=datos.slug, titulo=datos.name)
        if self._repositorio.slug_ocupado(slug):
            raise SlugDuplicadoError(slug)

        identificador = self._repositorio.crear(datos, slug=slug)
        self._auditar(
            AccionAuditada.ETIQUETA_CREADA,
            identificador=identificador,
            slug=slug,
            actor_id=actor_id,
            contexto=contexto,
        )
        return identificador


class RenombrarEtiqueta(_CasoDeUsoDeEtiquetas):
    """Cambia el nombre visible y la descripcion (flujo B.11)."""

    def __call__(
        self,
        *,
        identificador: uuid.UUID,
        datos: RenombradoDeLaEtiqueta,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> None:
        etiqueta = self._cargar(identificador)
        self._repositorio.renombrar(identificador, datos)
        self._auditar(
            AccionAuditada.ETIQUETA_ACTUALIZADA,
            identificador=identificador,
            slug=etiqueta.slug,
            actor_id=actor_id,
            contexto=contexto,
        )


class EliminarEtiqueta(_CasoDeUsoDeEtiquetas):
    """Elimina una etiqueta y **desasocia** el contenido (flujo B.11).

    El orden importa: se audita **antes** de borrar, porque despues el slug ya no
    se puede leer y el historial se quedaria sin decir que se borro. Las dos
    escrituras viven en la misma transaccion de la peticion, asi que un fallo
    posterior las revierte juntas.
    """

    def __call__(
        self, *, identificador: uuid.UUID, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> None:
        etiqueta = self._cargar(identificador)
        self._auditar(
            AccionAuditada.ETIQUETA_ELIMINADA,
            identificador=identificador,
            slug=etiqueta.slug,
            actor_id=actor_id,
            contexto=contexto,
        )
        self._repositorio.eliminar(identificador)
