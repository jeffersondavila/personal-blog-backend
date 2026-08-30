"""`MinIOStorage` — almacenamiento de objetos del entorno **local**."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from app.shared.storage.errores import ConfiguracionDeAlmacenamientoInvalidaError
from app.shared.storage.s3_compatible import AlmacenamientoCompatibleS3

if TYPE_CHECKING:  # pragma: no cover - solo para el tipado estatico
    from mypy_boto3_s3.client import S3Client

#: Sufijo de anfitrion que este adaptador tiene **prohibido**. Es una lista
#: negra y no una lista blanca de anfitriones locales a proposito: el endpoint
#: legitimo dentro de la red de Docker Compose es el nombre de servicio
#: `personal-blog-local-minio`, que ninguna lista blanca razonable de "local"
#: contendria. La lista blanca si se aplica en el harness de pruebas
#: (`tests/almacenamiento_de_pruebas.py`), donde lo que esta en juego es borrar
#: un bucket entero y el criterio correcto es el contrario.
ANFITRION_PROHIBIDO: Final = "amazonaws.com"


class MinIOStorage(AlmacenamientoCompatibleS3):
    """Adaptador para el MinIO del entorno local (`Task/007`).

    Dos invariantes lo distinguen de `S3Storage`, y las dos se comprueban al
    **construir**, antes de que exista ningun cliente (arranque fail-fast, T-01):

    1. **El endpoint es obligatorio y debe ser una URL HTTP utilizable.** No
       existe un valor por defecto sensato: MinIO vive donde lo ponga el
       entorno.
    2. **Ningun endpoint puede ser de AWS.** Este es el adaptador de desarrollo;
       una variable mal puesta no debe poder convertirlo en un cliente de
       produccion que escriba en el bucket real, ni emitir enlaces que apunten
       alli.

    Los dos endpoints, y por que
    ----------------------------

    | Endpoint | Quien lo ve | Para que |
    | --- | --- | --- |
    | `endpoint_url` | El **backend** | `put`, `get`, `head`, `delete` |
    | `access_endpoint_url` | El **consumidor del enlace** | Firmar `access_url` |

    En Docker Compose no son el mismo: el backend alcanza MinIO como
    `http://minio:9000` y el navegador del host, como `http://localhost:9000`.
    Un enlace firmado contra el primero es inservible para su unico consumidor,
    y no se puede corregir despues porque el `Host` entra en la firma SigV4.

    `access_endpoint_url` es **opcional**: sin el, se firma contra el operativo,
    que es lo correcto cuando los dos coinciden.
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str,
        access_endpoint_url: str | None = None,
    ) -> None:
        super().__init__(bucket=bucket)
        self._verificar_el_endpoint(endpoint_url)
        if access_endpoint_url is not None:
            self._verificar_el_endpoint(access_endpoint_url, nombre="el endpoint de acceso")
        self.endpoint_url = endpoint_url
        self.access_endpoint_url = access_endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self.region = region

    @staticmethod
    def _verificar_el_endpoint(endpoint_url: str, *, nombre: str = "el endpoint") -> None:
        """Rechaza un endpoint ausente, malformado o de AWS.

        Se aplica igual al operativo y al de acceso: un enlace del adaptador
        local que apuntara a Amazon S3 seria tan incorrecto como una operacion
        que escribiera alli.
        """
        partes = urlsplit(endpoint_url.strip())
        if partes.scheme not in {"http", "https"} or not partes.hostname:
            raise ConfiguracionDeAlmacenamientoInvalidaError(
                f"MinIOStorage necesita que {nombre} sea una URL HTTP explicita, "
                "por ejemplo 'http://127.0.0.1:9000'."
            )
        if partes.hostname == ANFITRION_PROHIBIDO or partes.hostname.endswith(
            f".{ANFITRION_PROHIBIDO}"
        ):
            raise ConfiguracionDeAlmacenamientoInvalidaError(
                f"MinIOStorage no puede usar '{partes.hostname}' como {nombre}: es el "
                "adaptador local y no debe alcanzar Amazon S3. Para produccion se usa "
                "S3Storage, que se selecciona con BLOG_STORAGE_PROVIDER."
            )

    def _crear_cliente(self) -> S3Client:
        """Cliente operativo: el que ejecuta `put`, `get`, `head` y `delete`."""
        return self._construir_cliente(self.endpoint_url)

    def _crear_cliente_de_firma(self) -> S3Client | None:
        """Cliente de firma, **solo** si hay un endpoint de acceso distinto.

        Sin el, la base reutiliza el operativo y no se construye nada.
        """
        if self.access_endpoint_url is None:
            return None
        return self._construir_cliente(self.access_endpoint_url)

    def _construir_cliente(self, endpoint_url: str) -> S3Client:
        """Cliente apuntado a `endpoint_url`, con direccionamiento por ruta.

        `addressing_style="path"` no es opcional: el estilo virtual convertiria
        el bucket en un subdominio (`mi-bucket.127.0.0.1`), que no resuelve.
        """
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self.region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
