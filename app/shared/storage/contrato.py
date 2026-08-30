"""Interfaz `ObjectStorage` y sus tipos de resultado.

Es el contrato que permite que cambiar de MinIO a Amazon S3 sea un cambio de
**configuracion** y no de codigo de dominio (software-architecture.md, seccion
3.7; requisito T-03).

Este modulo es deliberadamente **pobre en dependencias**: solo `abc`,
`dataclasses` y `datetime`. No importa FastAPI, SQLAlchemy, `boto3` ni
`botocore`. Un caso de uso que dependa de `ObjectStorage` no arrastra ningun
SDK, y por tanto puede probarse con un doble sin levantar nada.

Que operaciones existen, y por que exactamente estas (decision D-010-B)
-----------------------------------------------------------------------

Las cinco que los casos de uso de `Task/010` ejercen de verdad:

| Operacion | Quien la necesita |
| --- | --- |
| `guardar` | Subir el original y su miniatura |
| `obtener` | Recuperar el binario; ejercitada por el contrato |
| `existe` | Comprobar sin descargar |
| `eliminar` | Compensar una subida fallida y borrar un medio sin uso |
| `acceso_temporal` | Emitir el enlace publico del medio (D-009-O) |

`listar`, `copiar` y `metadatos` **no** estan. Los pedira la biblioteca de
medios de `Task/012`, y anadir un metodo entonces es trivial; mantenerlo muerto
mientras tanto obliga a implementarlo dos veces y a probarlo sin que nadie lo
use.

Semantica contratada
--------------------

Las dos implementaciones deben comportarse **igual** en todo esto, y
`tests/contract/test_contrato_de_object_storage.py` lo comprueba contra ambas:

| Situacion | Comportamiento |
| --- | --- |
| `guardar` sobre una clave existente | **Sobrescribe** (D-010-D) |
| `obtener` una clave inexistente | `ObjetoNoEncontradoError` |
| `eliminar` una clave inexistente | **No lanza**: es idempotente (D-010-C) |
| Contenido binario arbitrario | Se devuelve byte a byte, sin conversion a texto |
| `acceso_temporal` | URL utilizable **sin credenciales**, con expiracion |

**La interfaz no conoce imagenes.** No valida MIME, no genera miniaturas y no
sabe que es un `MediaAsset`: guarda y devuelve bytes. Las reglas de imagen viven
en `app.modules.media`, y la comprobacion de uso previa al borrado vive en su
caso de uso, no aqui: meter conocimiento de claves foraneas dentro de un
adaptador de almacenamiento romperia la separacion que este contrato existe para
mantener.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class ObjetoAlmacenado:
    """Resultado de guardar un objeto.

    Tipo propio y no la respuesta del SDK: devolver un `dict` de `boto3` haria
    que la forma de la respuesta de Amazon fuera parte del contrato del dominio.
    """

    clave: str
    tamano_bytes: int
    tipo_de_contenido: str


@dataclass(frozen=True, slots=True)
class ContenidoDeObjeto:
    """Objeto recuperado del almacenamiento.

    `contenido` son bytes ya materializados y no un flujo: los objetos de este
    proyecto son imagenes acotadas a pocos megabytes (D-010-F), y un flujo
    obligaria a todo consumidor a gestionar su cierre. Si algun dia hubiera que
    servir archivos grandes, la operacion que lo permita se anadira entonces,
    con su caso de uso real.
    """

    clave: str
    contenido: bytes
    tipo_de_contenido: str
    tamano_bytes: int


@dataclass(frozen=True, slots=True)
class AccesoTemporal:
    """Enlace de acceso con expiracion.

    **Nunca se persiste** (open-decisions.md, D-08: regla ya vigente). La base
    de datos guarda `object_key`; la URL se genera al servir, y por eso este
    tipo lleva su propia caducidad en lugar de fingir que es un dato estable.
    """

    url: str
    expira_en: datetime


class ObjectStorage(ABC):
    """Almacenamiento de objetos, independiente del proveedor."""

    #: Bucket sobre el que opera esta instancia. Informativo: **no** se expone
    #: en ninguna respuesta publica.
    bucket: str

    @abstractmethod
    def guardar(self, *, clave: str, contenido: bytes, tipo_de_contenido: str) -> ObjetoAlmacenado:
        """Escribe `contenido` en `clave`, sobrescribiendo si ya existia."""

    @abstractmethod
    def obtener(self, clave: str) -> ContenidoDeObjeto:
        """Devuelve el objeto, o lanza `ObjetoNoEncontradoError` si no existe."""

    @abstractmethod
    def existe(self, clave: str) -> bool:
        """Indica si la clave existe, sin descargar el contenido."""

    @abstractmethod
    def eliminar(self, clave: str) -> None:
        """Borra la clave. **Idempotente**: no lanza si no existia."""

    @abstractmethod
    def acceso_temporal(self, clave: str, *, duracion: timedelta) -> AccesoTemporal:
        """Emite un enlace de lectura valido durante `duracion`.

        `duracion` es un argumento y no una constante del adaptador: la politica
        de expiracion de produccion es de `Task/030` (D-08), y enterrarla aqui
        la haria inamovible sin tocar codigo (decision D-010-M).
        """
