"""Regresion del arranque del adaptador Lambda (`Task/023`, hallazgo H-023-1).

El defecto que esta prueba impide
---------------------------------

`Mangum.__init__` llama a `asyncio.get_event_loop()` y captura `RuntimeError`
para crear un bucle si no existe. Es correcto en Python **3.14**, donde esa
llamada lanza. En Python **3.12** —la version que fija este proyecto— no lanza:
emite `DeprecationWarning: There is no current event loop`, devuelve un bucle
nuevo y el `except` nunca se ejecuta.

Medido el 2026-09-13 sobre `mangum==0.22.0` y CPython 3.12:

| Situacion al importar `app.lambda_handler` | Resultado |
| --- | --- |
| Sin la guarda del modulo | `DeprecationWarning`: con `-W error`, **falla** |
| Con la guarda del modulo | **exit 0**, sin aviso |

No se silencio el aviso —el proyecto rechazo esa via con `anyio`/`starlette` en
`Task/020`— ni existe una version corregida aguas arriba que adoptar: se dejo de
tomar el camino deprecado.

Como se retira esta guarda
--------------------------

Cuando Mangum publique una version que no dependa del `RuntimeError` de
`get_event_loop()`, o cuando el proyecto pase a una version de Python donde esa
llamada vuelva a lanzar, se elimina el bloque de `app/lambda_handler.py` y esta
prueba debe seguir en verde por si sola.

Por que en un subproceso limpio
-------------------------------

Lo que se mide es el **import** del modulo con `-W error`, y eso solo se observa
desde fuera: dentro de la suite el modulo ya esta importado y el bucle ya esta
establecido, asi que una comprobacion en proceso no probaria nada. Es el mismo
motivo por el que `tests/test_hermeticidad.py` usa subprocesos.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parents[2]

#: Importa el adaptador y comprueba que quedo utilizable. El `-W error` del
#: subproceso es lo que convierte cualquier aviso del arranque en un fallo.
_PROGRAMA = """\
import app.lambda_handler as adaptador

assert callable(adaptador.handler)
print("import-correcto")
"""


def _entorno_minimo() -> dict[str, str]:
    """Entorno sin `BLOG_*` heredada y con el minimo que exige `Settings`.

    El adaptador importa `app.main`, que construye la aplicacion al importarse.
    Se le da la configuracion ficticia del harness —nunca la del desarrollador—
    para que el subproceso no dependa del `.env` local (`CERT-AUD-001`).
    """
    from tests import ENTORNO_MINIMO_DE_PRUEBAS

    entorno = {clave: valor for clave, valor in os.environ.items() if not clave.startswith("BLOG_")}
    entorno.update(ENTORNO_MINIMO_DE_PRUEBAS)
    entorno["PYTHONPATH"] = str(RAIZ_DEL_REPOSITORIO)
    return entorno


def test_importar_el_handler_no_emite_ningun_aviso(tmp_path: Path) -> None:
    """`python -W error -c "import app.lambda_handler"` debe terminar en exit 0."""
    resultado = subprocess.run(  # noqa: S603
        [sys.executable, "-W", "error", "-c", _PROGRAMA],
        cwd=tmp_path,
        env=_entorno_minimo(),
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert resultado.returncode == 0, (
        "importar el adaptador emitio un aviso o fallo\n"
        f"stdout:\n{resultado.stdout}\nstderr:\n{resultado.stderr}"
    )
    assert "import-correcto" in resultado.stdout


def test_el_subproceso_si_convierte_los_avisos_en_error(tmp_path: Path) -> None:
    """Guarda anti-tautologia: `-W error` esta realmente activo en el subproceso.

    Sin esto, la prueba de arriba pasaria igual aunque el aviso siguiera
    saliendo, porque nadie habria comprobado que el subproceso lo escala.
    """
    resultado = subprocess.run(
        [
            sys.executable,
            "-W",
            "error",
            "-c",
            "import warnings; warnings.warn('aviso de prueba', DeprecationWarning)",
        ],
        cwd=tmp_path,
        env=_entorno_minimo(),
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert resultado.returncode != 0
    assert "DeprecationWarning" in resultado.stderr
