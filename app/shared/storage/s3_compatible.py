"""Base comun de los adaptadores que hablan el protocolo S3.

Aqui vive la **traduccion** entre el contrato del proyecto y `boto3`: las cinco
operaciones, el mapeo de los errores del SDK a los del proyecto y la garantia de
que ninguna respuesta de `botocore` escapa hacia arriba.

Lo que **no** vive aqui es la politica de cada adaptador: como se construye el
cliente, que endpoints son admisibles y si el bucket puede crearse. Eso es lo
que distingue a `MinIOStorage` de `S3Storage`, y por eso `_crear_cliente` es
abstracto.

Por que hay una base compartida y no dos copias (decision D-010-A)
------------------------------------------------------------------

MinIO implementa el protocolo S3, asi que la traduccion `PutObject` /
`GetObject` / `HeadObject` / `DeleteObject` / prefirmado es **literalmente la
misma**. Duplicarla no produciria dos adaptadores mas honestos: produciria dos
copias del mismo mapeo que podrian divergir en silencio, que es justo lo que las
pruebas de contrato existen para impedir.

Lo que impide que `MinIOStorage` sea un alias vacio de `S3Storage` no es el SDK
ni la duplicacion de codigo: son sus **invariantes**, distintas y probadas por
separado. `MinIOStorage` no puede construirse sin endpoint y no puede apuntar a
AWS; `S3Storage` resuelve el endpoint de AWS por su cuenta y **jamas** crea un
bucket.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Final

from app.shared.storage.contrato import (
    AccesoTemporal,
    ContenidoDeObjeto,
    ObjectStorage,
    ObjetoAlmacenado,
)
from app.shared.storage.errores import (
    FalloDelProveedorDeAlmacenamientoError,
    ObjetoNoEncontradoError,
)

if TYPE_CHECKING:  # pragma: no cover - solo para el tipado estatico
    from mypy_boto3_s3.client import S3Client

#: Codigos con los que el protocolo S3 dice "esa clave no esta". `NoSuchKey` lo
#: devuelve `GetObject`; `404` es lo que `HeadObject` deja en el error, porque
#: esa operacion no tiene cuerpo donde poner un codigo.
_CODIGOS_DE_AUSENCIA: Final = frozenset({"NoSuchKey", "404", "NotFound"})

#: Prefijo bajo el que consulta la sonda de disponibilidad. **Nunca contiene
#: nada**: no se crea ningun objeto centinela, y las claves reales de los medios
#: son UUID v4 (`Task/010`), asi que no pueden colisionar con el.
PREFIJO_DE_LA_SONDA: Final[str] = "_readiness/"

#: Timeouts de la sonda, en segundos, y sin reintentos. Verificados durante la
#: `Task/017` contra MinIO real. Son limites por fase; el presupuesto HTTP
#: total de 2.5s se aplica en readiness.py, antes de los 3s de Traefik.
SEGUNDOS_DE_CONEXION_DE_LA_SONDA: Final[float] = 1.5
SEGUNDOS_DE_LECTURA_DE_LA_SONDA: Final[float] = 1.5


def opciones_de_sonda() -> dict[str, object]:
    """Opciones de `botocore` que acotan la sonda de disponibilidad.

    `total_max_attempts=1` incluye la tentativa inicial. En Config,
    `max_attempts=1` permitiria UN REINTENTO: dos tentativas y backoff.
    Regresion con conteo de envios reales del SDK en Task/017.
    """
    return {
        "connect_timeout": SEGUNDOS_DE_CONEXION_DE_LA_SONDA,
        "read_timeout": SEGUNDOS_DE_LECTURA_DE_LA_SONDA,
        "retries": {"total_max_attempts": 1, "mode": "standard"},
    }


class AlmacenamientoCompatibleS3(ObjectStorage):
    """Implementacion de `ObjectStorage` sobre un servicio compatible con S3."""

    def __init__(self, *, bucket: str) -> None:
        self.bucket = bucket

    @abstractmethod
    def _crear_cliente(self) -> S3Client:
        """Construye el cliente del SDK con la politica propia del adaptador."""

    @abstractmethod
    def _crear_cliente_de_sonda(self) -> S3Client:
        """Cliente de `comprobar_disponibilidad()`, con timeouts propios y sin reintentos.

        Es un cliente aparte y no el operativo por una razon concreta: los
        valores por defecto de `botocore` son largos y **reintentan**, asi que
        una sonda contra un endpoint caido podria tardar decenas de segundos —el
        `healthCheck` de Traefik usa `timeout: 3s`—. Pero acortar el cliente
        **operativo** degradaria una subida de imagen legitima, que si necesita
        margen. Dos consumidores con necesidades opuestas, dos clientes.
        """

    @abstractmethod
    def _crear_cliente_de_firma(self) -> S3Client | None:
        """Cliente alternativo usado **solo** para firmar enlaces de acceso.

        Devuelve `None` cuando no hay separacion que hacer, y entonces se firma
        con el cliente operativo.

        Es **abstracto y no tiene implementacion por defecto** a proposito. Un
        adaptador nuevo tiene que decidir explicitamente si el anfitrion que ve
        su consumidor coincide con el que ve el backend; heredar un `None`
        silencioso es justo como se cuela el defecto que esta separacion existe
        para evitar.
        """

    @cached_property
    def _cliente(self) -> S3Client:
        """Cliente del SDK, creado una sola vez por instancia.

        Perezoso a proposito: construir el adaptador no debe abrir sesiones ni
        resolver credenciales. Asi la aplicacion arranca aunque el
        almacenamiento no este disponible todavia, igual que hace el motor de
        base de datos (`app/shared/database/session.py`).
        """
        return self._crear_cliente()

    @cached_property
    def _cliente_de_sonda(self) -> S3Client:
        """Cliente de la sonda de disponibilidad, creado una sola vez."""
        return self._crear_cliente_de_sonda()

    @cached_property
    def _cliente_de_firma(self) -> S3Client:
        """Cliente con el que se firman los enlaces de acceso.

        Por que hay dos clientes y no uno
        ---------------------------------

        El backend y el consumidor del enlace **no ven el mismo anfitrion**. En
        el entorno local, el backend alcanza MinIO por el nombre de servicio de
        la red de Docker (`minio:9000`), que el navegador del host no resuelve.

        Y el problema no se puede arreglar despues de firmar: el `Host` forma
        parte de la **peticion canonica de AWS Signature Version 4**, asi que
        reescribir el anfitrion de una URL ya firmada la invalida. Comprobado
        contra MinIO real: la URL original devuelve `200` y la misma URL con el
        anfitrion cambiado devuelve `403 SignatureDoesNotMatch`. Hay una prueba
        de contrato que lo fija, para que nadie "simplifique" el diseno
        reescribiendo la cadena.

        La consecuencia es que el anfitrion externo tiene que participar en la
        firma **desde el principio**, y eso exige un cliente configurado con el.

        Construirlo no cuesta ninguna peticion de red: `generate_presigned_url`
        es aritmetica local, asi que este cliente funciona aunque su endpoint no
        sea alcanzable desde el proceso que lo usa —que es exactamente el caso
        dentro del contenedor—.

        Cuando no hay separacion, **es el mismo objeto** que `_cliente`: sin
        endpoint de acceso declarado no se construye un segundo cliente.
        """
        return self._crear_cliente_de_firma() or self._cliente

    # --- Operaciones del contrato -----------------------------------------

    def guardar(self, *, clave: str, contenido: bytes, tipo_de_contenido: str) -> ObjetoAlmacenado:
        """Escribe el objeto. Sobrescribe si la clave ya existia (D-010-D)."""
        try:
            self._cliente.put_object(
                Bucket=self.bucket,
                Key=clave,
                Body=contenido,
                ContentType=tipo_de_contenido,
            )
        except Exception as error:
            raise self._fallo("guardar", error) from error
        return ObjetoAlmacenado(
            clave=clave, tamano_bytes=len(contenido), tipo_de_contenido=tipo_de_contenido
        )

    def obtener(self, clave: str) -> ContenidoDeObjeto:
        """Descarga el objeto completo."""
        try:
            respuesta = self._cliente.get_object(Bucket=self.bucket, Key=clave)
            contenido = respuesta["Body"].read()
        except Exception as error:
            if self._es_ausencia(error):
                raise ObjetoNoEncontradoError(
                    f"no existe el objeto '{clave}' en el almacenamiento"
                ) from error
            raise self._fallo("obtener", error) from error
        return ContenidoDeObjeto(
            clave=clave,
            contenido=contenido,
            # `ContentType` siempre viaja en la respuesta de S3; el valor por
            # defecto cubre un objeto subido por otra via sin declararlo.
            tipo_de_contenido=respuesta.get("ContentType") or "application/octet-stream",
            tamano_bytes=len(contenido),
        )

    def existe(self, clave: str) -> bool:
        """Comprueba la existencia con `HeadObject`, sin traer el cuerpo."""
        try:
            self._cliente.head_object(Bucket=self.bucket, Key=clave)
        except Exception as error:
            if self._es_ausencia(error):
                return False
            raise self._fallo("comprobar", error) from error
        return True

    def eliminar(self, clave: str) -> None:
        """Borra la clave. Idempotente por contrato (D-010-C).

        `DeleteObject` de S3 ya responde correctamente ante una clave ausente,
        asi que la idempotencia no necesita una comprobacion previa —que ademas
        seria una condicion de carrera—. Se declara y se prueba para que las dos
        implementaciones no puedan divergir.
        """
        try:
            self._cliente.delete_object(Bucket=self.bucket, Key=clave)
        except Exception as error:
            if self._es_ausencia(error):
                return
            raise self._fallo("eliminar", error) from error

    def comprobar_disponibilidad(self) -> None:
        """Sonda de disponibilidad: `ListObjectsV2` acotado por prefijo.

        Por que `ListObjectsV2` y no `HeadBucket`
        -----------------------------------------

        Las dos distinguen el bucket ausente, pero solo esta entrega un **codigo
        de error semantico**. `HeadBucket` responde a un `HEAD`, sin cuerpo, asi
        que `botocore` no puede leer el XML del error y devuelve `Code='404'` o
        `Code='403'`: cadenas numericas con las que el log no puede decir *que*
        fallo. Con `ListObjectsV2` llegan `NoSuchBucket` e `InvalidAccessKeyId`.

        Y hay una segunda razon, de permisos: ambas exigen `s3:ListBucket`, pero
        solo esta envia un prefijo, asi que `Task/030` puede conceder el permiso
        **condicionado a `s3:prefix`**. Con `HeadBucket` habria que concederlo
        sin condicion, es decir, permitir enumerar el bucket entero.

        `MaxKeys=1` y un prefijo que nunca contiene nada: la respuesta es
        minima y no depende de cuantos objetos haya.
        """
        try:
            self._cliente_de_sonda.list_objects_v2(
                Bucket=self.bucket, Prefix=PREFIJO_DE_LA_SONDA, MaxKeys=1
            )
        except Exception as error:
            raise self._fallo("comprobar la disponibilidad", error) from error

    def acceso_temporal(self, clave: str, *, duracion: timedelta) -> AccesoTemporal:
        """Firma un enlace de lectura temporal.

        **La firma es local**: es un HMAC sobre la peticion canonica, sin ningun
        viaje a la red. Por eso emitir el enlace de cada medio de un listado no
        introduce una llamada por elemento (riesgo 3 de la ficha), por eso esta
        operacion funciona aunque el almacenamiento este caido, y por eso el
        cliente de firma puede estar configurado con un endpoint que este
        proceso no alcanza.
        """
        segundos = int(duracion.total_seconds())
        emitido_en = datetime.now(UTC)
        try:
            # `_cliente_de_firma`, no `_cliente`: el enlace lo consume alguien
            # que **no** ve el mismo anfitrion que el backend.
            url = self._cliente_de_firma.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": clave},
                ExpiresIn=segundos,
            )
        except Exception as error:
            raise self._fallo("firmar", error) from error
        return AccesoTemporal(url=url, expira_en=emitido_en + duracion)

    # --- Traduccion de errores --------------------------------------------

    @staticmethod
    def _es_ausencia(error: Exception) -> bool:
        """Reconoce el "no esta" del protocolo sin importar `botocore` aqui.

        Se lee del atributo `response` que `botocore.exceptions.ClientError`
        expone. Comprobar la clase obligaria a importar `botocore` en la ruta de
        error, y el interes es justamente que el SDK no se filtre.
        """
        respuesta = getattr(error, "response", None)
        if not isinstance(respuesta, dict):
            return False
        codigo = str(respuesta.get("Error", {}).get("Code", ""))
        return codigo in _CODIGOS_DE_AUSENCIA

    def _fallo(self, operacion: str, error: Exception) -> FalloDelProveedorDeAlmacenamientoError:
        """Envuelve un error del SDK **sin** filtrar credenciales ni trazas.

        El mensaje lleva la operacion y, si existe, el codigo del proveedor. No
        lleva el texto de la excepcion original —que puede incluir la URL
        firmada, cabeceras o el `arn` del principal— ni el nombre de su clase
        (requisitos S-07 y S-08). El original queda en `__cause__` para el log.
        """
        respuesta = getattr(error, "response", None)
        codigo = ""
        if isinstance(respuesta, dict):
            codigo = str(respuesta.get("Error", {}).get("Code", ""))
        detalle = f" (codigo del proveedor: {codigo})" if codigo else ""
        return FalloDelProveedorDeAlmacenamientoError(
            f"el almacenamiento de objetos no pudo {operacion} el objeto{detalle}"
        )
