"""Contrato de `ObjectStorage`, ejecutado contra **las dos** implementaciones.

Es la prueba que da sentido a la interfaz. `software-architecture.md` seccion
3.7 exige que cambiar de MinIO a S3 sea un cambio de **configuracion**, no de
codigo de dominio; eso solo es cierto si las dos implementaciones se comportan
igual, y "se comportan igual" es una afirmacion que hay que demostrar, no
declarar.

Cada caso de este modulo se ejecuta dos veces —`[minio]` y `[s3]`— gracias a la
fixture `almacenamiento`. Una divergencia entre proveedores pone rojo el caso
del proveedor que se desvia, y dice cual.

Por que vive en `tests/contract/`
---------------------------------

`BACKEND_TESTING_STRATEGY.md` seccion 14.1 reserva ese directorio para los
"contratos HTTP y de `ObjectStorage`", y la seccion 8.5 fija el orden: primero
el contrato de la interfaz, despues la integracion. Aqui se cumplen los dos a la
vez, porque la semantica que se contrata **es** la del protocolo S3: afirmarla
contra un doble seria afirmar lo que el doble hace, no lo que MinIO hace.

De ahi la marca `integration`: estas pruebas necesitan el MinIO del entorno
local y se omiten, con motivo, cuando no hay entorno declarado.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.shared.storage import ObjectStorage, ObjetoNoEncontradoError
from tests.almacenamiento_de_pruebas import DestinoDeAlmacenamiento

pytestmark = pytest.mark.integration

#: Contenido binario que no sobrevive a una conversion accidental a texto.
BINARIO_HOSTIL = bytes(range(256))


def _descargar(url: str) -> tuple[int, bytes]:
    """Descarga una URL sin credenciales de ningun tipo.

    `urllib` y no el cliente del SDK a proposito: la URL prefirmada tiene que
    funcionar para **cualquiera** que la reciba, que es justo lo que un
    navegador hara con ella. Firmar bien y que solo funcione desde el SDK no
    seria el comportamiento contratado.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=10) as respuesta:  # noqa: S310 - URL propia
            return respuesta.status, respuesta.read()
    except urllib.error.HTTPError as error:  # pragma: no cover - solo si el contrato falla
        return error.code, error.read()


# --- OS-01 -----------------------------------------------------------------
def test_guardar_y_obtener_devuelve_los_mismos_bytes(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    clave = f"{prefijo_de_la_prueba}/original.png"

    almacenamiento.guardar(clave=clave, contenido=BINARIO_HOSTIL, tipo_de_contenido="image/png")

    assert almacenamiento.obtener(clave).contenido == BINARIO_HOSTIL


# --- OS-02 -----------------------------------------------------------------
def test_existe_es_verdadero_para_un_objeto_guardado(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    clave = f"{prefijo_de_la_prueba}/existe.bin"
    almacenamiento.guardar(clave=clave, contenido=b"x", tipo_de_contenido="image/png")

    assert almacenamiento.existe(clave) is True


# --- OS-03 -----------------------------------------------------------------
def test_existe_es_falso_para_una_clave_inexistente(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    assert almacenamiento.existe(f"{prefijo_de_la_prueba}/no-existe.bin") is False


# --- OS-04 -----------------------------------------------------------------
def test_eliminar_deja_de_existir_el_objeto(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    clave = f"{prefijo_de_la_prueba}/efimero.bin"
    almacenamiento.guardar(clave=clave, contenido=b"x", tipo_de_contenido="image/png")

    almacenamiento.eliminar(clave)

    assert almacenamiento.existe(clave) is False


# --- OS-05 -----------------------------------------------------------------
def test_obtener_una_clave_inexistente_lanza_el_error_del_contrato(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    """El error es **del proyecto**, no del SDK: el dominio no conoce botocore."""
    with pytest.raises(ObjetoNoEncontradoError):
        almacenamiento.obtener(f"{prefijo_de_la_prueba}/fantasma.bin")


# --- OS-06 -----------------------------------------------------------------
def test_eliminar_una_clave_inexistente_no_lanza(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    """Decision D-010-C: `eliminar` es idempotente.

    La compensacion de una subida fallida no sabe con certeza que llego a
    escribirse; un borrado que lanzara convertiria la limpieza en un segundo
    error encima del primero.
    """
    almacenamiento.eliminar(f"{prefijo_de_la_prueba}/nunca-existio.bin")


# --- OS-07 -----------------------------------------------------------------
def test_el_tipo_de_contenido_y_el_tamano_se_preservan(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    clave = f"{prefijo_de_la_prueba}/tipada.png"
    contenido = b"a" * 321

    guardado = almacenamiento.guardar(
        clave=clave, contenido=contenido, tipo_de_contenido="image/png"
    )
    recuperado = almacenamiento.obtener(clave)

    assert guardado.clave == clave
    assert guardado.tamano_bytes == 321
    assert recuperado.tipo_de_contenido == "image/png"
    assert recuperado.tamano_bytes == 321


# --- OS-08 -----------------------------------------------------------------
def test_una_clave_con_varios_prefijos_funciona_y_se_devuelve_tal_cual(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    clave = f"{prefijo_de_la_prueba}/a/b/c/profunda.png"

    guardado = almacenamiento.guardar(clave=clave, contenido=b"z", tipo_de_contenido="image/png")

    assert guardado.clave == clave
    assert almacenamiento.obtener(clave).clave == clave


# --- OS-09 -----------------------------------------------------------------
def test_guardar_dos_veces_la_misma_clave_sobrescribe(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    """Decision D-010-D: la semantica es la de `PutObject`, y se declara."""
    clave = f"{prefijo_de_la_prueba}/sobrescrita.png"
    almacenamiento.guardar(clave=clave, contenido=b"antes", tipo_de_contenido="image/png")

    almacenamiento.guardar(clave=clave, contenido=b"despues", tipo_de_contenido="image/png")

    assert almacenamiento.obtener(clave).contenido == b"despues"


# --- OS-10 -----------------------------------------------------------------
def test_el_acceso_temporal_descarga_los_mismos_bytes_sin_credenciales(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    clave = f"{prefijo_de_la_prueba}/accesible.png"
    almacenamiento.guardar(clave=clave, contenido=BINARIO_HOSTIL, tipo_de_contenido="image/png")

    acceso = almacenamiento.acceso_temporal(clave, duracion=timedelta(minutes=5))

    assert acceso.url.startswith("http")
    estado, cuerpo = _descargar(acceso.url)
    assert estado == 200
    assert cuerpo == BINARIO_HOSTIL


# --- OS-14: el enlace se firma contra el endpoint de ACCESO ---------------
def test_el_enlace_se_firma_contra_el_endpoint_de_acceso_y_funciona(
    almacenamiento: ObjectStorage,
    prefijo_de_la_prueba: str,
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> None:
    """La prueba que cierra el defecto de alcanzabilidad de `Task/010`.

    El objeto se **guarda** por el endpoint operativo y el enlace se **firma**
    contra el de acceso, que es otro anfitrion. Despues se descarga la URL
    **exactamente como se emitio**, sin tocar ni el anfitrion, ni la ruta, ni
    la cadena de consulta.

    Que devuelva `200` con los bytes correctos demuestra las dos mitades a la
    vez: que la separacion de endpoints funciona y que la firma es valida para
    el anfitrion por el que de verdad se pide. Comprobar solo
    `url.startswith(...)` no demostraria lo segundo, que es justo lo que falla
    cuando se reescribe una URL ya firmada.
    """
    operativo = destino_de_almacenamiento_verificado.endpoint_url
    acceso_esperado = destino_de_almacenamiento_verificado.access_endpoint_url
    assert operativo != acceso_esperado, (
        "el harness debe dar dos endpoints distintos; si fueran el mismo, esta "
        "prueba no demostraria nada"
    )
    clave = f"{prefijo_de_la_prueba}/enlace-real.png"
    almacenamiento.guardar(clave=clave, contenido=BINARIO_HOSTIL, tipo_de_contenido="image/png")

    acceso = almacenamiento.acceso_temporal(clave, duracion=timedelta(minutes=5))

    assert acceso.url.startswith(f"{acceso_esperado}/")
    assert not acceso.url.startswith(f"{operativo}/")
    # Sin ninguna modificacion posterior: la URL viaja tal cual se firmo.
    estado, cuerpo = _descargar(acceso.url)
    assert estado == 200, f"el enlace firmado no es utilizable: HTTP {estado}"
    assert cuerpo == BINARIO_HOSTIL


def test_reescribir_el_anfitrion_de_una_url_firmada_la_invalida(
    almacenamiento: ObjectStorage,
    prefijo_de_la_prueba: str,
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> None:
    """Guarda que fija **por que** los endpoints se separan antes de firmar.

    El `Host` forma parte de la peticion canonica de AWS Signature Version 4,
    asi que cambiarlo despues rompe la firma. Sin esta prueba, alguien podria
    "simplificar" el diseno reescribiendo la URL emitida y el resultado
    parecería correcto en una aserción de cadena, pero devolvería `403` al
    primer visitante.
    """
    operativo = destino_de_almacenamiento_verificado.endpoint_url
    acceso_esperado = destino_de_almacenamiento_verificado.access_endpoint_url
    clave = f"{prefijo_de_la_prueba}/no-reescribir.png"
    almacenamiento.guardar(clave=clave, contenido=b"contenido", tipo_de_contenido="image/png")
    acceso = almacenamiento.acceso_temporal(clave, duracion=timedelta(minutes=5))

    reescrita = acceso.url.replace(acceso_esperado, operativo, 1)

    estado, _ = _descargar(reescrita)
    assert estado == 403


# --- OS-11 -----------------------------------------------------------------
def test_el_acceso_temporal_no_revela_la_clave_secreta(
    almacenamiento: ObjectStorage,
    prefijo_de_la_prueba: str,
    destino_de_almacenamiento_verificado: object,
) -> None:
    """Requisito S-08: una credencial no puede acabar en una URL que se publica."""
    secreto = destino_de_almacenamiento_verificado.secret_key  # type: ignore[attr-defined]
    clave = f"{prefijo_de_la_prueba}/sin-secretos.png"
    almacenamiento.guardar(clave=clave, contenido=b"x", tipo_de_contenido="image/png")

    acceso = almacenamiento.acceso_temporal(clave, duracion=timedelta(minutes=5))

    assert secreto not in acceso.url


# --- OS-12 -----------------------------------------------------------------
def test_el_acceso_temporal_declara_cuando_expira(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    clave = f"{prefijo_de_la_prueba}/con-expiracion.png"
    almacenamiento.guardar(clave=clave, contenido=b"x", tipo_de_contenido="image/png")
    antes = datetime.now(UTC)

    acceso = almacenamiento.acceso_temporal(clave, duracion=timedelta(minutes=5))

    assert antes + timedelta(minutes=4) <= acceso.expira_en <= antes + timedelta(minutes=6)


# --- OS-13 -----------------------------------------------------------------
def test_ningun_byte_se_corrompe_en_un_payload_binario_completo(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    """Guarda contra una implementacion que decodifique el cuerpo como texto."""
    clave = f"{prefijo_de_la_prueba}/todos-los-bytes.bin"
    contenido = bytes(range(256)) * 64

    almacenamiento.guardar(clave=clave, contenido=contenido, tipo_de_contenido="image/png")

    recuperado = almacenamiento.obtener(clave)
    assert recuperado.contenido == contenido
    assert recuperado.tamano_bytes == len(contenido)


# --- Sonda de disponibilidad (`Task/017`, requisito O-04) -----------------


def test_comprobar_disponibilidad_no_lanza_con_el_bucket_accesible(
    almacenamiento: ObjectStorage,
) -> None:
    """Ambas implementaciones deben coincidir tambien en el camino correcto."""
    almacenamiento.comprobar_disponibilidad()


def test_comprobar_disponibilidad_no_lanza_con_el_bucket_vacio(
    almacenamiento: ObjectStorage,
) -> None:
    """Un bucket sin objetos **esta** disponible: vacio no es ausente."""
    almacenamiento.comprobar_disponibilidad()


def test_comprobar_disponibilidad_no_crea_ni_borra_nada(
    almacenamiento: ObjectStorage, prefijo_de_la_prueba: str
) -> None:
    """La sonda es de solo lectura, y eso es parte del contrato, no del adaptador."""
    clave = f"{prefijo_de_la_prueba}/testigo-de-la-sonda.txt"
    almacenamiento.guardar(clave=clave, contenido=b"testigo", tipo_de_contenido="text/plain")

    almacenamiento.comprobar_disponibilidad()

    assert almacenamiento.existe(clave), "la sonda borro un objeto ajeno"
    assert not almacenamiento.existe("_readiness/"), "la sonda creo un centinela"
