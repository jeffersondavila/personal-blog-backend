"""Invariantes propias de cada adaptador de almacenamiento.

El contrato comun vive en `tests/contract/test_contrato_de_object_storage.py` y
demuestra que las dos implementaciones se comportan igual. Aqui se comprueba lo
contrario: en que **no** son intercambiables, que es lo que impide que
`MinIOStorage` sea un alias vacio de `S3Storage` (riesgo 2 de la ficha).

| Adaptador | Invariante |
| --- | --- |
| `MinIOStorage` | Exige endpoint explicito y **no puede** apuntar a AWS |
| `S3Storage` | Funciona **sin** endpoint y **nunca** crea un bucket |

Aqui vive tambien la separacion entre los **dos endpoints** —el operativo y el
de acceso—, que es una propiedad del adaptador y no del contrato: el contrato
solo exige que el enlace funcione, no desde que anfitrion se firma.

Ninguna de estas pruebas necesita MinIO: comprueban construccion y politica, no
transporte.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.shared.storage import (
    ConfiguracionDeAlmacenamientoInvalidaError,
    MinIOStorage,
    S3Storage,
)

CREDENCIALES = {"access_key": "clave-de-prueba", "secret_key": "secreto-de-prueba"}


class _ClienteQueRegistra:
    """Doble de cliente S3 que anota cada operacion que se le pide.

    No simula el protocolo: solo registra. Se usa para afirmaciones sobre **que
    operaciones ejecuta el adaptador**, que es politica del adaptador y no del
    servicio; el comportamiento real se prueba contra MinIO en el contrato.
    """

    def __init__(self) -> None:
        self.operaciones: list[str] = []

    def __getattr__(self, nombre: str) -> Any:
        def _registrar(*_: object, **__: object) -> dict[str, Any]:
            self.operaciones.append(nombre)
            return {}

        return _registrar


# --- M-02 ------------------------------------------------------------------
@pytest.mark.parametrize(
    "endpoint",
    [
        "https://s3.amazonaws.com",
        "https://s3.us-east-1.amazonaws.com",
        "https://mi-bucket.s3.eu-west-1.amazonaws.com",
    ],
)
def test_minio_storage_rechaza_un_endpoint_de_aws(endpoint: str) -> None:
    """El adaptador **local** no puede acabar hablando con Amazon S3.

    Es la misma filosofia que la guarda de destino de PostgreSQL: una variable
    de entorno mal puesta no debe poder convertir el adaptador de desarrollo en
    un cliente de produccion. La comprobacion se hace al **construir**, antes de
    que exista cliente alguno.

    Se prohiben los anfitriones de AWS en lugar de exigir una lista blanca de
    anfitriones locales **a proposito**: en el entorno de Docker Compose el
    endpoint legitimo es `http://personal-blog-local-minio:9000`, que no es
    local segun ninguna lista blanca razonable. La lista blanca si se aplica,
    en cambio, en el harness de pruebas, porque alli lo que esta en juego es
    borrar un bucket entero.
    """
    with pytest.raises(ConfiguracionDeAlmacenamientoInvalidaError):
        MinIOStorage(bucket="cualquiera", endpoint_url=endpoint, region="us-east-1", **CREDENCIALES)


# --- M-03 ------------------------------------------------------------------
@pytest.mark.parametrize("endpoint", ["", "   ", "no-es-una-url", "ftp://127.0.0.1:9000"])
def test_minio_storage_exige_un_endpoint_utilizable(endpoint: str) -> None:
    """Sin endpoint no hay MinIO: no existe un valor por defecto razonable."""
    with pytest.raises(ConfiguracionDeAlmacenamientoInvalidaError):
        MinIOStorage(bucket="cualquiera", endpoint_url=endpoint, region="us-east-1", **CREDENCIALES)


def test_minio_storage_acepta_el_endpoint_de_la_red_de_docker() -> None:
    """Guarda anti-tautologia: la prohibicion no puede rechazarlo todo."""
    almacenamiento = MinIOStorage(
        bucket="cualquiera",
        endpoint_url="http://personal-blog-local-minio:9000",
        region="us-east-1",
        **CREDENCIALES,
    )

    assert almacenamiento.endpoint_url == "http://personal-blog-local-minio:9000"


# --- S-02 ------------------------------------------------------------------
def test_s3_storage_se_construye_sin_endpoint_declarado() -> None:
    """En produccion el endpoint lo resuelve el SDK a partir de la region."""
    almacenamiento = S3Storage(bucket="bucket-de-produccion", region="eu-west-1")

    assert almacenamiento.endpoint_url is None
    assert almacenamiento.bucket == "bucket-de-produccion"


def test_s3_storage_resuelve_un_endpoint_de_aws_cuando_no_se_declara() -> None:
    """Comprobacion de que la construccion sin endpoint produce un cliente de AWS.

    No hay red: `boto3` resuelve el endpoint a partir de la region antes de
    cualquier peticion. Es lo que demuestra que `S3Storage` es codigo real de
    produccion y no una variante de `MinIOStorage` con otro nombre.
    """
    almacenamiento = S3Storage(bucket="bucket-de-produccion", region="eu-west-1", **CREDENCIALES)

    punto_final = almacenamiento._cliente.meta.endpoint_url

    assert "amazonaws.com" in punto_final
    assert "eu-west-1" in punto_final


# --- S-04 ------------------------------------------------------------------
def test_s3_storage_nunca_crea_un_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Crear el bucket es infraestructura, y la infraestructura es de `Task/030`.

    Un adaptador que creara su bucket al arrancar convertiria un despliegue en
    una operacion de infraestructura silenciosa, fuera de Terraform, que es la
    fuente de verdad (AWS LOCAL PARITY LAW).
    """
    cliente = _ClienteQueRegistra()
    almacenamiento = S3Storage(bucket="b", region="eu-west-1", **CREDENCIALES)
    monkeypatch.setattr(S3Storage, "_crear_cliente", lambda _: cliente)

    almacenamiento.guardar(clave="k", contenido=b"x", tipo_de_contenido="image/png")
    almacenamiento.existe("k")
    almacenamiento.eliminar("k")

    assert "create_bucket" not in cliente.operaciones
    assert cliente.operaciones == ["put_object", "head_object", "delete_object"]


# --- Riesgo 3: la firma es local ------------------------------------------
def test_firmar_un_acceso_temporal_no_necesita_llegar_al_almacenamiento() -> None:
    """`acceso_temporal` no puede introducir una llamada de red por medio.

    Un listado publico de doce elementos con portada emite doce enlaces. Si cada
    uno costara un viaje al almacenamiento, la pagina publica pasaria a depender
    de la latencia de S3 (requisito P-08).

    Se demuestra apuntando a un puerto cerrado: si hubiera E/S, la operacion
    fallaria. Que devuelva una URL prueba que la firma es un HMAC local.
    """
    almacenamiento = MinIOStorage(
        bucket="bucket-inalcanzable",
        endpoint_url="http://127.0.0.1:1",
        region="us-east-1",
        **CREDENCIALES,
    )

    acceso = almacenamiento.acceso_temporal("medios/x/original.png", duracion=timedelta(minutes=5))

    assert acceso.url.startswith("http://127.0.0.1:1/")
    assert "X-Amz-Signature" in acceso.url


# --- Separacion entre el endpoint operativo y el de acceso ----------------
#
# El backend en Docker alcanza MinIO por el nombre de servicio de la red
# (`minio:9000`). El navegador del host **no resuelve ese nombre**, asi que un
# enlace firmado contra el es inservible para su unico consumidor.
#
# Y no puede arreglarse despues: el `Host` entra en la peticion canonica de
# **AWS Signature Version 4**, asi que reescribir el anfitrion de una URL ya
# firmada invalida la firma. Comprobado contra MinIO real durante `Task/010`:
# la URL original devuelve `200` y la misma URL con el anfitrion cambiado
# devuelve `403 SignatureDoesNotMatch`.
#
# La consecuencia de diseno es que el endpoint de acceso tiene que participar
# en la firma **desde el principio**, no despues.

INTERNO = "http://minio:9000"
EXTERNO = "http://localhost:9000"


def _minio(**extra: object) -> MinIOStorage:
    argumentos: dict[str, Any] = {
        "bucket": "personal-blog-media",
        "endpoint_url": INTERNO,
        "region": "us-east-1",
        **CREDENCIALES,
        **extra,
    }
    return MinIOStorage(**argumentos)


def test_el_enlace_de_acceso_se_firma_contra_el_endpoint_externo() -> None:
    """El consumidor del enlace es el navegador del host, no el backend."""
    almacenamiento = _minio(access_endpoint_url=EXTERNO)

    acceso = almacenamiento.acceso_temporal("medios/x/original.png", duracion=timedelta(minutes=5))

    assert acceso.url.startswith(f"{EXTERNO}/")
    assert "minio:9000" not in acceso.url


def test_las_operaciones_siguen_usando_el_endpoint_interno() -> None:
    """Separar los endpoints no puede desviar el trafico real del backend.

    Si las operaciones salieran por `localhost`, el contenedor del backend
    intentaria hablar consigo mismo y la subida fallaria.
    """
    almacenamiento = _minio(access_endpoint_url=EXTERNO)

    assert almacenamiento._cliente.meta.endpoint_url == INTERNO
    assert almacenamiento._cliente_de_firma.meta.endpoint_url == EXTERNO


def test_sin_endpoint_de_acceso_se_firma_contra_el_operativo() -> None:
    """Comportamiento por defecto: un solo endpoint, como antes.

    Es lo que mantiene intacto el caso de produccion, donde el endpoint de AWS
    lo resuelve el SDK y no hay ninguna separacion que hacer.
    """
    almacenamiento = _minio()

    acceso = almacenamiento.acceso_temporal("medios/x/original.png", duracion=timedelta(minutes=5))

    assert acceso.url.startswith(f"{INTERNO}/")
    assert almacenamiento._cliente_de_firma is almacenamiento._cliente


@pytest.mark.parametrize("endpoint", ["no-es-una-url", "ftp://localhost:9000", "   "])
def test_un_endpoint_de_acceso_malformado_se_rechaza(endpoint: str) -> None:
    """Fail-fast: se comprueba al construir, no al emitir el primer enlace."""
    with pytest.raises(ConfiguracionDeAlmacenamientoInvalidaError):
        _minio(access_endpoint_url=endpoint)


def test_el_endpoint_de_acceso_de_minio_tampoco_puede_ser_de_aws() -> None:
    """La misma guarda que el operativo, por la misma razon.

    Un enlace del adaptador local que apuntara a Amazon S3 seria tan incorrecto
    como una operacion que escribiera alli.
    """
    with pytest.raises(ConfiguracionDeAlmacenamientoInvalidaError):
        _minio(access_endpoint_url="https://s3.eu-west-1.amazonaws.com")


def test_s3_sin_endpoint_de_acceso_firma_contra_el_endpoint_de_aws() -> None:
    """Produccion no necesita configurar nada nuevo (requisito de `Task/030`).

    Sin endpoint operativo ni de acceso, el SDK resuelve el de AWS y firma
    contra el: la separacion es un mecanismo disponible, no una obligacion.
    """
    almacenamiento = S3Storage(bucket="bucket-de-produccion", region="eu-west-1", **CREDENCIALES)

    acceso = almacenamiento.acceso_temporal("medios/x/original.png", duracion=timedelta(minutes=5))

    assert "amazonaws.com" in acceso.url
    assert "eu-west-1" in acceso.url
    assert almacenamiento._cliente_de_firma is almacenamiento._cliente


def test_s3_admite_un_endpoint_de_acceso_distinto_del_operativo() -> None:
    """El mecanismo existe tambien para `S3Storage`.

    Quien lo use y con que valor —un dominio propio, un CDN— es de `Task/030`
    (**D-08**). Aqui solo se garantiza que el adaptador no lo impide.
    """
    almacenamiento = S3Storage(
        bucket="b",
        region="eu-west-1",
        endpoint_url="http://127.0.0.1:9000",
        access_endpoint_url="http://localhost:9000",
        **CREDENCIALES,
    )

    acceso = almacenamiento.acceso_temporal("k", duracion=timedelta(minutes=5))

    assert acceso.url.startswith("http://localhost:9000/")
    assert almacenamiento._cliente.meta.endpoint_url == "http://127.0.0.1:9000"
