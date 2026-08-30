"""Harness de almacenamiento de objetos para las pruebas (`Task/010`).

Estas pruebas son **destructivas**: crean y borran objetos, y borran el bucket
entero al terminar. Por eso el destino nunca puede ser un bucket de desarrollo
ni, mucho menos, uno real de Amazon S3.

Politica, calcada de la que `Task/005.6` fijo para PostgreSQL — dos casos, y
solo dos:

| Caso | Situacion | Resultado |
| --- | --- | --- |
| 1 | `PERSONAL_BLOG_TEST_STORAGE_ENDPOINT_URL` **no definida** | `SKIP` con motivo |
| 2 | Definida | el almacenamiento **debe** funcionar: cualquier fallo es `FAIL` |

En el caso 2 **nada se convierte en `skip`**: ni credenciales incorrectas, ni
MinIO caido, ni una regresion del SDK. Un `skip` ahi ocultaria exactamente el
defecto que la integracion existe para detectar.

Las variables no llevan el prefijo `BLOG_` a proposito: la suite limpia ese
prefijo del entorno para aislarse de la configuracion de la maquina
(`tests/__init__.py`), y estas deben sobrevivir a esa limpieza. Tampoco se
reutiliza la configuracion de la aplicacion: el destino de las pruebas es una
decision de quien las ejecuta, no del `.env` del desarrollador.

Garantia *fail-closed*
----------------------

**Ninguna fixture de este harness entrega un cliente, un bucket ni una
implementacion de `ObjectStorage` sin que la guarda haya verificado antes que el
destino es seguro.** Todas derivan de `destino_de_almacenamiento_verificado`,
que verifica **antes** de hacer `yield`.

Las cuatro barreras:

1. **Los endpoints deben estar declarados y ser locales.** Se comprueban los
   **dos**, el operativo y el de acceso: un host de AWS es un rechazo
   inmediato, y no hay forma de que una suite que borra buckets acabe hablando
   con Amazon S3 por una variable mal puesta.
2. **El bucket lo crea la propia suite**, con un nombre unico y un prefijo
   inequivoco de prueba. Nunca se reutiliza uno existente, asi que el bucket de
   desarrollo del `.env` no es alcanzable como destino.
3. **La limpieza solo borra el bucket que la suite creo**, y vuelve a comprobar
   el prefijo antes de hacerlo. Un bucket ajeno no puede borrarse ni por error
   de programacion en la propia limpieza.
4. **El harness no usa el codigo que esta probando** para preparar ni para
   limpiar. Si `MinIOStorage` tuviera un defecto, un harness construido sobre el
   podria dejar de limpiar sin que nadie se enterase.

Lo que **no** se afirma —seria falso—: que resulte imposible que codigo Python
cualquiera abra un cliente contra otro destino. `boto3.client` esta al alcance
de quien lo escriba. La garantia es sobre el harness oficial, que es donde una
prueba futura se equivocaria por accidente.

Limite conocido: la limpieza no sobrevive a un `SIGKILL`
---------------------------------------------------------

El borrado del bucket vive en el `finally` de una fixture, asi que **no** se
ejecuta si el proceso muere sin desenrollar la pila: un `kill`, un corte por
tiempo de espera o un apagado. Se observo durante `Task/010`, al cortar una
ejecucion larga: quedo un bucket con sus objetos dentro.

No se intenta arreglar con un manejador de senales, que anadiria una ruta de
codigo dificil de probar para un caso que no corrompe nada. La consecuencia es
solo espacio ocupado, y el diseno ya la hace trivial de resolver: el nombre
lleva el prefijo `personal-blog-test-`, asi que cualquier bucket residual es
inequivocamente descartable y no puede confundirse con el de desarrollo.
Purgarlos es una linea, y pasa por la misma guarda de prefijo:

```python
for bucket in cliente.list_buckets()["Buckets"]:
    if bucket["Name"].startswith(PREFIJO_DE_BUCKET_DE_PRUEBAS):
        _vaciar_y_borrar_el_bucket(cliente, bucket["Name"])
```

Comprobacion estructural: `tests/test_guarda_del_almacenamiento_de_pruebas.py`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

import pytest

if TYPE_CHECKING:  # pragma: no cover - solo para el tipado estatico
    from app.shared.storage import ObjectStorage

VARIABLE_DEL_ENDPOINT: Final = "PERSONAL_BLOG_TEST_STORAGE_ENDPOINT_URL"
VARIABLE_DEL_ENDPOINT_DE_ACCESO: Final = "PERSONAL_BLOG_TEST_STORAGE_ACCESS_ENDPOINT_URL"
VARIABLE_DE_LA_CLAVE: Final = "PERSONAL_BLOG_TEST_STORAGE_ACCESS_KEY"
VARIABLE_DEL_SECRETO: Final = "PERSONAL_BLOG_TEST_STORAGE_SECRET_KEY"

#: Todo bucket creado por la suite empieza asi, y **solo** un bucket con este
#: prefijo puede borrarse. Es la barrera 3.
PREFIJO_DE_BUCKET_DE_PRUEBAS: Final = "personal-blog-test-"

#: Anfitriones aceptados para una suite destructiva. Es una lista blanca a
#: proposito: comprobar "que no sea AWS" fallaria **abierta** ante cualquier
#: otro proveedor remoto que apareciera manana.
ANFITRIONES_LOCALES: Final = frozenset(
    {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"}  # noqa: S104 - lista blanca, no un bind
)

#: Region declarada para el destino local. MinIO acepta cualquiera; se fija una
#: para que la firma sea reproducible y no dependa del entorno.
REGION_DE_PRUEBAS: Final = "us-east-1"


@dataclass(frozen=True)
class DestinoDeAlmacenamiento:
    """Destino de pruebas ya verificado como seguro."""

    endpoint_url: str
    access_key: str
    secret_key: str
    region: str
    bucket: str
    #: Endpoint contra el que se firman los enlaces de acceso. **Distinto** del
    #: operativo a proposito: si fueran el mismo, la suite no podria demostrar
    #: que la separacion existe ni que el enlace funciona de verdad.
    access_endpoint_url: str = ""


def _endpoint_de_acceso_por_defecto(endpoint_operativo: str) -> str:
    """Deriva un endpoint de acceso **distinto** del operativo, y alcanzable.

    En el entorno local, `127.0.0.1` y `localhost` llevan al mismo MinIO pero
    son anfitriones **distintos para la firma**: el `Host` entra en la peticion
    canonica de SigV4. Intercambiarlos da exactamente lo que la prueba
    necesita: dos endpoints distintos, los dos alcanzables desde el host, para
    poder afirmar que el enlace se firmo contra el de acceso y **funciona**.

    Es la propiedad que reproduce en pequeno lo que ocurre en Docker, donde el
    operativo es `minio:9000` y el de acceso `localhost:9000`; alli el primero
    no es alcanzable desde el host, asi que no serviria para preparar el objeto
    que la prueba necesita descargar.
    """
    partes = urlsplit(endpoint_operativo)
    intercambio = {"127.0.0.1": "localhost", "localhost": "127.0.0.1"}
    anfitrion = intercambio.get(partes.hostname or "", partes.hostname or "")
    puerto = f":{partes.port}" if partes.port else ""
    return f"{partes.scheme}://{anfitrion}{puerto}"


def _variable(nombre: str) -> str | None:
    return os.environ.get(nombre)


def _verificar_que_el_endpoint_es_local(endpoint_url: str) -> None:
    """Guarda *fail-closed* previa a cualquier operacion destructiva.

    No comprueba que el destino sea peligroso: exige **demostrar** que es
    seguro. Si el anfitrion no esta en la lista blanca, la respuesta es `FAIL`,
    nunca `skip` y nunca continuar.
    """
    partes = urlsplit(endpoint_url)
    if partes.scheme not in {"http", "https"} or not partes.hostname:
        pytest.fail(
            f"{VARIABLE_DEL_ENDPOINT} no es una URL utilizable. "
            "Se esperaba algo como 'http://127.0.0.1:9000'.",
            pytrace=False,
        )
    if partes.hostname not in ANFITRIONES_LOCALES:
        pytest.fail(
            f"Destino rechazado: el anfitrion '{partes.hostname}' no es local. "
            "Las pruebas de almacenamiento crean y BORRAN un bucket entero, asi que "
            f"solo pueden apuntar a {sorted(ANFITRIONES_LOCALES)}. "
            "Un endpoint remoto —Amazon S3 incluido— es un fallo, no un aviso.",
            pytrace=False,
        )


def _cliente_del_harness(destino_sin_bucket: DestinoDeAlmacenamiento) -> Any:
    """Cliente `boto3` propio del harness.

    Deliberadamente **no** se usa `MinIOStorage` ni `S3Storage` para preparar y
    limpiar: son el codigo bajo prueba. Un defecto en ellos no debe poder
    impedir la limpieza ni falsear la preparacion.
    """
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=destino_sin_bucket.endpoint_url,
        aws_access_key_id=destino_sin_bucket.access_key,
        aws_secret_access_key=destino_sin_bucket.secret_key,
        region_name=destino_sin_bucket.region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _vaciar_y_borrar_el_bucket(cliente: Any, bucket: str) -> None:
    """Borra el bucket de pruebas, y **solo** si su nombre lo acredita."""
    if not bucket.startswith(PREFIJO_DE_BUCKET_DE_PRUEBAS):  # pragma: no cover - barrera
        raise AssertionError(
            f"la limpieza se nego a borrar '{bucket}': no lleva el prefijo "
            f"'{PREFIJO_DE_BUCKET_DE_PRUEBAS}'. Solo se borra lo que la suite creo."
        )
    paginador = cliente.get_paginator("list_objects_v2")
    for pagina in paginador.paginate(Bucket=bucket):
        objetos = [{"Key": elemento["Key"]} for elemento in pagina.get("Contents", ())]
        if objetos:
            cliente.delete_objects(Bucket=bucket, Delete={"Objects": objetos})
    cliente.delete_bucket(Bucket=bucket)


@pytest.fixture(scope="session")
def destino_de_almacenamiento_verificado() -> Iterator[DestinoDeAlmacenamiento]:
    """Resuelve el destino de almacenamiento y **lo verifica antes de entregarlo**.

    Es el unico punto del harness que convierte las variables de entorno en un
    destino utilizable. Todo lo demas se deriva de aqui, igual que
    `destino_de_integracion_verificado` hace con PostgreSQL.

    Unico `skip` admitido: la variable del endpoint no esta definida, es decir,
    no hay entorno de almacenamiento que ejecutar.
    """
    endpoint_url = _variable(VARIABLE_DEL_ENDPOINT)
    if not endpoint_url:
        pytest.skip(f"{VARIABLE_DEL_ENDPOINT} no definida: se omite la integracion de MinIO")

    _verificar_que_el_endpoint_es_local(endpoint_url)

    access_key = _variable(VARIABLE_DE_LA_CLAVE)
    secret_key = _variable(VARIABLE_DEL_SECRETO)
    if not access_key or not secret_key:
        pytest.fail(
            f"{VARIABLE_DEL_ENDPOINT} esta definida pero faltan {VARIABLE_DE_LA_CLAVE} o "
            f"{VARIABLE_DEL_SECRETO}. Con el endpoint definido, la integracion NO se omite: "
            "se exige que funcione.",
            pytrace=False,
        )

    endpoint_de_acceso = _variable(VARIABLE_DEL_ENDPOINT_DE_ACCESO) or (
        _endpoint_de_acceso_por_defecto(endpoint_url)
    )
    # La misma guarda, tambien para el endpoint de acceso: los enlaces que emite
    # la suite no pueden apuntar a ningun anfitrion remoto.
    _verificar_que_el_endpoint_es_local(endpoint_de_acceso)

    destino = DestinoDeAlmacenamiento(
        endpoint_url=endpoint_url,
        access_key=access_key,
        secret_key=secret_key,
        region=REGION_DE_PRUEBAS,
        bucket=f"{PREFIJO_DE_BUCKET_DE_PRUEBAS}{uuid.uuid4().hex[:12]}",
        access_endpoint_url=endpoint_de_acceso,
    )

    cliente = _cliente_del_harness(destino)
    try:
        cliente.create_bucket(Bucket=destino.bucket)
    # `Exception` a proposito: credenciales, servicio caido o una regresion del
    # SDK son fallos reales del entorno, y ninguno puede degradarse a `skip`.
    except Exception as error:
        pytest.fail(
            f"{VARIABLE_DEL_ENDPOINT} esta definida pero el almacenamiento no responde: "
            f"{type(error).__name__}: {error}. "
            "Comprobar que MinIO esta levantado (docker compose ps).",
            pytrace=False,
        )

    try:
        yield destino
    finally:
        _vaciar_y_borrar_el_bucket(cliente, destino.bucket)


@pytest.fixture
def prefijo_de_la_prueba(request: pytest.FixtureRequest) -> str:
    """Prefijo de clave propio de cada prueba.

    Todas las pruebas comparten un unico bucket —crear uno por prueba
    multiplicaria el tiempo sin anadir aislamiento real—, asi que el aislamiento
    lo da la clave: dos pruebas nunca escriben sobre el mismo objeto.
    """
    return f"pruebas/{request.node.name}/{uuid.uuid4().hex[:8]}"


@pytest.fixture
def almacenamiento_minio(destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento) -> Any:
    """`MinIOStorage` apuntando al destino de pruebas ya verificado."""
    from app.shared.storage import MinIOStorage

    return MinIOStorage(
        bucket=destino_de_almacenamiento_verificado.bucket,
        endpoint_url=destino_de_almacenamiento_verificado.endpoint_url,
        access_endpoint_url=destino_de_almacenamiento_verificado.access_endpoint_url,
        access_key=destino_de_almacenamiento_verificado.access_key,
        secret_key=destino_de_almacenamiento_verificado.secret_key,
        region=destino_de_almacenamiento_verificado.region,
    )


@pytest.fixture
def almacenamiento_s3(destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento) -> Any:
    """`S3Storage` apuntando al **mismo** endpoint S3-compatible local.

    Es como se prueba el codigo real del adaptador de produccion **sin Amazon S3
    real** (STAGE-03: `Task/010` no necesita AWS). Lo que aqui se demuestra es
    que `S3Storage` habla el protocolo S3 correctamente; que el bucket, las
    politicas y los permisos de AWS sean los correctos es de `Task/030`.
    """
    from app.shared.storage import S3Storage

    return S3Storage(
        bucket=destino_de_almacenamiento_verificado.bucket,
        endpoint_url=destino_de_almacenamiento_verificado.endpoint_url,
        access_endpoint_url=destino_de_almacenamiento_verificado.access_endpoint_url,
        access_key=destino_de_almacenamiento_verificado.access_key,
        secret_key=destino_de_almacenamiento_verificado.secret_key,
        region=destino_de_almacenamiento_verificado.region,
    )


@pytest.fixture(params=["minio", "s3"])
def almacenamiento(request: pytest.FixtureRequest) -> ObjectStorage:
    """Las **dos** implementaciones, para la misma suite de contrato.

    Parametrizar aqui es lo que convierte el contrato en un contrato: cada caso
    se ejecuta contra `MinIOStorage` y contra `S3Storage`, y ninguna de las dos
    puede desviarse de la semantica acordada sin ponerse roja.
    """
    implementacion: ObjectStorage = request.getfixturevalue(f"almacenamiento_{request.param}")
    return implementacion
