"""El dominio es Python plano: no arrastra framework ni ORM.

ADR-004 seccion 4 y software-architecture.md seccion 3.2 exigen que
`presentation -> application -> domain <- infrastructure`, y que `domain` no
importe nada de las otras capas. La consecuencia comprobable es esta: importar
cualquier modulo de dominio **no** debe cargar FastAPI, Starlette, SQLAlchemy,
Alembic ni el driver de PostgreSQL.

Regresion de un defecto real de esta tarea
------------------------------------------

El primer modulo de dominio de `Task/008` importaba su error de aplicacion con
`from app.shared.errors import ConflictError`. Ese paquete reexporta tambien
`register_error_handlers`, que **importa FastAPI**: un `import` aparentemente
inocente metia el framework entero dentro del dominio. La correccion es importar
del modulo hoja, `app.shared.errors.exceptions`, que solo depende de `http` y
`typing`. Esta prueba se queda en la suite para que no vuelva a colarse.

Por que un subproceso
---------------------

`sys.modules` es del proceso. Cuando pytest llega aqui ya ha importado FastAPI
para otras pruebas, asi que mirarlo desde dentro no demostraria nada. Cada
comprobacion arranca un interprete limpio y observa lo que **ese** proceso
cargo.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parents[2]
DIRECTORIO_DE_MODULOS = RAIZ_DEL_REPOSITORIO / "app" / "modules"

#: Lo que el dominio no puede arrastrar. `starlette` y `psycopg` estan aqui
#: porque son la forma en que FastAPI y SQLAlchemy se cuelan sin nombrarse.
DEPENDENCIAS_PROHIBIDAS = ("fastapi", "starlette", "sqlalchemy", "alembic", "psycopg")

#: Guarda anti-tautologia del descubrimiento: si `_modulos_de_dominio` dejara de
#: encontrar archivos, la comprobacion pasaria sin haber importado nada.
DOMINIOS_CONOCIDOS = {
    "app.modules.book_reviews.domain",
    "app.modules.posts.domain",
    "app.modules.projects.domain",
    "app.modules.videos.domain",
}


def _modulos_de_dominio() -> list[str]:
    """Descubre los paquetes `domain` de los modulos de negocio.

    Se recorre el directorio en lugar de mantener una lista: un modulo de
    dominio nuevo entra en la comprobacion por el hecho de existir. Una lista
    escrita a mano falla **abierta**, que es justo lo que esta prueba evita.
    """
    return sorted(
        f"app.modules.{ruta.parents[1].name}.domain"
        for ruta in DIRECTORIO_DE_MODULOS.glob("*/domain/__init__.py")
    )


def _importar_en_un_interprete_limpio(modulos: list[str]) -> list[str]:
    """Importa `modulos` en un proceso nuevo y devuelve lo prohibido que se cargo."""
    codigo = (
        "import json, sys\n"
        f"for nombre in {modulos!r}:\n"
        "    __import__(nombre)\n"
        f"prohibidas = [n for n in {DEPENDENCIAS_PROHIBIDAS!r} if n in sys.modules]\n"
        "print(json.dumps(prohibidas))\n"
    )
    resultado = subprocess.run(  # noqa: S603 - interprete propio, sin entrada externa
        [sys.executable, "-c", codigo],
        cwd=RAIZ_DEL_REPOSITORIO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 0, (
        f"el subproceso no pudo importar {modulos}: {resultado.stderr.strip()}"
    )
    salida: list[str] = json.loads(resultado.stdout.strip().splitlines()[-1])
    return salida


def test_el_descubrimiento_encuentra_los_dominios_conocidos() -> None:
    """Sin esto, un descubrimiento roto dejaria la comprobacion en verde vacio."""
    descubiertos = set(_modulos_de_dominio())

    ausentes = DOMINIOS_CONOCIDOS - descubiertos
    assert not ausentes, (
        f"el descubrimiento no encontro {sorted(ausentes)}. Si esos modulos se "
        "renombraron, actualizar `DOMINIOS_CONOCIDOS`; si el mecanismo se rompio, "
        f"el resto de este modulo no estaria comprobando nada. Encontrados: {sorted(descubiertos)}"
    )


def test_la_comprobacion_detecta_de_verdad_una_dependencia_prohibida() -> None:
    """Guarda anti-tautologia del mecanismo.

    Importar `app.shared.database` **si** carga SQLAlchemy. Si esta prueba no
    lo viera, el subproceso o la deteccion estarian rotos y la comprobacion
    principal seria decorativa.
    """
    cargadas = _importar_en_un_interprete_limpio(["app.shared.database"])

    assert "sqlalchemy" in cargadas


def test_el_dominio_no_importa_framework_ni_orm() -> None:
    dominios = _modulos_de_dominio()

    cargadas = _importar_en_un_interprete_limpio(dominios)

    assert cargadas == [], (
        f"importar el dominio {dominios} cargo {cargadas}. El dominio debe ser "
        "Python plano (ADR-004). Revisar si algun import apunta a un paquete que "
        "reexporta piezas de infraestructura en lugar de al modulo hoja."
    )
