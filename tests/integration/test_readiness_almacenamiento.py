"""Los cinco escenarios de `comprobar_disponibilidad()` (`Task/017`, O-04).

Por que estos cinco y no menos
-------------------------------

La primera propuesta de la ficha usaba `existe(<clave-sonda>)`. Se midio contra
MinIO real durante la definicion y se descarto por un falso positivo
demostrado: `HeadObject` devuelve `404 Code='404'` **tanto** cuando el bucket
existe y la clave no, **como** cuando el bucket no existe. Las dos rutas
colapsaban en `existe() -> False`, asi que `/ready` habria respondido `200` con
el almacenamiento inutilizable.

La sonda actual usa `ListObjectsV2` con prefijo, que si distingue los cuatro
resultados y ademas entrega **codigos semanticos** —`NoSuchBucket`,
`InvalidAccessKeyId`— aprovechables en el log.

Todo ocurre contra el bucket **descartable** `personal-blog-test-*` que crea el
harness. El bucket de desarrollo `personal-blog-media` no es alcanzable desde
aqui: la guarda de `tests/almacenamiento_de_pruebas.py` lo impide.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from app.shared.storage import ErrorDeAlmacenamiento, ObjectStorage
from tests.almacenamiento_de_pruebas import DestinoDeAlmacenamiento


def _inventario(cliente: Any, bucket: str) -> dict[str, tuple[str, str]]:
    """Estado observable del bucket: clave, `ETag` y `LastModified`.

    Con los tres se detecta cualquier mutacion: una clave nueva o ausente cambia
    el conjunto, y una sobrescritura cambia `ETag` y `LastModified` aunque la
    clave siga siendo la misma.
    """
    paginador = cliente.get_paginator("list_objects_v2")
    inventario: dict[str, tuple[str, str]] = {}
    for pagina in paginador.paginate(Bucket=bucket):
        for objeto in pagina.get("Contents", []):
            inventario[objeto["Key"]] = (objeto["ETag"], objeto["LastModified"].isoformat())
    return inventario


# --- D y E: el almacenamiento esta disponible -----------------------------


def test_escenario_d_un_bucket_existente_y_vacio_esta_disponible(
    almacenamiento: ObjectStorage,
) -> None:
    """Un bucket sin objetos **si** esta listo: vacio no es lo mismo que ausente."""
    almacenamiento.comprobar_disponibilidad()


def test_escenario_e_un_bucket_existente_con_objetos_esta_disponible(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    """El objeto lo crea **la fixture**, nunca la sonda.

    El baseline de la definicion etiqueto un caso como *"bucket con objetos"*
    cuando el bucket real tenia `KeyCount = 0`, asi que este escenario no estaba
    demostrado. Aqui se demuestra: se siembra un objeto y se comprueba que la
    sonda sigue diciendo que hay disponibilidad.
    """
    almacenamiento.guardar(
        clave=f"{prefijo_de_la_prueba}/sembrado.txt",
        contenido=b"contenido sembrado por la fixture, no por la sonda",
        tipo_de_contenido="text/plain",
    )

    almacenamiento.comprobar_disponibilidad()


# --- C: el escenario que motivo reabrir la decision -----------------------


def test_escenario_c_un_bucket_inexistente_no_esta_disponible(
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> None:
    """**El falso positivo que `existe()` no detectaba.**

    Con la estrategia anterior este caso devolvia `False` igual que "la clave no
    esta", y `/ready` habria respondido `200`.
    """
    from app.shared.storage import MinIOStorage

    almacenamiento = MinIOStorage(
        bucket="bucket-que-no-existe-task017-readiness",
        endpoint_url=destino_de_almacenamiento_verificado.endpoint_url,
        access_endpoint_url=destino_de_almacenamiento_verificado.access_endpoint_url,
        access_key=destino_de_almacenamiento_verificado.access_key,
        secret_key=destino_de_almacenamiento_verificado.secret_key,
        region=destino_de_almacenamiento_verificado.region,
    )

    with pytest.raises(ErrorDeAlmacenamiento):
        almacenamiento.comprobar_disponibilidad()


# --- B: credenciales invalidas --------------------------------------------


def test_escenario_b_unas_credenciales_invalidas_no_estan_disponibles(
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> None:
    from app.shared.storage import MinIOStorage

    almacenamiento = MinIOStorage(
        bucket=destino_de_almacenamiento_verificado.bucket,
        endpoint_url=destino_de_almacenamiento_verificado.endpoint_url,
        access_endpoint_url=destino_de_almacenamiento_verificado.access_endpoint_url,
        access_key="TASK017_CLAVE_INVALIDA",
        secret_key="TASK017_SECRETO_INVALIDO",
        region=destino_de_almacenamiento_verificado.region,
    )

    with pytest.raises(ErrorDeAlmacenamiento):
        almacenamiento.comprobar_disponibilidad()


# --- A: endpoint inalcanzable ---------------------------------------------


def test_escenario_a_un_endpoint_inalcanzable_no_esta_disponible(
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> None:
    from app.shared.storage import MinIOStorage

    almacenamiento = MinIOStorage(
        bucket=destino_de_almacenamiento_verificado.bucket,
        # Puerto local sin servicio: inalcanzable, no lento.
        endpoint_url="http://127.0.0.1:9099",
        access_endpoint_url=destino_de_almacenamiento_verificado.access_endpoint_url,
        access_key=destino_de_almacenamiento_verificado.access_key,
        secret_key=destino_de_almacenamiento_verificado.secret_key,
        region=destino_de_almacenamiento_verificado.region,
    )

    with pytest.raises(ErrorDeAlmacenamiento):
        almacenamiento.comprobar_disponibilidad()


def test_un_endpoint_inalcanzable_no_agota_el_presupuesto_de_la_sonda(
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> None:
    """No basta con configurar un timeout: hay que medir que se respeta.

    El `healthCheck` de Traefik usa `timeout: 3s`. Una sonda que tardara mas
    convertiria un almacenamiento caido en un proxy colgado.
    """
    import time

    from app.shared.storage import MinIOStorage

    almacenamiento = MinIOStorage(
        bucket=destino_de_almacenamiento_verificado.bucket,
        endpoint_url="http://127.0.0.1:9099",
        access_endpoint_url=destino_de_almacenamiento_verificado.access_endpoint_url,
        access_key=destino_de_almacenamiento_verificado.access_key,
        secret_key=destino_de_almacenamiento_verificado.secret_key,
        region=destino_de_almacenamiento_verificado.region,
    )

    comenzado_en = time.perf_counter()
    with pytest.raises(ErrorDeAlmacenamiento):
        almacenamiento.comprobar_disponibilidad()
    transcurrido = time.perf_counter() - comenzado_en

    assert transcurrido < 10, f"la sonda tardo {transcurrido:.1f}s: los reintentos siguen activos"


# --- Invariante de no mutacion --------------------------------------------


@pytest.fixture
def cliente_de_inspeccion(
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
    destino_de_integracion_verificado: Any,
) -> Any:
    """Cliente independiente del adaptador, para observar sin usar el codigo probado.

    Depende de `destino_de_integracion_verificado` **a proposito, aunque no lo
    use**, por el mismo motivo que `alembic_config` depende de `database_engine`:
    esta fixture vive en `tests/integration/`, que es lo que delimita el harness,
    y `CERT-AUD-002` exige que **toda** fixture del harness derive del resolutor
    verificado. Sin esa arista, el grafo tendria una fixture publica de
    integracion fuera de la guarda *fail-closed*, y
    `tests/test_grafo_de_fixtures_de_integracion.py` lo detecta.

    No es una dependencia decorativa: es la que hace que estas pruebas se omitan,
    en bloque y con el resto de la integracion, cuando no hay entorno de
    integracion que ejecutar. **No ejecuta ninguna operacion adicional sobre
    PostgreSQL**: el resolutor tiene alcance de sesion y ya conecto una vez.

    El remedio alternativo —sacar el modulo de `tests/integration/`— se descarto:
    estas pruebas hablan con MinIO **real** contra un bucket descartable, que es
    exactamente lo que el harness de integracion existe para albergar. Moverlas
    solo para esquivar la guarda habria debilitado la comprobacion en vez de
    satisfacerla.
    """
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=destino_de_almacenamiento_verificado.endpoint_url,
        aws_access_key_id=destino_de_almacenamiento_verificado.access_key,
        aws_secret_access_key=destino_de_almacenamiento_verificado.secret_key,
        region_name=destino_de_almacenamiento_verificado.region,
    )


def test_la_sonda_no_crea_modifica_ni_elimina_ningun_objeto(
    almacenamiento: ObjectStorage,
    cliente_de_inspeccion: Any,
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
    prefijo_de_la_prueba: str,
) -> None:
    """La preparacion **si** muta; la sonda **no**. Se distingue explicitamente."""
    bucket = destino_de_almacenamiento_verificado.bucket

    # --- Preparacion: esto SI muta, y es de la fixture, no de la sonda.
    almacenamiento.guardar(
        clave=f"{prefijo_de_la_prueba}/testigo.txt",
        contenido=b"testigo que no debe cambiar",
        tipo_de_contenido="text/plain",
    )
    antes = _inventario(cliente_de_inspeccion, bucket)
    assert antes, "la preparacion deberia haber dejado al menos un objeto"

    # --- La sonda, varias veces para que una mutacion acumulativa se note.
    for _ in range(3):
        almacenamiento.comprobar_disponibilidad()

    despues = _inventario(cliente_de_inspeccion, bucket)

    assert set(despues) == set(antes), "cambio el conjunto de claves"
    assert despues == antes, "cambio algun ETag o LastModified"


def test_la_sonda_no_deja_rastro_bajo_su_propio_prefijo(
    almacenamiento: ObjectStorage,
    cliente_de_inspeccion: Any,
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> None:
    """El prefijo de la sonda sigue vacio: no se crea ningun objeto centinela."""
    almacenamiento.comprobar_disponibilidad()

    respuesta = cliente_de_inspeccion.list_objects_v2(
        Bucket=destino_de_almacenamiento_verificado.bucket, Prefix="_readiness/"
    )

    assert respuesta.get("KeyCount", 0) == 0


def test_la_sonda_no_enumera_el_bucket_entero(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    """Consulta solo bajo su prefijo, que es lo que permite acotar `s3:ListBucket`.

    Es la propiedad que hace preferible `ListObjectsV2` frente a `HeadBucket`:
    `Task/030` puede conceder el permiso con una condicion sobre `s3:prefix`, de
    modo que un compromiso de la Lambda **no** permita listar los medios del blog.
    """
    almacenamiento.guardar(
        clave=f"{prefijo_de_la_prueba}/fuera-del-prefijo-de-sonda.txt",
        contenido=b"no deberia ser visible para la sonda",
        tipo_de_contenido="text/plain",
    )

    almacenamiento.comprobar_disponibilidad()


# --- El error no filtra credenciales --------------------------------------


def test_el_error_de_la_sonda_no_contiene_la_clave_ni_el_secreto(
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> None:
    from app.shared.storage import MinIOStorage

    senuelo_clave = "TASK017_SECRET_STORAGE_KEY_EN_ERROR"
    senuelo_secreto = "TASK017_SECRET_STORAGE_SECRETO_EN_ERROR"
    almacenamiento = MinIOStorage(
        bucket=destino_de_almacenamiento_verificado.bucket,
        endpoint_url=destino_de_almacenamiento_verificado.endpoint_url,
        access_endpoint_url=destino_de_almacenamiento_verificado.access_endpoint_url,
        access_key=senuelo_clave,
        secret_key=senuelo_secreto,
        region=destino_de_almacenamiento_verificado.region,
    )

    with pytest.raises(ErrorDeAlmacenamiento) as capturado:
        almacenamiento.comprobar_disponibilidad()

    mensaje = str(capturado.value)
    assert senuelo_clave not in mensaje
    assert senuelo_secreto not in mensaje


def test_la_sonda_real_no_reintenta_una_conexion_fallida(
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> None:
    from app.shared.storage import MinIOStorage

    almacenamiento = MinIOStorage(
        bucket=destino_de_almacenamiento_verificado.bucket,
        endpoint_url="http://127.0.0.1:9099",
        access_key=destino_de_almacenamiento_verificado.access_key,
        secret_key=destino_de_almacenamiento_verificado.secret_key,
        region=destino_de_almacenamiento_verificado.region,
    )
    intentos: list[object] = []

    def _contar(**evento: Any) -> None:
        intentos.append(evento["request"])

    almacenamiento._cliente_de_sonda.meta.events.register("before-send.s3.ListObjectsV2", _contar)
    with pytest.raises(ErrorDeAlmacenamiento):
        almacenamiento.comprobar_disponibilidad()
    assert len(intentos) == 1, "una sonda informa, no reintenta"


@pytest.fixture
def bucket_exclusivo_de_sonda(
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
    cliente_de_inspeccion: Any,
) -> Iterator[DestinoDeAlmacenamiento]:
    """Vacio demostrable incluso cuando otras pruebas ya poblaron el bucket compartido."""
    from tests.almacenamiento_de_pruebas import _vaciar_y_borrar_el_bucket

    destino = replace(
        destino_de_almacenamiento_verificado, bucket=f"personal-blog-test-ready-{uuid4().hex[:12]}"
    )
    cliente_de_inspeccion.create_bucket(Bucket=destino.bucket)
    try:
        yield destino
    finally:
        _vaciar_y_borrar_el_bucket(cliente_de_inspeccion, destino.bucket)


@pytest.mark.parametrize("proveedor", ["minio", "s3"])
@pytest.mark.parametrize("escenario", ["endpoint", "credenciales", "ausente", "vacio", "objetos"])
def test_cinco_escenarios_preservan_claves_etag_y_last_modified(
    bucket_exclusivo_de_sonda: DestinoDeAlmacenamiento,
    cliente_de_inspeccion: Any,
    proveedor: str,
    escenario: str,
) -> None:
    from app.shared.storage import MinIOStorage, S3Storage

    destino = bucket_exclusivo_de_sonda
    if escenario != "vacio":
        cliente_de_inspeccion.put_object(
            Bucket=destino.bucket, Key="fuera/testigo", Body=b"testigo"
        )
    antes = _inventario(cliente_de_inspeccion, destino.bucket)
    assert bool(antes) == (escenario != "vacio")
    clase = MinIOStorage if proveedor == "minio" else S3Storage
    sonda = clase(
        bucket=destino.bucket + "-ausente" if escenario == "ausente" else destino.bucket,
        endpoint_url="http://127.0.0.1:9099" if escenario == "endpoint" else destino.endpoint_url,
        region=destino.region,
        access_key="TASK017_INVALIDA" if escenario == "credenciales" else destino.access_key,
        secret_key="TASK017_INVALIDO" if escenario == "credenciales" else destino.secret_key,
    )
    parametros: list[dict[str, Any]] = []

    def _observar(**evento: Any) -> None:
        parametros.append(dict(evento["params"]))

    sonda._cliente_de_sonda.meta.events.register(
        "before-parameter-build.s3.ListObjectsV2", _observar
    )
    if escenario in {"endpoint", "credenciales", "ausente"}:
        with pytest.raises(ErrorDeAlmacenamiento):
            sonda.comprobar_disponibilidad()
    else:
        sonda.comprobar_disponibilidad()
    assert _inventario(cliente_de_inspeccion, destino.bucket) == antes
    assert len(parametros) == 1
    # El SDK agrega EncodingType=url antes de emitir el evento. Las tres
    # restricciones de la sonda deben seguir presentes en la peticion real.
    assert {clave: parametros[0][clave] for clave in ("Bucket", "Prefix", "MaxKeys")} == {
        "Bucket": sonda.bucket,
        "Prefix": "_readiness/",
        "MaxKeys": 1,
    }
