"""Configuracion compartida de las pruebas.

Las pruebas nunca leen el `.env` del desarrollador: cada una construye la
configuracion que necesita. Asi el resultado no depende de la maquina donde se
ejecuten y ninguna credencial real entra en la suite.
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
    """Devuelve una funcion que crea configuraciones de prueba."""

    def _factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "app_env": "test",
            "database_url": FAKE_DATABASE_URL,
            "log_format": "text",
            **overrides,
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
