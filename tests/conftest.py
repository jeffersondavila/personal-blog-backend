"""Configuracion compartida de las pruebas.

Las pruebas nunca leen el `.env` del desarrollador. Eso se consigue con **dos**
mecanismos complementarios, porque uno solo no basta:

1. `_isolated_environment` borra del entorno toda variable `BLOG_*`.
2. `settings_factory` construye la configuracion con `_env_file=None`.

El punto 1 no cubre el punto 2: `pydantic-settings` lee el archivo `.env` del
directorio de trabajo **aunque no haya ninguna variable en el entorno**. Hasta
`Task/005.6` faltaba el punto 2, y los campos que una prueba no fijaba de forma
explicita —`app_name`, `log_level`, `app_debug`— se tomaban del `.env` local.
La suite pasaba o fallaba segun la maquina.

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

from app.main import create_app
from app.shared.configuration import Settings, build_settings
from tests import FAKE_DATABASE_URL


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Elimina del entorno toda variable BLOG_* antes de cada prueba."""
    for name in list(os.environ):
        if name.upper().startswith("BLOG_"):
            monkeypatch.delenv(name, raising=False)


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
    """Aplicacion FastAPI construida con la configuracion de prueba."""
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
