"""Seleccion de la implementacion de `ObjectStorage` segun la configuracion.

Este modulo es **el unico sitio** del proyecto que sabe que existe mas de una
implementacion. Es lo que hace cierta la frase de software-architecture.md
seccion 3.7: cambiar de MinIO a Amazon S3 es cambiar configuracion, no codigo.

Lo que este modulo deliberadamente **no** es
--------------------------------------------

No es un *service locator*, ni un contenedor de inyeccion de dependencias, ni un
registro de proveedores extensible. El principio 6 de software-architecture.md
lo prohibe expresamente: *"inyeccion de dependencias simple; el mecanismo del
framework basta"*. Son dos implementaciones y un `match`; un registro con
plugins seria mas codigo para resolver un problema que no existe.

Tampoco importa FastAPI. La dependencia HTTP vive en la capa de presentacion
del modulo de medios, para que un caso de uso pueda pedir un `ObjectStorage` sin
arrastrar el framework (ADR-004).
"""

from __future__ import annotations

from functools import lru_cache

from app.shared.configuration import Settings
from app.shared.storage.contrato import ObjectStorage
from app.shared.storage.errores import ConfiguracionDeAlmacenamientoInvalidaError
from app.shared.storage.minio import MinIOStorage
from app.shared.storage.s3 import S3Storage


def crear_almacenamiento(configuracion: Settings) -> ObjectStorage:
    """Construye la implementacion que corresponde a la configuracion.

    La configuracion ya se valido al construirse —`Settings` exige endpoint y
    credenciales cuando el proveedor es `minio`, y prohibe `minio` en
    produccion—, asi que aqui no se repite esa validacion. Lo que si queda es la
    rama imposible: si algun dia se anade un proveedor al tipo y no se anade
    aqui, el fallo debe ser explicito y no un `None` silencioso.
    """
    match configuracion.storage_provider:
        case "minio":
            return MinIOStorage(
                bucket=configuracion.storage_bucket,
                # Los tres son obligatorios con este proveedor; el `or ""` solo
                # existe para el tipado, porque `Settings` ya garantizo que no
                # son `None` (validador `_require_local_storage_credentials`).
                endpoint_url=configuracion.storage_endpoint_url or "",
                access_endpoint_url=configuracion.storage_access_endpoint_url,
                access_key=configuracion.storage_access_key or "",
                secret_key=(
                    configuracion.storage_secret_key.get_secret_value()
                    if configuracion.storage_secret_key is not None
                    else ""
                ),
                region=configuracion.storage_region,
            )
        case "s3":
            return S3Storage(
                bucket=configuracion.storage_bucket,
                region=configuracion.storage_region,
                access_key=configuracion.storage_access_key,
                secret_key=(
                    configuracion.storage_secret_key.get_secret_value()
                    if configuracion.storage_secret_key is not None
                    else None
                ),
                endpoint_url=configuracion.storage_endpoint_url,
                access_endpoint_url=configuracion.storage_access_endpoint_url,
            )
        case proveedor:  # pragma: no cover - inalcanzable con el tipo cerrado
            raise ConfiguracionDeAlmacenamientoInvalidaError(
                f"proveedor de almacenamiento sin implementacion: {proveedor!r}"
            )


@lru_cache(maxsize=4)
def obtener_almacenamiento(configuracion: Settings) -> ObjectStorage:
    """Devuelve el almacenamiento del proceso, creandolo la primera vez.

    Se memoriza por la misma razon que el motor de base de datos: construir un
    cliente de `boto3` carga el modelo del servicio desde disco, y hacerlo en
    cada peticion penalizaria especialmente un arranque en frio de Lambda
    (requisito P-07).

    La clave de la cache es la **configuracion completa**, no el proceso: dos
    configuraciones distintas producen almacenamientos distintos, que es lo que
    permite que una prueba monte una aplicacion propia sin contaminar a las
    demas. `Settings` es inmutable (`frozen=True`), asi que es utilizable como
    clave.
    """
    return crear_almacenamiento(configuracion)
