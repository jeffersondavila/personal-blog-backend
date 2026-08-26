"""Comprobacion estructural del grafo de fixtures de integracion (`CERT-AUD-002`).

Las pruebas de `tests/integration/test_guarda_del_destino.py` demuestran el
comportamiento —un destino inseguro se rechaza antes de tocar nada—, pero solo
para los caminos que ellas mismas recorren. Esta prueba cubre el hueco que queda:
que **no exista** ninguna otra fixture del harness de integracion capaz de
entregar el destino saltandose la guarda.

Es una comprobacion de forma, no de comportamiento, y por eso vive fuera de
`tests/integration/`: no necesita PostgreSQL y debe ejecutarse **siempre**,
tambien cuando la integracion se omite. Una regresion introducida al anadir una
fixture nueva se detecta sin depender de que alguien tenga la base levantada.

La garantia expresada como invariante comprobable: toda fixture definida en el
harness de integracion, o **es** el resolutor verificado, o depende de el de
forma transitiva.

Por que los modulos se descubren, no se enumeran
------------------------------------------------

Una lista de modulos escrita a mano falla **abierta**: el dia que alguien crea
`tests/integration/test_articles.py` con una fixture insegura y no se acuerda de
anadir el modulo a la lista, la comprobacion sigue en verde y la proteccion
desaparece en silencio. Eso es exactamente la convencion humana que
`CERT-AUD-002` existe para eliminar, reintroducida en la prueba que deberia
impedirla.

Aqui el conjunto se **descubre del directorio del harness**, asi que un modulo
nuevo entra en la comprobacion por el hecho de existir. Anadir un archivo de
prueba no obliga a recordar nada.

El descubrimiento tiene sus propias guardas anti-tautologia
(`test_el_descubrimiento_encuentra_los_modulos_conocidos` y
`test_la_inspeccion_encuentra_las_fixtures_del_harness`): esta prueba **no puede
ponerse verde porque el descubrimiento haya dejado de encontrar archivos**.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

#: Unica fixture que resuelve el destino de integracion. Verifica el destino
#: antes de entregar nada, asi que alcanzarla es condicion suficiente.
RESOLUTOR_VERIFICADO = "destino_de_integracion_verificado"

#: Paquete y directorio del harness oficial de integracion. Todo modulo Python
#: que viva aqui forma parte del harness y entra en la comprobacion.
PAQUETE_DEL_HARNESS = "tests.integration"
DIRECTORIO_DEL_HARNESS = Path(__file__).resolve().parent / "integration"


def _modulos_del_harness() -> list[str]:
    """Descubre los modulos del harness de integracion.

    Recorre el directorio en lugar de leer una lista escrita a mano. `rglob`
    incluye subdirectorios, que hoy no existen pero podrian aparecer; el orden es
    alfabetico para que la parametrizacion sea determinista.

    Se excluyen `__init__.py` —marca el paquete, no define fixtures— y
    `__pycache__`, que no contiene fuentes. Todo lo demas se inspecciona:
    `conftest.py` y cualquier modulo de prueba, tenga o no fixtures hoy.
    """
    modulos: list[str] = []
    for ruta in sorted(DIRECTORIO_DEL_HARNESS.rglob("*.py")):
        if ruta.stem == "__init__" or "__pycache__" in ruta.parts:
            continue
        relativa = ruta.relative_to(DIRECTORIO_DEL_HARNESS).with_suffix("")
        modulos.append(".".join((PAQUETE_DEL_HARNESS, *relativa.parts)))
    return modulos


#: Modulos que el harness tiene hoy. No son la fuente del descubrimiento: son su
#: **guarda**. Si `_modulos_del_harness` deja de encontrarlos —directorio movido,
#: `rglob` roto, paquete renombrado— la comprobacion debe ponerse roja en lugar
#: de quedarse en verde inspeccionando un conjunto vacio.
MODULOS_CONOCIDOS = {
    f"{PAQUETE_DEL_HARNESS}.conftest",
    f"{PAQUETE_DEL_HARNESS}.test_auditoria",
    f"{PAQUETE_DEL_HARNESS}.test_esquema_de_contenido",
    f"{PAQUETE_DEL_HARNESS}.test_esquema_fisico",
    f"{PAQUETE_DEL_HARNESS}.test_politica_de_medios",
    f"{PAQUETE_DEL_HARNESS}.test_relaciones_de_etiquetas",
    f"{PAQUETE_DEL_HARNESS}.test_singletons",
    f"{PAQUETE_DEL_HARNESS}.test_database_connection",
    f"{PAQUETE_DEL_HARNESS}.test_guarda_del_destino",
    f"{PAQUETE_DEL_HARNESS}.test_hermeticidad_de_la_integracion",
    f"{PAQUETE_DEL_HARNESS}.test_migrations",
}

#: Fixtures propias de pytest: no forman parte del harness y no pueden alcanzar
#: la base de datos del proyecto.
FIXTURES_DE_PYTEST = {
    "request",
    "monkeypatch",
    "tmp_path",
    "tmp_path_factory",
    "capsys",
    "caplog",
    "recwarn",
}


#: Marcas que pytest deja en un objeto decorado con `@pytest.fixture`.
#: `_fixture_function_marker` es la de pytest >= 8.4, donde el decorador devuelve
#: un `FixtureFunctionDefinition`; `_pytestfixturefunction` es la anterior, en la
#: que devolvia la propia funcion. Se aceptan las dos para que la comprobacion no
#: se vuelva silenciosamente vacia —y por tanto inutil— al cambiar de version.
_MARCAS_DE_FIXTURE = ("_fixture_function_marker", "_pytestfixturefunction")


def _es_fixture(objeto: Any) -> bool:
    """Reconoce una fixture de pytest sin dejarse enganar por proxies dinamicos.

    No basta con `hasattr`: hay objetos que responden **a cualquier atributo**.
    `sqlalchemy.func` es uno —`func.lo_que_sea` construye una llamada SQL—, asi
    que importarlo en un modulo del harness lo convertia en una "fixture" llamada
    `func` que, naturalmente, no dependia de la guarda. La comprobacion se ponia
    roja por un import perfectamente correcto (detectado en `Task/008`).

    Se exige ademas que el valor de la marca **venga de pytest**. Sigue siendo
    fail-closed: `test_la_inspeccion_encuentra_las_fixtures_del_harness` se pone
    rojo si esta condicion dejara fuera fixtures de verdad.
    """
    for marca in _MARCAS_DE_FIXTURE:
        valor = getattr(objeto, marca, None)
        if valor is not None and type(valor).__module__.startswith("_pytest"):
            return True
    return False


def _fixtures_de(modulo: ModuleType) -> dict[str, Any]:
    return {nombre: objeto for nombre, objeto in vars(modulo).items() if _es_fixture(objeto)}


def _todas_las_fixtures() -> dict[str, Any]:
    encontradas: dict[str, Any] = {}
    for ruta in _modulos_del_harness():
        encontradas.update(_fixtures_de(importlib.import_module(ruta)))
    return encontradas


def _dependencias(fixture: Any) -> list[str]:
    return [
        nombre
        for nombre in inspect.signature(fixture).parameters
        if nombre not in FIXTURES_DE_PYTEST
    ]


#: Fixtures que el harness de integracion tiene hoy. Se enumeran para que la
#: inspeccion no pueda quedarse vacia sin que nadie se entere: si pytest cambia
#: como marca las fixtures, `_fixtures_de` devolveria `{}`, la parametrizacion se
#: quedaria sin casos y la comprobacion pasaria sin haber mirado nada.
FIXTURES_CONOCIDAS = {
    "alembic_config",
    "configured_process",
    "esquema_migrado",
    "sesion_de_pruebas",
    "database_engine",
    "database_settings",
    "tabla_de_pruebas",
}


def test_el_descubrimiento_encuentra_los_modulos_conocidos() -> None:
    """Guarda anti-tautologia del descubrimiento.

    Sin esta comprobacion, un descubrimiento roto —directorio inexistente,
    paquete renombrado, `rglob` que no encuentra nada— dejaria el conjunto vacio
    y **toda** esta prueba pasaria sin haber inspeccionado un solo modulo. La
    proteccion se perderia exactamente igual que con la lista manual que este
    mecanismo sustituye, pero de forma todavia mas silenciosa.
    """
    assert DIRECTORIO_DEL_HARNESS.is_dir(), (
        f"el directorio del harness de integracion no existe: {DIRECTORIO_DEL_HARNESS}. "
        "El descubrimiento no puede encontrar nada y la comprobacion estructural "
        "no estaria comprobando nada."
    )

    descubiertos = set(_modulos_del_harness())

    ausentes = MODULOS_CONOCIDOS - descubiertos
    assert not ausentes, (
        f"el descubrimiento no encontro {sorted(ausentes)}. Si esos modulos se "
        "renombraron o se movieron, actualizar `MODULOS_CONOCIDOS`; si el "
        "mecanismo de descubrimiento se rompio, el resto de este modulo estaria "
        f"inspeccionando un conjunto incompleto. Descubiertos: {sorted(descubiertos)}"
    )


def test_la_inspeccion_encuentra_las_fixtures_del_harness() -> None:
    """Guarda anti-tautologia: la parametrizacion no puede quedarse vacia."""
    encontradas = set(_todas_las_fixtures())

    ausentes = FIXTURES_CONOCIDAS - encontradas
    assert not ausentes, (
        f"la inspeccion no encontro {sorted(ausentes)}. O el harness cambio, o "
        "`_es_fixture` dejo de reconocer como marca pytest lo que pytest usa hoy. "
        "En el segundo caso el resto de este modulo estaria comprobando el vacio."
    )


def test_el_harness_de_integracion_define_un_unico_resolutor() -> None:
    """El resolutor existe y tiene el nombre que el resto de la prueba asume."""
    fixtures = _todas_las_fixtures()

    assert RESOLUTOR_VERIFICADO in fixtures, (
        f"el harness de integracion ya no define '{RESOLUTOR_VERIFICADO}'. "
        "Si se renombro, actualizar tambien esta comprobacion; si desaparecio, "
        "la garantia de CERT-AUD-002 ya no esta implementada."
    )


@pytest.mark.parametrize("nombre", sorted(_todas_las_fixtures()))
def test_toda_fixture_de_integracion_pasa_por_la_guarda(nombre: str) -> None:
    """Ninguna fixture publica entrega el destino sin haberlo verificado antes.

    Los casos salen del descubrimiento, asi que una fixture definida en un modulo
    nuevo de `tests/integration/` entra aqui sin que nadie tenga que registrarla.
    """
    fixtures = _todas_las_fixtures()

    if nombre == RESOLUTOR_VERIFICADO:
        return

    alcanzadas: set[str] = set()
    pendientes = [nombre]
    while pendientes:
        actual = pendientes.pop()
        if actual in alcanzadas or actual not in fixtures:
            continue
        alcanzadas.add(actual)
        pendientes.extend(_dependencias(fixtures[actual]))

    assert RESOLUTOR_VERIFICADO in alcanzadas, (
        f"la fixture '{nombre}' del harness de integracion no depende de "
        f"'{RESOLUTOR_VERIFICADO}': puede entregar configuracion, motor, sesion o "
        "Config de Alembic para el destino de integracion sin que la guarda "
        f"fail-closed haya pasado. Cadena alcanzada: {sorted(alcanzadas)}. "
        "Remedios legitimos: (a) derivarla del resolutor, pidiendo "
        f"'{RESOLUTOR_VERIFICADO}', 'database_settings' o 'database_engine'; o "
        "(b) si de verdad no toca la base de integracion, moverla fuera de "
        "tests/integration/, que es lo que delimita el harness. Bajar esta "
        "comprobacion NO es un remedio."
    )
