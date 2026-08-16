"""Pruebas de la configuracion tipada.

Comprueban las tres garantias que la configuracion debe dar: se valida al
arrancar (fail-fast), tiene valores por defecto seguros y **no filtra la
contrasena** de la base de datos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.shared.configuration import ConfigurationError, Settings, build_settings, get_settings
from tests import FAKE_DATABASE_URL

CLAVE = "clave_de_prueba"

#: Valores deliberadamente distintos de los de por defecto, para que su
#: aparicion en una configuracion de prueba solo pueda venir del `.env`.
DOTENV_INTRUSO = (
    "BLOG_APP_NAME=nombre-del-desarrollador\nBLOG_LOG_LEVEL=CRITICAL\nBLOG_APP_DEBUG=true\n"
)


def test_falla_si_falta_la_url_de_base_de_datos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BLOG_DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError) as error:
        build_settings(_env_file=None)

    assert "database_url" in str(error.value)


def test_falla_si_la_url_no_es_de_postgresql(settings_factory: Any) -> None:
    with pytest.raises(ConfigurationError):
        settings_factory(database_url="mysql://usuario:clave@localhost:3306/base")


def test_falla_ante_una_variable_desconocida(settings_factory: Any) -> None:
    """Una variable mal escrita debe romper el arranque, no ignorarse en silencio."""
    with pytest.raises(ConfigurationError):
        settings_factory(variable_inexistente="valor")


def test_falla_ante_un_entorno_no_valido(settings_factory: Any) -> None:
    with pytest.raises(ConfigurationError):
        settings_factory(app_env="preproduccion")


def test_el_mensaje_de_error_no_incluye_valores(monkeypatch: pytest.MonkeyPatch) -> None:
    """El error de configuracion nombra el campo, nunca su valor (requisito S-08)."""
    monkeypatch.setenv("BLOG_DATABASE_URL", f"postgresql://usuario:{CLAVE}@localhost:5432/base")
    monkeypatch.setenv("BLOG_LOG_LEVEL", "VERBOSO")

    with pytest.raises(ConfigurationError) as error:
        build_settings(_env_file=None)

    mensaje = str(error.value)
    assert "log_level" in mensaje
    assert CLAVE not in mensaje
    assert "VERBOSO" not in mensaje


def test_valores_por_defecto_seguros(settings: Settings) -> None:
    assert settings.app_debug is False
    assert settings.database_echo is False
    assert settings.log_format in {"json", "text"}
    assert settings.api_v1_prefix == "/api/v1"


def test_debug_prohibido_en_produccion(settings_factory: Any) -> None:
    with pytest.raises(ConfigurationError):
        settings_factory(app_env="production", app_debug=True)


def test_echo_de_sql_prohibido_en_produccion(settings_factory: Any) -> None:
    with pytest.raises(ConfigurationError):
        settings_factory(app_env="production", database_echo=True)


def test_una_configuracion_de_produccion_valida_se_construye(settings_factory: Any) -> None:
    """La validacion de produccion rechaza lo inseguro **y acepta lo seguro**.

    Sin este caso solo estaba probada la rama que lanza `ValueError`: una
    validacion que rechazara *toda* configuracion `production` habria pasado la
    suite igualmente.
    """
    configuracion = settings_factory(
        app_env="production",
        app_debug=False,
        database_echo=False,
        log_format="json",
    )

    assert configuracion.app_env == "production"
    assert configuracion.app_debug is False
    assert configuracion.database_echo is False
    assert configuracion.log_format == "json"


def test_la_configuracion_de_prueba_ignora_el_dotenv_del_desarrollador(
    settings_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresion (`Task/005.6`): la suite no puede depender del `.env` local.

    `pydantic-settings` resuelve `env_file=".env"` **relativo al directorio de
    trabajo**. Situando un `.env` intruso en el cwd se reproduce exactamente el
    defecto: los campos que la prueba no fija de forma explicita se tomaban de
    ese archivo.
    """
    (tmp_path / ".env").write_text(DOTENV_INTRUSO, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    configuracion = settings_factory()

    # No basta con comprobar el valor por defecto: se comprueba tambien que el
    # valor del `.env` intruso no llego, que es el defecto concreto.
    assert configuracion.app_name != "nombre-del-desarrollador"
    assert configuracion.app_name == "personal-blog-backend"
    assert configuracion.log_level != "CRITICAL"
    assert configuracion.log_level == "INFO"
    assert configuracion.app_debug is False


def test_el_dotenv_intruso_del_caso_anterior_si_es_legible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda anti-tautologia del test anterior.

    Si `Settings` no encontrara el `.env` por una ruta mal construida, la
    prueba de aislamiento pasaria sin demostrar nada. Aqui se construye la
    configuracion **sin** `_env_file=None` y se exige que los valores intrusos
    **si** lleguen: eso prueba que el archivo esta donde `pydantic-settings` lo
    busca y que el aislamiento es lo que marca la diferencia.
    """
    (tmp_path / ".env").write_text(DOTENV_INTRUSO, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    configuracion = build_settings(app_env="test", database_url=FAKE_DATABASE_URL)

    assert configuracion.app_name == "nombre-del-desarrollador"
    assert configuracion.log_level == "CRITICAL"
    assert configuracion.app_debug is True


def test_la_contrasena_no_aparece_en_repr(settings: Settings) -> None:
    assert CLAVE not in repr(settings)
    assert CLAVE not in str(settings)


def test_url_enmascarada_para_registrar(settings: Settings) -> None:
    segura = settings.database_url_safe

    assert CLAVE not in segura
    assert ":***@" in segura
    assert "base_de_prueba" in segura


def test_url_sin_contrasena_se_devuelve_intacta(settings_factory: Any) -> None:
    sin_clave = settings_factory(database_url="postgresql://usuario@localhost:5432/base")

    assert sin_clave.database_url_safe.endswith("/base")
    assert "***" not in sin_clave.database_url_safe


def test_url_de_sqlalchemy_fija_el_driver(settings: Settings) -> None:
    assert settings.sqlalchemy_url.startswith("postgresql+psycopg://")
    assert settings.sqlalchemy_url.endswith("/base_de_prueba")


def test_url_con_driver_explicito_se_respeta(settings_factory: Any) -> None:
    explicita = settings_factory(
        database_url="postgresql+psycopg://usuario:clave@localhost:5432/base"
    )

    assert explicita.sqlalchemy_url.startswith("postgresql+psycopg://")


def test_la_configuracion_es_inmutable(settings: Settings) -> None:
    with pytest.raises(Exception, match=r"frozen|immutable"):
        settings.app_debug = True


def test_get_settings_memoriza_el_resultado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLOG_DATABASE_URL", FAKE_DATABASE_URL)
    get_settings.cache_clear()
    try:
        primera = get_settings()
        segunda = get_settings()
        assert primera is segunda
    finally:
        get_settings.cache_clear()
