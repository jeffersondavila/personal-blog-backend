"""La semilla se puede ejecutar tal como esta documentada (`Task/022`, defecto H-3).

Por que existe esta prueba
--------------------------

`scripts/seed_local.py` se escribio con TDD y sus doce casos de comportamiento
pasaban **importado** desde la suite. Pero la primera ejecucion real, siguiendo
la linea de uso de su propio docstring, fallo:

    ModuleNotFoundError: No module named 'app'

Al invocar un archivo por su ruta, Python coloca en `sys.path` el directorio del
**archivo** —`scripts/`— y no la raiz del repositorio, asi que `app` deja de
resolverse. Ninguna prueba lo detectaba porque todas importaban el modulo, que
es justo el camino que no tiene el problema.

Lo que se fija aqui es la **invocabilidad**: que el comando documentado funcione
de verdad. Se ejecuta en un subproceso porque es la unica forma de reproducir el
`sys.path` real de la linea de comandos; importar el modulo no lo reproduce.

No toca PostgreSQL: con el entorno sin las variables de la semilla, el script
valida la entrada y sale **antes** de abrir ninguna conexion. Por eso esta
prueba vive fuera de `tests/integration/` y no lleva la marca `integration`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.seed_local import CODIGO_DE_ERROR, VARIABLE_CORREO

RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parents[1]
RUTA_DEL_SCRIPT = RAIZ_DEL_REPOSITORIO / "scripts" / "seed_local.py"

#: Prefijos que se retiran del entorno heredado: los de la semilla y los de la
#: configuracion de la aplicacion. Lo demas se conserva.
#:
#: Se parte del entorno real y se resta, en lugar de construir uno vacio desde
#: cero: en Windows, un entorno sin `SystemRoot` impide inicializar el stack de
#: sockets y el subproceso muere con `WinError 10106` antes de ejecutar una sola
#: linea del script. Fue el primer intento de esta prueba, y no medía nada.
PREFIJOS_RETIRADOS = ("PERSONAL_BLOG_", "BLOG_")


def _entorno_sin_configuracion() -> dict[str, str]:
    return {
        clave: valor
        for clave, valor in os.environ.items()
        if not clave.startswith(PREFIJOS_RETIRADOS)
    }


def _ejecutar(argumentos: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argumentos fijos, sin shell y sin entrada externa
        [sys.executable, *argumentos],
        capture_output=True,
        text=True,
        cwd=RAIZ_DEL_REPOSITORIO,
        env=_entorno_sin_configuracion(),
        timeout=120,
        check=False,
    )


def test_se_ejecuta_por_ruta_de_archivo() -> None:
    """`python scripts/seed_local.py` — la forma que documenta el runbook."""
    resultado = _ejecutar([str(RUTA_DEL_SCRIPT)])

    assert "ModuleNotFoundError" not in resultado.stderr, resultado.stderr
    assert resultado.returncode == CODIGO_DE_ERROR
    assert VARIABLE_CORREO in resultado.stderr


def test_se_ejecuta_como_modulo() -> None:
    """`python -m scripts.seed_local` — la forma equivalente, tambien soportada."""
    resultado = _ejecutar(["-m", "scripts.seed_local"])

    assert "ModuleNotFoundError" not in resultado.stderr, resultado.stderr
    assert resultado.returncode == CODIGO_DE_ERROR
    assert VARIABLE_CORREO in resultado.stderr


def test_no_intenta_conectarse_antes_de_validar_la_entrada() -> None:
    """Sin variables, falla por la entrada y no por la base de datos.

    Es lo que permite que esta prueba no necesite PostgreSQL, y ademas es el
    comportamiento util: quien olvida una variable recibe el nombre de la
    variable, no un error de conexion que no explica nada.
    """
    resultado = _ejecutar([str(RUTA_DEL_SCRIPT)])

    assert "psycopg" not in resultado.stderr.lower()
    assert "connection" not in resultado.stderr.lower()
    assert "database_url" not in resultado.stderr.lower()
