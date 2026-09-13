"""Guardas del adaptador Lambda (`Task/023`).

Estas pruebas no comprueban comportamiento nuevo: protegen dos **decisiones**
cuya validez depende de premisas que hoy son ciertas y podrian dejar de serlo.
Nacen en verde a proposito. Su valor es ponerse rojas el dia que la premisa
caiga, obligando a revisar la decision en lugar de heredarla a ciegas.

Guarda 1 — la premisa de `lifespan="off"`
-----------------------------------------

Verificado sobre la rueda fijada de `mangum==0.22.0`, con su `sha256`
comprobado contra PyPI:

- `LifespanCycle` se instancia **dentro** de `Mangum.__call__`, es decir **una
  vez por invocacion**, no una vez por contenedor.
- El modo `"auto"` solo degrada a "no soportado" si la aplicacion envia un
  mensaje **antes** de recibir el evento de arranque. Starlette **si** implementa
  el protocolo, asi que `"auto"` ejecutaria un ciclo completo de arranque y
  apagado en **cada** peticion.

Como `create_app()` no declara ningun manejador de ciclo de vida, ese ciclo no
haria ningun trabajo util. De ahi `"off"`.

`"auto"` tampoco seria el modo prudente de cara al futuro: un arranque que
calentara un *pool* de conexiones se ejecutaria —y se destruiria— en cada
peticion, que es peor que no ejecutarlo. Por eso la premisa se protege en lugar
de elegir el modo por el que "parece" mas tolerante.

Por que la comprobacion no es un `grep` ni depende de nombres privados
----------------------------------------------------------------------

La premisa se protege en **tres capas independientes**: se interroga la
superficie publica por la que Starlette y FastAPI registran manejadores de
ciclo de vida —`router.on_startup` y `router.on_shutdown`—, se **ejecuta** el
protocolo ASGI de `lifespan` tal como lo define la especificacion, y se recorre
el arbol sintactico de nuestro propio codigo. Ninguna de las tres depende de un
nombre privado de Starlette o de FastAPI.

Que se aprendio escribiendo esta guarda
---------------------------------------

El primer intento comparaba `router.lifespan_context` con el de una `FastAPI()`
recien construida. **Fallo, y el fallo fue util:** `include_router()` envuelve
el contexto con `_merge_lifespan_context`, asi que una aplicacion que monta
routers **nunca** conserva el contexto por omision, aunque ninguno de ellos
haga nada. Esa comprobacion media un detalle interno de FastAPI, no la premisa
de la decision. Se sustituyo por las tres capas de arriba.

Guarda 2 — la capa sigue siendo removible (**T-04**)
----------------------------------------------------

El requisito T-04 exige que el adaptador sea una capa fina y **removible**. Eso
solo es cierto mientras `mangum` no se filtre al resto del backend: en cuanto un
modulo de dominio, de aplicacion o de infraestructura lo importara, quitarlo
dejaria de ser borrar un archivo. El arbol se recorre con `ast`, no con texto,
para no depender de como este escrito el import.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi import FastAPI

PAQUETE_DE_LA_APLICACION: Final[Path] = Path(__file__).resolve().parents[2] / "app"

#: Unico modulo autorizado a importar el adaptador de terceros.
MODULO_DEL_ADAPTADOR: Final[str] = "lambda_handler.py"

#: Distribucion de terceros que materializa el adaptador.
PAQUETE_DEL_ADAPTADOR: Final[str] = "mangum"


def _modulos_de_la_aplicacion() -> list[Path]:
    """Descubre los modulos de `app/` recorriendo el directorio.

    Se descubren, no se enumeran: una lista escrita a mano fallaria **abierta**
    el dia que alguien crease un modulo nuevo y no se acordara de anadirlo.
    """
    return sorted(
        ruta for ruta in PAQUETE_DE_LA_APLICACION.rglob("*.py") if "__pycache__" not in ruta.parts
    )


def _paquetes_importados(ruta: Path) -> set[str]:
    """Paquetes de primer nivel que importa un modulo, segun su arbol sintactico."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    importados: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            importados.add(nodo.module.split(".")[0])
    return importados


#: Formas con las que FastAPI y Starlette permiten declarar ciclo de vida.
DECLARACIONES_DE_CICLO_DE_VIDA: Final[frozenset[str]] = frozenset(
    {"lifespan", "on_startup", "on_shutdown"}
)


def _declaraciones_de_ciclo_de_vida(ruta: Path) -> list[str]:
    """Formas de declarar ciclo de vida presentes en un modulo."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    hallazgos: list[str] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        hallazgos.extend(
            palabra.arg
            for palabra in nodo.keywords
            if palabra.arg in DECLARACIONES_DE_CICLO_DE_VIDA
        )
        if isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "on_event":
            hallazgos.append("on_event")
    return hallazgos


def _ejecutar_el_ciclo_de_vida(aplicacion: FastAPI) -> tuple[dict[str, Any], list[str]]:
    """Recorre el protocolo ASGI de `lifespan` y devuelve el estado y los mensajes.

    Se habla el protocolo tal como lo define la especificacion ASGI —arranque,
    apagado y los mensajes de confirmacion—, no una API interna del framework.
    """
    estado: dict[str, Any] = {}
    mensajes: list[str] = []
    pendientes: list[dict[str, str]] = [
        {"type": "lifespan.startup"},
        {"type": "lifespan.shutdown"},
    ]

    async def recibir() -> dict[str, str]:
        return pendientes.pop(0)

    async def enviar(mensaje: Any) -> None:
        mensajes.append(mensaje["type"])

    async def ciclo() -> None:
        await aplicacion(
            {
                "type": "lifespan",
                "asgi": {"version": "3.0", "spec_version": "2.0"},
                "state": estado,
            },
            recibir,
            enviar,
        )

    asyncio.run(ciclo())
    return estado, mensajes


# --- L-15 -------------------------------------------------------------------
def test_la_aplicacion_no_declara_manejadores_de_arranque_ni_apagado(
    settings_factory: Any,
) -> None:
    """Si esto se pone rojo, `lifespan="off"` deja de ser la eleccion correcta."""
    from app.main import create_app

    configuracion = settings_factory()
    aplicacion = create_app(settings=configuracion)

    assert aplicacion.router.on_startup == []
    assert aplicacion.router.on_shutdown == []


def test_ejecutar_el_ciclo_de_vida_no_produce_ningun_estado(settings_factory: Any) -> None:
    """Segunda capa: se **ejecuta** el protocolo ASGI y se mira que deja.

    Un ciclo de vida que preparase recursos para las peticiones los publicaria
    en el `state` del *scope*, que es el canal que la especificacion ASGI define
    para eso. Mientras siga vacio, `lifespan="off"` no esta privando a la
    aplicacion de nada.
    """
    from app.main import create_app

    aplicacion = create_app(settings=settings_factory())
    estado, mensajes = _ejecutar_el_ciclo_de_vida(aplicacion)

    assert mensajes == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    assert estado == {}


def test_ningun_modulo_de_la_aplicacion_declara_ciclo_de_vida() -> None:
    """Tercera capa: la unica que ve un ciclo de vida con efectos laterales.

    Las dos anteriores observan el resultado; esta observa la **declaracion**.
    Hace falta porque un arranque que guardase su recurso en una variable de
    modulo —en vez de en el `state`— no dejaria rastro en las otras dos.

    Se recorre el arbol sintactico de nuestro propio codigo, no el de Starlette:
    la comprobacion no depende de ningun detalle privado del framework.
    """
    infractores = {
        ruta.relative_to(PAQUETE_DE_LA_APLICACION).as_posix(): declaraciones
        for ruta in _modulos_de_la_aplicacion()
        # El adaptador SI escribe `lifespan=`: es su propia configuracion
        # —`"off"`—, no una declaracion de ciclo de vida de la aplicacion.
        if ruta.name != MODULO_DEL_ADAPTADOR
        and (declaraciones := _declaraciones_de_ciclo_de_vida(ruta))
    }

    assert infractores == {}, (
        f"la aplicacion declara ciclo de vida en {infractores}. La premisa de "
        'lifespan="off" ha dejado de ser cierta: revisa la decision en la ficha de '
        "Task/023 antes de tocar esta prueba."
    )


def test_el_handler_se_configura_sin_ciclo_de_vida(settings_factory: Any) -> None:
    """La decision, en forma ejecutable: el adaptador no corre lifespan."""
    from app.lambda_handler import crear_handler
    from app.main import create_app

    configuracion = settings_factory()
    handler = crear_handler(create_app(settings=configuracion))

    assert handler.lifespan == "off"


# --- T-04: la capa sigue siendo removible -----------------------------------
def test_solo_el_adaptador_importa_el_paquete_de_terceros() -> None:
    """Quitar Lambda debe seguir siendo borrar un archivo y una dependencia."""
    infractores = [
        ruta.relative_to(PAQUETE_DE_LA_APLICACION).as_posix()
        for ruta in _modulos_de_la_aplicacion()
        if ruta.name != MODULO_DEL_ADAPTADOR and PAQUETE_DEL_ADAPTADOR in _paquetes_importados(ruta)
    ]

    assert infractores == [], (
        f"{PAQUETE_DEL_ADAPTADOR!r} se importa fuera de app/{MODULO_DEL_ADAPTADOR}: "
        f"{infractores}. El adaptador dejaria de ser una capa removible (requisito T-04)."
    )


def test_el_adaptador_vive_en_un_solo_modulo() -> None:
    """La capa fina es, literalmente, un archivo."""
    modulos = [
        ruta.relative_to(PAQUETE_DE_LA_APLICACION).as_posix()
        for ruta in _modulos_de_la_aplicacion()
        if PAQUETE_DEL_ADAPTADOR in _paquetes_importados(ruta)
    ]

    assert modulos == [MODULO_DEL_ADAPTADOR]


def test_el_descubrimiento_encuentra_los_modulos_conocidos() -> None:
    """Guarda anti-tautologia: las dos pruebas de arriba no pasan por vacio."""
    descubiertos = {
        ruta.relative_to(PAQUETE_DE_LA_APLICACION).as_posix()
        for ruta in _modulos_de_la_aplicacion()
    }

    assert {"main.py", "lambda_handler.py", "shared/configuration/settings.py"} <= descubiertos


@pytest.mark.parametrize("modulo", ["main.py", "lambda_handler.py"])
def test_la_inspeccion_de_imports_encuentra_algo_en_los_modulos_clave(modulo: str) -> None:
    """Guarda anti-tautologia del analizador: si devolviera conjuntos vacios,
    `test_solo_el_adaptador_importa_el_paquete_de_terceros` pasaria sin probar nada.
    """
    assert _paquetes_importados(PAQUETE_DE_LA_APLICACION / modulo)
