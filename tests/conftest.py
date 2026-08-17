"""Configuracion compartida de las pruebas.

Las pruebas nunca leen el `.env` del desarrollador. Eso se consigue con **tres**
mecanismos complementarios, porque ninguno basta por si solo:

1. `tests/__init__.py` aisla el proceso entero antes de la collection: limpia el
   entorno y neutraliza el `.env` para toda instanciacion de `Settings`.
2. `_isolated_environment` borra del entorno toda variable `BLOG_*` antes de cada
   prueba, para que una prueba no herede lo que otra dejo puesto.
3. `settings_factory` construye la configuracion con `_env_file=None`.

El punto 2 no cubre el punto 3: `pydantic-settings` lee el archivo `.env` del
directorio de trabajo **aunque no haya ninguna variable en el entorno**. Hasta
`Task/005.6` faltaba el punto 3, y los campos que una prueba no fijaba de forma
explicita —`app_name`, `log_level`, `app_debug`— se tomaban del `.env` local.

Y ninguno de los dos alcanzaba la **collection**, que ocurre antes de que exista
ninguna fixture: ese hueco es el punto 1, anadido en `Task/005.7`
(`CERT-AUD-001`). Regresion en `tests/test_hermeticidad.py`.

Asi el resultado no depende de donde se ejecute y ninguna credencial real entra
en la suite.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shared.configuration import Settings, build_settings
from tests import FAKE_DATABASE_URL


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deja el entorno de cada prueba en el mismo estado controlado.

    Borra toda variable `BLOG_*` —incluida la que haya dejado puesta otra
    prueba— y **repone** la URL ficticia obligatoria. Reponerla no es un detalle:
    `BLOG_DATABASE_URL` es el unico campo sin valor por defecto, asi que un
    proceso sin ella no puede construir la configuracion. `app/main.py` la
    necesita al importarse, y desde `Task/005.7` ese import ocurre dentro de una
    fixture, no durante la collection.

    Las pruebas que necesitan comprobar la ausencia de la variable la borran
    ellas mismas con `monkeypatch.delenv`, que es explicito y local.
    """
    for name in list(os.environ):
        if name.upper().startswith("BLOG_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BLOG_DATABASE_URL", FAKE_DATABASE_URL)


@pytest.fixture
def settings_factory() -> Any:
    """Devuelve una funcion que crea configuraciones de prueba.

    `_env_file=None` es obligatorio y **no se puede sobrescribir** desde
    `overrides`: sin el, `Settings` lee el `.env` del directorio de trabajo
    —el del desarrollador— para todo campo que la prueba no fije de forma
    explicita. Eso hacia que `app_name`, `log_level` o `app_debug` dependieran
    de la maquina que ejecuta la suite. Regresion en
    `test_la_configuracion_de_prueba_ignora_el_dotenv_del_desarrollador`.
    """

    def _factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "app_env": "test",
            "database_url": FAKE_DATABASE_URL,
            "log_format": "text",
            **overrides,
            # Despues de `overrides` a proposito: el aislamiento no es
            # negociable por quien llama al factory.
            "_env_file": None,
        }
        return build_settings(**values)

    return _factory


@pytest.fixture
def settings(settings_factory: Any) -> Settings:
    """Configuracion valida de prueba."""
    result: Settings = settings_factory()
    return result


@pytest.fixture
def application(settings: Settings) -> FastAPI:
    """Aplicacion FastAPI construida con la configuracion de prueba.

    El import de `app.main` vive **dentro** de la fixture a proposito. Ese modulo
    construye la instancia ASGI al importarse (`app = create_app()`), asi que un
    import en la cabecera de este archivo la construiria durante la collection,
    con el entorno que hubiera en ese momento. Aqui se importa cuando una prueba
    lo pide, con el aislamiento ya aplicado.

    Es la segunda capa de `CERT-AUD-001`: `tests/__init__.py` ya deja el proceso
    hermetico, pero mantener las dos capas independientes significa que perder
    una en una refactorizacion futura no reabre el defecto.
    """
    from app.main import create_app

    return create_app(settings=settings)


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    """Cliente HTTP contra la aplicacion de prueba.

    `raise_server_exceptions=False` permite comprobar que una excepcion no
    prevista se convierte en la respuesta `500` del proyecto en lugar de
    propagarse hasta la prueba.
    """
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client
