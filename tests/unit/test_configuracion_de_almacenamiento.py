"""Configuracion del almacenamiento y seleccion de la implementacion.

`software-architecture.md` seccion 3.7 lo exige en una frase: *"cambiar de MinIO
a S3 debe requerir cambiar **configuracion**, no codigo de dominio"*. Eso obliga
a dos cosas comprobables:

1. Que exista **un** punto donde se elige la implementacion. Un `if app_env ==
   ...` repartido por la aplicacion seria codigo, no configuracion.
2. Que la configuracion **falle al arrancar** si es invalida o esta incompleta
   (requisito T-01), en lugar de fallar en la primera subida.

Y una tercera, de seguridad: que el secreto no aparezca ni en `repr` ni en el
mensaje de error (requisito S-08). La configuracion se imprime en los logs de
arranque, asi que esto no es teorico.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

import pytest

from app.shared.configuration import ConfigurationError
from app.shared.configuration.settings import build_settings
from app.shared.storage import MinIOStorage, S3Storage
from app.shared.storage.fabrica import crear_almacenamiento, obtener_almacenamiento
from tests import FAKE_DATABASE_URL

SECRETO = "secreto-que-no-debe-aparecer"

CONFIGURACION_MINIMA: dict[str, Any] = {
    "app_env": "test",
    "database_url": FAKE_DATABASE_URL,
    "log_format": "text",
    "_env_file": None,
}

ALMACENAMIENTO_MINIO: dict[str, Any] = {
    "storage_provider": "minio",
    "storage_bucket": "bucket-local",
    "storage_endpoint_url": "http://127.0.0.1:9000",
    "storage_access_key": "clave-local",
    "storage_secret_key": SECRETO,
}

#: Configuracion equivalente a la que `docker-compose.yml` da al backend: el
#: endpoint operativo es el nombre de servicio de la red de Docker, y el de
#: acceso es el que el navegador del host si alcanza.
ALMACENAMIENTO_EN_DOCKER: dict[str, Any] = {
    **ALMACENAMIENTO_MINIO,
    "storage_endpoint_url": "http://minio:9000",
    "storage_access_endpoint_url": "http://localhost:9000",
}

ALMACENAMIENTO_S3: dict[str, Any] = {
    "storage_provider": "s3",
    "storage_bucket": "bucket-de-produccion",
    "storage_region": "eu-west-1",
}


# --- C-01 ------------------------------------------------------------------
def test_la_fabrica_devuelve_minio_para_el_proveedor_local() -> None:
    configuracion = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_MINIO)

    almacenamiento = crear_almacenamiento(configuracion)

    assert isinstance(almacenamiento, MinIOStorage)
    assert almacenamiento.bucket == "bucket-local"


# --- C-02 ------------------------------------------------------------------
def test_la_fabrica_devuelve_s3_para_el_proveedor_de_produccion() -> None:
    configuracion = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_S3)

    almacenamiento = crear_almacenamiento(configuracion)

    assert isinstance(almacenamiento, S3Storage)
    assert almacenamiento.bucket == "bucket-de-produccion"


# --- C-03 ------------------------------------------------------------------
def test_un_proveedor_desconocido_impide_arrancar() -> None:
    """Elegir el proveedor con una cadena libre convertiria una errata en un fallo
    silencioso; el tipo cerrado lo convierte en un fallo de arranque."""
    with pytest.raises(ConfigurationError) as fallo:
        build_settings(
            **CONFIGURACION_MINIMA, **{**ALMACENAMIENTO_MINIO, "storage_provider": "azure"}
        )

    assert "storage_provider" in str(fallo.value)


# --- C-04 ------------------------------------------------------------------
def _sin_configuracion_de_almacenamiento_en_el_entorno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retira del entorno lo que el harness repone en cada prueba.

    `tests/conftest.py` fija un almacenamiento ficticio antes de cada prueba,
    porque sin el ninguna configuracion seria construible. Para comprobar que
    **falta** una variable hay que retirarla explicitamente, que es lo que el
    propio harness documenta como forma correcta de hacerlo.
    """
    for nombre in list(os.environ):
        if nombre.upper().startswith("BLOG_STORAGE_"):
            monkeypatch.delenv(nombre, raising=False)


def test_sin_bucket_el_proceso_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _sin_configuracion_de_almacenamiento_en_el_entorno(monkeypatch)

    with pytest.raises(ConfigurationError) as fallo:
        build_settings(**CONFIGURACION_MINIMA)

    assert "storage_bucket" in str(fallo.value)


@pytest.mark.parametrize(
    "ausente", ["storage_endpoint_url", "storage_access_key", "storage_secret_key"]
)
def test_minio_sin_su_configuracion_obligatoria_no_arranca(
    ausente: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MinIO no tiene cadena de credenciales alternativa: si falta, falta.

    `S3Storage` si puede prescindir de claves explicitas —en produccion usa el
    rol de ejecucion (requisito S-01)—, asi que la obligatoriedad depende del
    proveedor y se comprueba despues de resolverlo.
    """
    _sin_configuracion_de_almacenamiento_en_el_entorno(monkeypatch)
    incompleta = {clave: valor for clave, valor in ALMACENAMIENTO_MINIO.items() if clave != ausente}

    with pytest.raises(ConfigurationError) as fallo:
        build_settings(**CONFIGURACION_MINIMA, **incompleta)

    assert ausente.removeprefix("storage_") in str(fallo.value).lower()


# --- C-05 ------------------------------------------------------------------
def test_el_secreto_no_aparece_en_la_representacion_de_la_configuracion() -> None:
    configuracion = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_MINIO)

    assert SECRETO not in repr(configuracion)
    assert SECRETO not in str(configuracion)


def test_el_secreto_no_aparece_en_el_mensaje_de_un_fallo_de_configuracion() -> None:
    """Un error de arranque acaba en el log; un log acaba en observabilidad."""
    with pytest.raises(ConfigurationError) as fallo:
        build_settings(
            **CONFIGURACION_MINIMA,
            **{**ALMACENAMIENTO_MINIO, "storage_access_ttl_seconds": 0},
        )

    assert SECRETO not in str(fallo.value)


def test_el_secreto_si_es_legible_por_quien_lo_necesita() -> None:
    """Guarda anti-tautologia: ocultarlo en `repr` no puede significar perderlo."""
    configuracion = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_MINIO)

    assert configuracion.storage_secret_key is not None
    assert configuracion.storage_secret_key.get_secret_value() == SECRETO


# --- C-06 ------------------------------------------------------------------
def test_produccion_no_puede_usar_el_almacenamiento_local() -> None:
    """MinIO es local (ADR-003 y software-architecture 3.7). Arrancar produccion
    contra el significaria que el blog publicado sirve imagenes de un contenedor
    de desarrollo."""
    with pytest.raises(ConfigurationError) as fallo:
        build_settings(**{**CONFIGURACION_MINIMA, "app_env": "production"}, **ALMACENAMIENTO_MINIO)

    assert "STORAGE_PROVIDER" in str(fallo.value).upper()


# --- C-07 ------------------------------------------------------------------
def test_el_almacenamiento_no_se_reconstruye_en_cada_peticion() -> None:
    """Construir un cliente del SDK por peticion cargaria el modelo del servicio
    cada vez, lo que penaliza especialmente un arranque en frio (requisito
    P-07)."""
    configuracion = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_MINIO)

    assert obtener_almacenamiento(configuracion) is obtener_almacenamiento(configuracion)


def test_dos_configuraciones_distintas_no_comparten_almacenamiento() -> None:
    """Guarda anti-tautologia de la cache: memorizar no puede significar ignorar
    la configuracion."""
    local = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_MINIO)
    produccion = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_S3)

    assert obtener_almacenamiento(local) is not obtener_almacenamiento(produccion)


# --- C-08: separacion de endpoints, desde la configuracion -----------------
def test_la_fabrica_propaga_los_dos_endpoints() -> None:
    """La configuracion del Compose tiene que llegar entera al adaptador."""
    configuracion = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_EN_DOCKER)

    almacenamiento = crear_almacenamiento(configuracion)

    assert isinstance(almacenamiento, MinIOStorage)
    assert almacenamiento.endpoint_url == "http://minio:9000"
    assert almacenamiento.access_endpoint_url == "http://localhost:9000"


def test_el_enlace_emitido_con_la_configuracion_del_compose_apunta_al_host() -> None:
    """La comprobacion que de verdad importa, extremo a extremo de configuracion.

    Es el defecto que `Task/010` tuvo que corregir: con un unico endpoint, el
    enlace salia hacia `minio:9000` y el navegador del host no lo resolvia.
    """
    configuracion = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_EN_DOCKER)

    acceso = crear_almacenamiento(configuracion).acceso_temporal(
        "medios/x/original.png", duracion=timedelta(minutes=5)
    )

    assert acceso.url.startswith("http://localhost:9000/")
    assert "minio:9000" not in acceso.url


def test_el_endpoint_de_acceso_es_opcional() -> None:
    """Sin el, se firma contra el operativo. Es el comportamiento de siempre."""
    configuracion = build_settings(**CONFIGURACION_MINIMA, **ALMACENAMIENTO_MINIO)

    assert configuracion.storage_access_endpoint_url is None
    acceso = crear_almacenamiento(configuracion).acceso_temporal(
        "medios/x/original.png", duracion=timedelta(minutes=5)
    )
    assert acceso.url.startswith("http://127.0.0.1:9000/")


def test_un_endpoint_de_acceso_malformado_impide_arrancar() -> None:
    """Fail-fast (requisito T-01): el proceso no arranca con un valor invalido."""
    with pytest.raises(ConfigurationError) as fallo:
        build_settings(
            **CONFIGURACION_MINIMA,
            **{**ALMACENAMIENTO_MINIO, "storage_access_endpoint_url": "no-es-una-url"},
        )

    assert "STORAGE_ACCESS_ENDPOINT_URL" in str(fallo.value).upper()


def test_produccion_no_necesita_declarar_un_endpoint_de_acceso() -> None:
    """`Task/030` no queda obligada a configurar nada nuevo.

    Sin endpoint de acceso, `S3Storage` firma contra el endpoint de AWS que el
    SDK resuelve. Si el mecanismo obligara a declararlo, esta tarea estaria
    imponiendo configuracion productiva, que no le corresponde.
    """
    # `storage_endpoint_url=None` explicito: el harness deja uno ficticio en el
    # entorno para que la configuracion de MinIO sea construible, y produccion
    # es justamente el caso en el que **no** hay endpoint declarado.
    configuracion = build_settings(
        **CONFIGURACION_MINIMA, **ALMACENAMIENTO_S3, storage_endpoint_url=None
    )

    assert configuracion.storage_access_endpoint_url is None
    acceso = crear_almacenamiento(configuracion).acceso_temporal(
        "medios/x/original.png", duracion=timedelta(minutes=5)
    )
    assert "amazonaws.com" in acceso.url
