"""Contrato de persistencia de los medios.

Principio 4 de software-architecture.md: *"repositorios para persistencia; el
dominio define la interfaz, la infraestructura la implementa"*.

El contrato habla de **datos**, no de modelos ORM: `MedioParaRegistrar` y
`MedioRegistrado` son estructuras planas. Asi la capa de aplicacion —y sus
pruebas— no dependen de SQLAlchemy, y la orquestacion puede probarse con un
doble de frontera sin levantar PostgreSQL. La implementacion real vive en
`app.modules.media.infrastructure.repositorio` y se prueba contra PostgreSQL
real, que es donde las restricciones existen de verdad.

`Task/009` no necesito ningun repositorio (**D-009-Q**): sus consultas son de
solo lectura y no orquestan nada. `Task/010` introduce la primera **escritura**,
con invariantes que cruzan dos sistemas, y ahi la interfaz si gana su sitio.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MedioParaRegistrar:
    """Metadatos de un medio recien almacenado.

    No lleva —y no puede llevar— el binario ni ninguna URL: la base guarda
    metadatos y la clave del objeto (CONTENT_MODEL.md seccion 3.7), y una URL
    prefirmada caduca, asi que persistirla produciria enlaces muertos (**D-08**,
    regla ya vigente).
    """

    object_key: str
    original_filename: str
    mime_type: str
    size_bytes: int
    width: int
    height: int
    checksum: str
    alt_text: str | None = None


@dataclass(frozen=True, slots=True)
class MedioRegistrado:
    """Medio ya persistido, en la forma minima que necesitan los casos de uso."""

    id: uuid.UUID
    object_key: str


@dataclass(frozen=True, slots=True)
class UsoDeMedio:
    """Un contenido que referencia un medio.

    El flujo B.5 exige que el rechazo diga **donde** se usa la imagen, asi que
    no basta con un booleano: hace falta el tipo, el titulo y el `slug` para que
    el administrador pueda ir a quitarla.
    """

    tipo: str
    slug: str | None
    titulo: str


class RepositorioDeMedios(Protocol):
    """Persistencia de los medios."""

    def registrar(self, medio: MedioParaRegistrar) -> uuid.UUID:
        """Inserta el medio y devuelve su identificador."""
        ...


class RepositorioDeMediosCompleto(RepositorioDeMedios, Protocol):
    """Ampliacion con las operaciones que necesita el borrado.

    Se separa del contrato de la subida a proposito: `SubirImagen` solo necesita
    `registrar`, y pedirle mas obligaria a sus dobles a implementar metodos que
    ese caso de uso nunca llama.
    """

    def buscar(self, identificador: uuid.UUID) -> MedioRegistrado | None:
        """Devuelve el medio, o `None` si no existe."""
        ...

    def usos_de(self, identificador: uuid.UUID) -> list[UsoDeMedio]:
        """Enumera los contenidos que referencian el medio."""
        ...

    def eliminar(self, identificador: uuid.UUID) -> None:
        """Borra la fila del medio."""
        ...
