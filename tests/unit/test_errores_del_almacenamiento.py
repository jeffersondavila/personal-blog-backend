"""Traduccion de los errores del SDK a los errores del proyecto (caso S-03).

El contrato de `tests/contract/` demuestra el camino feliz y la ausencia de un
objeto contra MinIO real. Lo que **no** puede demostrar es el camino de fallo del
proveedor: provocar un `AccessDenied` o un `InternalError` reales exigiria
romper MinIO a proposito.

Aqui se comprueba con un doble de frontera, y lo que se afirma es exactamente lo
que el proyecto necesita garantizar:

- El llamante recibe un error **del proyecto**, nunca uno de `botocore`. El
  dominio no conoce el SDK (ADR-004).
- El mensaje **no filtra credenciales, trazas ni nombres de clase internos**
  (requisitos S-07 y S-08). Un error acaba en un log, y un log acaba en un
  sistema de observabilidad.
- La excepcion original **se conserva** en `__cause__`. No filtrar hacia el
  cliente no puede significar perder el diagnostico.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.shared.storage import (
    FalloDelProveedorDeAlmacenamientoError,
    MinIOStorage,
    ObjetoNoEncontradoError,
)

SECRETO = "secreto-que-no-debe-filtrarse"
CLAVE_DE_ACCESO = "clave-que-no-debe-filtrarse"


class _ErrorDelSdk(Exception):  # noqa: N818 - nombre en espanol, igual que la jerarquia real
    """Imita la forma de `botocore.exceptions.ClientError`.

    Lo que importa de esa clase es el atributo `response`, que es lo unico que
    el adaptador inspecciona: asi la traduccion no depende de importar
    `botocore` en la ruta de error, que es justo lo que se quiere evitar.
    """

    def __init__(self, codigo: str, mensaje: str = "") -> None:
        super().__init__(mensaje or codigo)
        self.response = {"Error": {"Code": codigo, "Message": mensaje}}


class _ClienteQueFalla:
    """Cliente que lanza el error configurado en cualquier operacion."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def __getattr__(self, nombre: str) -> Any:
        def _lanzar(*_: object, **__: object) -> None:
            raise self._error

        return _lanzar


def _almacenamiento_con(error: Exception, monkeypatch: pytest.MonkeyPatch) -> MinIOStorage:
    almacenamiento = MinIOStorage(
        bucket="bucket-de-prueba",
        endpoint_url="http://127.0.0.1:9000",
        access_key=CLAVE_DE_ACCESO,
        secret_key=SECRETO,
        region="us-east-1",
    )
    monkeypatch.setattr(MinIOStorage, "_crear_cliente", lambda _: _ClienteQueFalla(error))
    return almacenamiento


# --- Un fallo del proveedor se envuelve, nunca se propaga ------------------
@pytest.mark.parametrize(
    ("operacion", "argumentos"),
    [
        ("guardar", {"clave": "k", "contenido": b"x", "tipo_de_contenido": "image/png"}),
        ("obtener", {}),
        ("existe", {}),
        ("eliminar", {}),
    ],
)
def test_un_fallo_del_proveedor_llega_como_error_del_proyecto(
    monkeypatch: pytest.MonkeyPatch, operacion: str, argumentos: dict[str, Any]
) -> None:
    almacenamiento = _almacenamiento_con(_ErrorDelSdk("AccessDenied", "Access Denied"), monkeypatch)
    metodo = getattr(almacenamiento, operacion)

    with pytest.raises(FalloDelProveedorDeAlmacenamientoError) as fallo:
        metodo(**argumentos) if argumentos else metodo("k")

    assert isinstance(fallo.value.__cause__, _ErrorDelSdk)


def test_un_fallo_al_firmar_tambien_se_envuelve(monkeypatch: pytest.MonkeyPatch) -> None:
    almacenamiento = _almacenamiento_con(_ErrorDelSdk("InternalError"), monkeypatch)

    with pytest.raises(FalloDelProveedorDeAlmacenamientoError):
        almacenamiento.acceso_temporal("k", duracion=timedelta(minutes=5))


# --- El bucket inexistente es un fallo del proveedor, no una ausencia ------
def test_un_bucket_inexistente_no_se_confunde_con_un_objeto_ausente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`NoSuchBucket` es un problema de configuracion, no una clave que falta.

    Confundirlos haria que apuntar al bucket equivocado se manifestara como
    "esta imagen no existe" en lugar de como el error de despliegue que es.
    """
    almacenamiento = _almacenamiento_con(_ErrorDelSdk("NoSuchBucket"), monkeypatch)

    with pytest.raises(FalloDelProveedorDeAlmacenamientoError):
        almacenamiento.obtener("k")


def test_una_clave_ausente_si_produce_el_error_de_ausencia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guarda anti-tautologia: la distincion anterior no puede colapsar en un
    unico error para todo."""
    almacenamiento = _almacenamiento_con(_ErrorDelSdk("NoSuchKey"), monkeypatch)

    with pytest.raises(ObjetoNoEncontradoError):
        almacenamiento.obtener("k")


def test_eliminar_absorbe_la_ausencia_venga_como_venga(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision D-010-C. S3 no protesta al borrar una clave ausente, pero otro
    servicio compatible podria: la idempotencia se garantiza en el adaptador y
    no se delega en el proveedor."""
    almacenamiento = _almacenamiento_con(_ErrorDelSdk("NoSuchKey"), monkeypatch)

    almacenamiento.eliminar("k")  # no debe lanzar


def test_existe_devuelve_falso_ante_la_ausencia(monkeypatch: pytest.MonkeyPatch) -> None:
    almacenamiento = _almacenamiento_con(_ErrorDelSdk("404"), monkeypatch)

    assert almacenamiento.existe("k") is False


# --- Un error sin forma de `ClientError` tampoco se propaga ----------------
def test_un_error_sin_respuesta_estructurada_tambien_se_envuelve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fallo de red no trae `response`: es una `ConnectionError` pelada.

    Si el adaptador diera por hecho que todo error del SDK tiene esa forma, un
    problema de conectividad escaparia sin traducir y llegaria al manejador
    generico como un `500` sin contexto.
    """
    almacenamiento = _almacenamiento_con(ConnectionError("no hay ruta al host"), monkeypatch)

    with pytest.raises(FalloDelProveedorDeAlmacenamientoError):
        almacenamiento.existe("k")


# --- S-07 y S-08: el mensaje no filtra nada -------------------------------
@pytest.mark.parametrize(
    "error",
    [
        _ErrorDelSdk("AccessDenied", f"credential {CLAVE_DE_ACCESO}/20260101/us-east-1"),
        ConnectionError(f"fallo con la clave {SECRETO}"),
    ],
)
def test_el_error_no_filtra_credenciales_ni_el_texto_del_sdk(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    almacenamiento = _almacenamiento_con(error, monkeypatch)

    with pytest.raises(FalloDelProveedorDeAlmacenamientoError) as fallo:
        almacenamiento.obtener("k")

    mensaje = str(fallo.value)
    assert SECRETO not in mensaje
    assert CLAVE_DE_ACCESO not in mensaje
    assert str(error) not in mensaje


def test_el_error_conserva_el_codigo_del_proveedor_para_diagnosticar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No filtrar no puede significar no decir nada.

    El codigo del proveedor no es sensible y es lo primero que hace falta para
    entender que paso; el texto libre del SDK, que si puede llevar cabeceras y
    URL firmadas, se descarta.
    """
    almacenamiento = _almacenamiento_con(_ErrorDelSdk("AccessDenied"), monkeypatch)

    with pytest.raises(FalloDelProveedorDeAlmacenamientoError) as fallo:
        almacenamiento.obtener("k")

    assert "AccessDenied" in str(fallo.value)
    assert "obtener" in str(fallo.value)


def test_un_error_sin_codigo_produce_un_mensaje_igualmente_utilizable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    almacenamiento = _almacenamiento_con(ConnectionError("sin codigo"), monkeypatch)

    with pytest.raises(FalloDelProveedorDeAlmacenamientoError) as fallo:
        almacenamiento.guardar(clave="k", contenido=b"x", tipo_de_contenido="image/png")

    assert "guardar" in str(fallo.value)
    assert "codigo del proveedor" not in str(fallo.value)
