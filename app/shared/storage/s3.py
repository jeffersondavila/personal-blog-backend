"""`S3Storage` — almacenamiento de objetos de **produccion** (Amazon S3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.shared.storage.s3_compatible import AlmacenamientoCompatibleS3, opciones_de_sonda

if TYPE_CHECKING:  # pragma: no cover - solo para el tipado estatico
    from mypy_boto3_s3.client import S3Client


class S3Storage(AlmacenamientoCompatibleS3):
    """Adaptador para Amazon S3.

    Es **codigo real**, no un esqueleto: STAGE-03 asigna a `Task/010` las dos
    implementaciones y deja a `Task/030` el bucket, las politicas, el CORS, el
    *lifecycle* y la expiracion productiva de las prefirmadas.

    `endpoint_url` es **opcional**. Sin el, `boto3` resuelve el endpoint de AWS
    a partir de la region, que es como funciona en produccion. Con el, el mismo
    codigo se ejecuta contra un servicio S3-compatible, y eso es lo que permite
    probarlo **sin AWS real** (`Task/010`) antes de validarlo contra Amazon S3
    de verdad (`Task/030`).

    `access_endpoint_url` tambien es opcional, y en produccion **se omite**: sin
    el, el enlace se firma contra el endpoint de AWS que el SDK resuelve, que es
    el comportamiento correcto. El mecanismo existe aqui para que este adaptador
    no lo impida —un dominio propio o un CDN delante del bucket—, pero **quien
    lo use y con que valor es de `Task/030`** (**D-08**). `Task/010` no impone
    ninguna configuracion productiva nueva.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key: str | None = None,
        secret_key: str | None = None,
        endpoint_url: str | None = None,
        access_endpoint_url: str | None = None,
    ) -> None:
        super().__init__(bucket=bucket)
        self.region = region
        self.endpoint_url = endpoint_url
        self.access_endpoint_url = access_endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key

    def _crear_cliente(self) -> S3Client:
        """Cliente de S3.

        Cuando no hay credenciales explicitas, `boto3` usa su cadena habitual
        —rol de la Lambda, variables de entorno, perfil—, que es lo correcto en
        produccion: el rol de ejecucion es preferible a una credencial estatica
        (requisito S-01). El *wiring* concreto en Lambda es de `Task/032`.

        El estilo de direccionamiento se deriva del endpoint y no es una opcion
        configurable: contra un endpoint propio hace falta la ruta; contra AWS,
        el estilo virtual es el que Amazon recomienda.
        """
        return self._construir_cliente(self.endpoint_url)

    def _crear_cliente_de_firma(self) -> S3Client | None:
        """Cliente de firma, **solo** si se declara un endpoint de acceso propio.

        En produccion no se declara, asi que la base reutiliza el operativo y
        aqui no se construye nada.
        """
        if self.access_endpoint_url is None:
            return None
        return self._construir_cliente(self.access_endpoint_url)

    def _crear_cliente_de_sonda(self) -> S3Client:
        """Cliente de la sonda de disponibilidad: mismo endpoint, timeouts cortos."""
        return self._construir_cliente(self.endpoint_url, para_sonda=True)

    def _construir_cliente(self, endpoint_url: str | None, *, para_sonda: bool = False) -> S3Client:
        """Cliente de S3 apuntado a `endpoint_url`, o al de AWS si es `None`.

        El estilo de direccionamiento se declara **siempre**, y eso es el arreglo
        de **DEF-030-1**. Antes solo se declaraba cuando habia endpoint propio, y
        contra AWS real —sin endpoint— el estilo quedaba sin fijar: `botocore`
        resolvia bien el `endpoint_url` regional del cliente, pero al generar una
        URL **prefirmada** construia el anfitrion heredado global
        `<bucket>.s3.amazonaws.com` mientras la firma llevaba alcance de region.
        S3 respondia **403 SignatureDoesNotMatch**, medido contra el bucket real
        de `Task/030` en us-east-2.

        - Endpoint propio —MinIO, emulador— exige la **ruta**: el estilo virtual
          convertiria el nombre del bucket en un subdominio que la red local no
          resuelve.
        - AWS real usa el **virtual**, que es el que Amazon recomienda y el que
          produce el anfitrion regional `<bucket>.s3.<region>.amazonaws.com`.

        No hay ningun valor fijo aqui: el anfitrion lo deriva el SDK de la region
        configurada.
        """
        import boto3
        from botocore.config import Config

        estilo = "path" if endpoint_url is not None else "virtual"
        opciones: dict[str, object] = {
            "signature_version": "s3v4",
            "s3": {"addressing_style": estilo},
        }
        if para_sonda:
            opciones.update(opciones_de_sonda())

        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self.region,
            config=Config(**opciones),  # type: ignore[arg-type]
        )
