"""Regresion permanente de `CERT-AUD-001`: la suite es hermetica frente al dotenv.

`Task/005.6` dejo aislado el *cuerpo* de las pruebas —`settings_factory` construye
con `_env_file=None`— pero no el **arranque** de la propia suite. Quedaba un
camino abierto que la certificacion final reprodujo:

    tests/conftest.py  ->  from app.main import create_app
    app/main.py        ->  app = create_app()        (nivel de modulo)
    create_app()       ->  get_settings()
    get_settings()     ->  Settings()                (env_file=".env")

Ese import ocurre **durante la collection**, antes de que ninguna fixture pueda
intervenir: las fixtures se ejecutan despues de collection, asi que un
`autouse=True` no lo alcanza. Resultado demostrado: un `.env` situado en el
directorio de trabajo alteraba `app_name`, `log_level` y `app_debug` del proceso
de pruebas.

Lo que se comprueba aqui es el arranque completo, no una funcion suelta, y por
eso cada caso se ejecuta en un **subproceso limpio** con un directorio de trabajo
propio: es la unica forma de observar la collection desde fuera y de no depender
del `.env` real del desarrollador ni del cwd habitual del repositorio.

El alcance de la garantia es el **harness oficial**. No se afirma que ningun
codigo Python imaginable pueda leer un `.env`: se afirma que arrancar la suite no
lo hace.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parents[1]

#: Valores deliberadamente distintos de los de por defecto: si aparecen en el
#: proceso de pruebas, solo pueden venir de este archivo.
DOTENV_INTRUSO = "BLOG_APP_NAME=nombre-intruso\nBLOG_LOG_LEVEL=CRITICAL\nBLOG_APP_DEBUG=true\n"

APP_NAME_POR_DEFECTO = "personal-blog-backend"

#: Complemento de pytest que observa el estado del bootstrap **al terminar la
#: collection**, que es justo el instante en el que el defecto se manifestaba.
#: Importa `app.main` el mismo: asi la prueba no depende de que el harness lo
#: importe o no, y mide lo que de verdad importa —si al construir la aplicacion
#: en ese momento entran valores del `.env` del directorio de trabajo—.
_SONDA_DE_COLLECTION = """\
import json
import os
import sys


def pytest_collection_finish(session):
    informe = {"app_main_ya_estaba_importado": "app.main" in sys.modules}

    import app.main
    from app.shared.configuration import get_settings

    configuracion = get_settings()
    informe["app_title"] = app.main.app.title
    informe["app_debug"] = app.main.app.debug
    informe["settings_app_name"] = configuracion.app_name
    informe["settings_log_level"] = configuracion.log_level

    with open(os.environ["INFORME_DE_LA_SONDA"], "w", encoding="utf-8") as destino:
        json.dump(informe, destino)
"""

#: Misma construccion, pero **sin pasar por el bootstrap de la suite**. Es la
#: guarda anti-tautologia: demuestra que el `.env` intruso esta donde
#: `pydantic-settings` lo busca y que es legible. Sin esto, un `.env` colocado en
#: una ruta equivocada haria pasar la prueba de aislamiento sin probar nada.
_SIN_BOOTSTRAP = """\
import json
import os
import sys

sys.path.insert(0, os.environ["RAIZ_DEL_REPOSITORIO"])
# El minimo obligatorio para que `Settings` sea construible. Se fija aqui —y no
# en el `.env` intruso— a proposito: lo que la prueba mide es si los valores
# INTRUSOS (`app_name`, `log_level`, `app_debug`) llegan, no si la aplicacion
# arranca. Desde `Task/010` ese minimo incluye el almacenamiento de objetos.
os.environ["BLOG_DATABASE_URL"] = "postgresql://usuario:clave@localhost:5432/base_de_prueba"
os.environ["BLOG_STORAGE_BUCKET"] = "bucket-de-prueba"
os.environ["BLOG_STORAGE_ENDPOINT_URL"] = "http://almacenamiento.invalid:9000"
os.environ["BLOG_STORAGE_ACCESS_KEY"] = "clave_de_prueba"
os.environ["BLOG_STORAGE_SECRET_KEY"] = "secreto_de_prueba"

import app.main

with open(os.environ["INFORME_DE_LA_SONDA"], "w", encoding="utf-8") as destino:
    json.dump({"app_title": app.main.app.title, "app_debug": app.main.app.debug}, destino)
"""


def _entorno_limpio(directorio: Path) -> dict[str, str]:
    """Entorno del subproceso sin ninguna variable `BLOG_*` heredada.

    El subproceso debe apanarselas solo: si necesitara que el proceso padre le
    pasara la configuracion, la prueba no estaria midiendo el bootstrap.
    """
    entorno = {clave: valor for clave, valor in os.environ.items() if not clave.startswith("BLOG_")}
    entorno["PYTHONPATH"] = os.pathsep.join([str(directorio), str(RAIZ_DEL_REPOSITORIO)])
    entorno["RAIZ_DEL_REPOSITORIO"] = str(RAIZ_DEL_REPOSITORIO)
    entorno.pop("PERSONAL_BLOG_TEST_DATABASE_URL", None)
    return entorno


def _preparar_directorio_intruso(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text(DOTENV_INTRUSO, encoding="utf-8")
    return tmp_path


def test_la_collection_no_consume_un_dotenv_del_directorio_de_trabajo(tmp_path: Path) -> None:
    """`CERT-AUD-001`: arrancar la suite desde un cwd con `.env` no lo lee.

    Se ejecuta una collection real —`--collect-only`— desde un directorio que
    contiene un `.env` intruso. La sonda construye la aplicacion al terminar la
    collection y reporta que valores llegaron.
    """
    directorio = _preparar_directorio_intruso(tmp_path)
    (directorio / "sonda_de_collection.py").write_text(_SONDA_DE_COLLECTION, encoding="utf-8")
    informe = directorio / "informe.json"

    entorno = _entorno_limpio(directorio)
    entorno["INFORME_DE_LA_SONDA"] = str(informe)

    resultado = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "sonda_de_collection",
            "-c",
            str(RAIZ_DEL_REPOSITORIO / "pyproject.toml"),
            "--rootdir",
            str(RAIZ_DEL_REPOSITORIO),
            str(RAIZ_DEL_REPOSITORIO / "tests"),
        ],
        cwd=directorio,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert resultado.returncode == 0, (
        f"la collection fallo desde un cwd ajeno al repositorio\n"
        f"stdout:\n{resultado.stdout}\nstderr:\n{resultado.stderr}"
    )
    assert informe.exists(), (
        f"la sonda no llego a escribir su informe\n"
        f"stdout:\n{resultado.stdout}\nstderr:\n{resultado.stderr}"
    )

    observado = json.loads(informe.read_text(encoding="utf-8"))

    # El defecto concreto: el valor intruso NO puede haber llegado.
    assert observado["app_title"] != "nombre-intruso"
    assert observado["settings_app_name"] != "nombre-intruso"
    assert observado["settings_log_level"] != "CRITICAL"
    assert observado["app_debug"] is not True

    # Y ademas los valores son los controlados, no cualquier otra cosa.
    assert observado["app_title"] == APP_NAME_POR_DEFECTO
    assert observado["settings_app_name"] == APP_NAME_POR_DEFECTO
    assert observado["settings_log_level"] == "INFO"
    assert observado["app_debug"] is False


def test_la_collection_no_construye_la_aplicacion(tmp_path: Path) -> None:
    """Segunda capa: la collection ni siquiera llega a construir la aplicacion.

    El aislamiento del bootstrap ya basta para que un `.env` intruso no entre.
    Esta prueba fija ademas la propiedad estructural que lo hace robusto: nada
    del arranque de la suite importa `app.main`, asi que no hay ninguna
    aplicacion construida con el entorno que hubiera en ese momento.

    Las dos capas son deliberadamente independientes: si una se pierde en una
    refactorizacion futura, la otra sigue impidiendo el defecto original.
    """
    directorio = _preparar_directorio_intruso(tmp_path)
    (directorio / "sonda_de_collection.py").write_text(_SONDA_DE_COLLECTION, encoding="utf-8")
    informe = directorio / "informe.json"

    entorno = _entorno_limpio(directorio)
    entorno["INFORME_DE_LA_SONDA"] = str(informe)

    subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "sonda_de_collection",
            "-c",
            str(RAIZ_DEL_REPOSITORIO / "pyproject.toml"),
            "--rootdir",
            str(RAIZ_DEL_REPOSITORIO),
            str(RAIZ_DEL_REPOSITORIO / "tests"),
        ],
        cwd=directorio,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )

    observado = json.loads(informe.read_text(encoding="utf-8"))

    assert observado["app_main_ya_estaba_importado"] is False, (
        "la collection importo `app.main`, que construye la aplicacion al importarse. "
        "Ese import debe ocurrir dentro de una fixture, no durante la collection."
    )


def test_el_dotenv_intruso_si_es_legible_sin_el_bootstrap(tmp_path: Path) -> None:
    """Guarda anti-tautologia de las dos pruebas anteriores.

    Construye la aplicacion en el **mismo** directorio y con el **mismo** `.env`,
    pero sin importar el paquete `tests`. Los valores intrusos deben llegar: eso
    demuestra que el archivo es legible desde ahi y que lo que marca la
    diferencia es el bootstrap de la suite, no una ruta mal construida.
    """
    directorio = _preparar_directorio_intruso(tmp_path)
    (directorio / "sin_bootstrap.py").write_text(_SIN_BOOTSTRAP, encoding="utf-8")
    informe = directorio / "informe.json"

    entorno = _entorno_limpio(directorio)
    entorno["INFORME_DE_LA_SONDA"] = str(informe)

    resultado = subprocess.run(  # noqa: S603
        [sys.executable, str(directorio / "sin_bootstrap.py")],
        cwd=directorio,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert resultado.returncode == 0, f"stdout:\n{resultado.stdout}\nstderr:\n{resultado.stderr}"

    observado = json.loads(informe.read_text(encoding="utf-8"))

    assert observado["app_title"] == "nombre-intruso"
    assert observado["app_debug"] is True


def test_el_aislamiento_no_depende_del_directorio_de_trabajo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La configuracion del proceso de pruebas es la misma desde cualquier cwd.

    Complementa a las pruebas de subproceso desde dentro del propio proceso: aqui
    ya no hay ningun `_env_file=None` explicito de por medio, se llama a
    `get_settings()` tal cual lo llaman `session_scope` y `alembic/env.py`.
    """
    from app.shared.configuration import get_settings
    from tests import FAKE_DATABASE_URL

    (tmp_path / ".env").write_text(DOTENV_INTRUSO, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # `_isolated_environment` deja el entorno sin ninguna `BLOG_*`; la URL se
    # repone aqui porque es obligatoria y su ausencia haria fallar el arranque
    # por un motivo que no es el que se esta probando.
    monkeypatch.setenv("BLOG_DATABASE_URL", FAKE_DATABASE_URL)
    get_settings.cache_clear()
    try:
        configuracion = get_settings()

        assert configuracion.app_name == APP_NAME_POR_DEFECTO
        assert configuracion.log_level == "INFO"
        assert configuracion.app_debug is False
    finally:
        get_settings.cache_clear()
