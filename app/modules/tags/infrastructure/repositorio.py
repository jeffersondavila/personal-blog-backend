"""Persistencia administrativa de las etiquetas (`Task/012`)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.tags.application.administracion import (
    DatosDeLaEtiqueta,
    EtiquetaAlmacenada,
    RenombradoDeLaEtiqueta,
)
from app.modules.tags.infrastructure.models import Tag


class RepositorioSqlDeEtiquetas:
    """Repositorio administrativo de etiquetas sobre una sesion de SQLAlchemy."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def slug_ocupado(self, slug: str) -> bool:
        """Dice si ya existe una etiqueta con ese slug.

        No lleva `excepto`, al contrario que los repositorios de contenido: el
        slug de una etiqueta es inmutable (decision D-012-S), asi que una
        edicion nunca lo compara consigo mismo.
        """
        return (
            self._sesion.execute(select(Tag.id).where(Tag.slug == slug)).scalar_one_or_none()
            is not None
        )

    def crear(self, datos: DatosDeLaEtiqueta, *, slug: str) -> uuid.UUID:
        fila = Tag(slug=slug, name=datos.name, description=datos.description)
        self._sesion.add(fila)
        self._sesion.flush()
        return fila.id

    def obtener(self, identificador: uuid.UUID) -> EtiquetaAlmacenada | None:
        fila = self._sesion.get(Tag, identificador)
        if fila is None:
            return None
        return EtiquetaAlmacenada(id=fila.id, slug=fila.slug)

    def renombrar(self, identificador: uuid.UUID, datos: RenombradoDeLaEtiqueta) -> None:
        """Cambia el nombre y la descripcion. **No toca el slug.**"""
        fila = self._sesion.execute(select(Tag).where(Tag.id == identificador)).scalar_one()
        fila.name = datos.name
        fila.description = datos.description
        self._sesion.flush()

    def eliminar(self, identificador: uuid.UUID) -> None:
        """Borra la etiqueta.

        Las asociaciones caen con ella por `ON DELETE CASCADE` sobre las cuatro
        tablas puente (decision D-J): se retira la **asociacion**, nunca el
        contenido, que es exactamente lo que exige USER_FLOWS.md B.11.
        """
        fila = self._sesion.execute(select(Tag).where(Tag.id == identificador)).scalar_one()
        self._sesion.delete(fila)
        self._sesion.flush()
