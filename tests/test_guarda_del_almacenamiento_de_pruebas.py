"""Guarda del harness de almacenamiento de pruebas (`Task/010`).

Las pruebas de almacenamiento **crean y borran un bucket entero**. Son, por
tanto, tan destructivas como las de PostgreSQL, y merecen la misma clase de
proteccion que `Task/005.6` y `Task/005.7` construyeron para aquellas.

Este modulo comprueba las dos mitades de esa proteccion:

| Mitad | Que demuestra | Necesita MinIO |
| --- | --- | --- |
| **Comportamiento** | Un destino no local se rechaza, y se rechaza **antes** de tocar nada | No |
| **Estructura** | Ninguna fixture del harness entrega el destino saltandose la guarda | No |

Vive fuera de `tests/contract/` a proposito, igual que
`tests/test_grafo_de_fixtures_de_integracion.py` vive fuera de
`tests/integration/`: es una comprobacion de forma que debe ejecutarse
**siempre**, tambien cuando el almacenamiento no esta disponible y las pruebas
que protege se omiten. Una regresion introducida al anadir una fixture nueva se
detecta sin depender de que alguien tenga Docker levantado.

Por que la lista blanca aqui y la lista negra en `MinIOStorage`
--------------------------------------------------------------

No es una incoherencia: son dos riesgos distintos.

- **El harness borra un bucket.** El criterio correcto es exigir demostrar que
  el destino es seguro: solo anfitriones locales, lista blanca. Cualquier otro
  —AWS o no— es un fallo.
- **`MinIOStorage` escribe imagenes.** Ahi el endpoint legitimo puede ser el
  nombre de servicio de Docker Compose, que ninguna lista blanca de "local"
  contendria. El criterio es prohibir AWS, lista negra.

Poner la lista blanca en el adaptador romperia el entorno local; poner la lista
negra en el harness dejaria pasar cualquier proveedor remoto que no fuera AWS.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

import pytest

from tests import almacenamiento_de_pruebas as harness

#: Unica fixture que resuelve el destino de almacenamiento. Verifica antes de
#: entregar nada, asi que alcanzarla es condicion suficiente.
RESOLUTOR_VERIFICADO = "destino_de_almacenamiento_verificado"

#: Fixtures que el harness tiene hoy. No son la fuente de la inspeccion: son su
#: **guarda**. Si el descubrimiento dejara de encontrarlas, la comprobacion debe
#: ponerse roja en lugar de pasar habiendo inspeccionado un conjunto vacio.
FIXTURES_CONOCIDAS = {
    RESOLUTOR_VERIFICADO,
    "almacenamiento",
    "almacenamiento_minio",
    "almacenamiento_s3",
    "prefijo_de_la_prueba",
}

#: Implementaciones sobre las que se parametriza la fixture `almacenamiento`.
#: Se enumeran aqui porque esa fixture las resuelve dinamicamente y la
#: comprobacion estructural necesita saber a que fixtures llega.
IMPLEMENTACIONES_PARAMETRIZADAS = ("minio", "s3")

#: Fixtures propias de pytest: no forman parte del harness.
FIXTURES_DE_PYTEST = {"request", "monkeypatch", "tmp_path", "capsys", "caplog"}

_MARCAS_DE_FIXTURE = ("_fixture_function_marker", "_pytestfixturefunction")


def _es_fixture(objeto: Any) -> bool:
    """Reconoce una fixture de pytest exigiendo que la marca venga de pytest.

    Mismo criterio que `tests/test_grafo_de_fixtures_de_integracion.py`, y por el
    mismo motivo: `hasattr` se deja enganar por objetos que responden a
    cualquier atributo.
    """
    for marca in _MARCAS_DE_FIXTURE:
        valor = getattr(objeto, marca, None)
        if valor is not None and type(valor).__module__.startswith("_pytest"):
            return True
    return False


def _fixtures_del_harness() -> dict[str, Any]:
    modulo = importlib.import_module(harness.__name__)
    return {nombre: objeto for nombre, objeto in vars(modulo).items() if _es_fixture(objeto)}


def _dependencias(fixture: Any) -> list[str]:
    return [
        nombre
        for nombre in inspect.signature(fixture).parameters
        if nombre not in FIXTURES_DE_PYTEST
    ]


# --- Guardas anti-tautologia ----------------------------------------------
def test_la_parametrizacion_declarada_coincide_con_la_del_harness() -> None:
    """Guarda: si el harness anadiera un tercer proveedor y aqui no, la
    comprobacion estructural dejaria de mirarlo."""
    marca = harness.almacenamiento._fixture_function_marker

    assert tuple(marca.params or ()) == IMPLEMENTACIONES_PARAMETRIZADAS


def test_la_inspeccion_encuentra_las_fixtures_del_harness() -> None:
    """Sin esto, un descubrimiento roto dejaria el resto en verde vacio."""
    encontradas = set(_fixtures_del_harness())

    ausentes = FIXTURES_CONOCIDAS - encontradas
    assert not ausentes, (
        f"la inspeccion no encontro {sorted(ausentes)}. O el harness cambio, o "
        "`_es_fixture` dejo de reconocer como marca pytest lo que pytest usa hoy."
    )


# --- Estructura: toda fixture pasa por la guarda ---------------------------
@pytest.mark.parametrize("nombre", sorted(_fixtures_del_harness()))
def test_toda_fixture_de_almacenamiento_pasa_por_la_guarda(nombre: str) -> None:
    """Ninguna fixture entrega un destino sin haberlo verificado antes.

    `prefijo_de_la_prueba` es la unica excepcion legitima y esta declarada: no
    resuelve ningun destino, solo compone una cadena de clave.
    """
    if nombre in {RESOLUTOR_VERIFICADO, "prefijo_de_la_prueba"}:
        return

    fixtures = _fixtures_del_harness()
    # `almacenamiento` no declara sus dependencias en la firma: elige la
    # implementacion con `getfixturevalue` a partir de su parametrizacion. Se
    # sustituyen por las fixtures que esa parametrizacion puede alcanzar, para
    # que la comprobacion siga siendo real y no una excepcion concedida.
    raices = (
        [f"almacenamiento_{parametro}" for parametro in IMPLEMENTACIONES_PARAMETRIZADAS]
        if nombre == "almacenamiento"
        else [nombre]
    )

    alcanzadas: set[str] = set()
    pendientes = list(raices)
    while pendientes:
        actual = pendientes.pop()
        if actual in alcanzadas or actual not in fixtures:
            continue
        alcanzadas.add(actual)
        pendientes.extend(_dependencias(fixtures[actual]))

    assert RESOLUTOR_VERIFICADO in alcanzadas, (
        f"la fixture '{nombre}' del harness de almacenamiento no depende de "
        f"'{RESOLUTOR_VERIFICADO}': puede entregar un cliente o un bucket sin que la "
        f"guarda fail-closed haya pasado. Cadena alcanzada: {sorted(alcanzadas)}. "
        "Bajar esta comprobacion NO es un remedio."
    )


# --- Comportamiento: el destino inseguro se rechaza ------------------------
@pytest.mark.parametrize(
    "endpoint",
    [
        "https://s3.amazonaws.com",
        "https://s3.eu-west-1.amazonaws.com",
        "https://almacenamiento.de-otro-proveedor.com",
        "http://192.168.1.50:9000",
    ],
)
def test_un_endpoint_que_no_es_local_se_rechaza(endpoint: str) -> None:
    """Lista blanca: cualquier anfitrion remoto es un fallo, no solo AWS.

    Comprobar unicamente "que no sea AWS" fallaria **abierta** ante cualquier
    otro proveedor que apareciera manana, y ante un MinIO de un companero en la
    red local. La suite borra un bucket entero: el criterio tiene que ser
    demostrar que el destino es seguro.
    """
    with pytest.raises(pytest.fail.Exception, match="no es local"):
        harness._verificar_que_el_endpoint_es_local(endpoint)


@pytest.mark.parametrize("endpoint", ["", "no-es-una-url", "ftp://127.0.0.1:9000"])
def test_un_endpoint_malformado_se_rechaza(endpoint: str) -> None:
    with pytest.raises(pytest.fail.Exception, match="no es una URL utilizable"):
        harness._verificar_que_el_endpoint_es_local(endpoint)


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:9000", "http://localhost:9000"])
def test_un_endpoint_local_se_acepta(endpoint: str) -> None:
    """Guarda anti-tautologia: la lista blanca no puede rechazarlo todo."""
    harness._verificar_que_el_endpoint_es_local(endpoint)


# --- La limpieza solo borra lo que la suite creo ---------------------------
def test_la_limpieza_se_niega_a_borrar_un_bucket_que_no_creo_la_suite() -> None:
    """Segunda barrera, dentro de la propia limpieza.

    El nombre se comprueba **otra vez** justo antes del `delete_bucket`, no solo
    al crearlo. Es deliberadamente redundante: es la ultima linea antes de una
    operacion irreversible, y una redundancia ahi cuesta tres lineas.
    """

    class _ClienteQueNoDebeUsarse:
        def __getattr__(self, nombre: str) -> Any:  # pragma: no cover - no debe llamarse
            raise AssertionError(f"la limpieza llego a llamar a {nombre!r}")

    with pytest.raises(AssertionError, match="no lleva el prefijo"):
        harness._vaciar_y_borrar_el_bucket(_ClienteQueNoDebeUsarse(), "personal-blog-media")


def test_el_nombre_del_bucket_de_pruebas_es_inequivoco() -> None:
    """El prefijo tiene que decir a las claras que el bucket es descartable."""
    assert harness.PREFIJO_DE_BUCKET_DE_PRUEBAS == "personal-blog-test-"
    assert not harness.PREFIJO_DE_BUCKET_DE_PRUEBAS.startswith("personal-blog-media")
