"""Origen publico del sitio: `BLOG_PUBLIC_SITE_BASE_URL` (`Task/016`).

Por que el backend necesita conocer el origen del **sitio**
-----------------------------------------------------------

El sitemap (**E-05**) enumera URL del sitio publico, no del API. Un sitemap que
listara `https://api.ejemplo.test/articulos/x` seria simplemente falso: esa
direccion no sirve la pagina. Y el backend no puede deducir el origen del sitio
de la peticion que recibe —`Host` la escribe el cliente, y detras de un proxy o
de API Gateway dice el nombre del API, no el del sitio—.

Por eso es **configuracion** (requisito T-01), obligatoria y validada al
arrancar, con el mismo criterio con el que lo son `BLOG_DATABASE_URL` y
`BLOG_STORAGE_BUCKET`: sin ella el proceso no arranca.

*Fail-closed* y no un valor por omision: un origen inventado produciria un
sitemap que apunta a un sitio que no es este, y un sitemap incorrecto es peor
que no tenerlo.

**No fija ningun dominio.** El dominio concreto es la decision **D-07**, abierta
hasta `Task/029`/`Task/035`. Aqui solo se nombra y se valida la variable.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.shared.configuration import ConfigurationError
from app.shared.configuration.settings import build_settings
from tests import FAKE_DATABASE_URL

CONFIGURACION_MINIMA: dict[str, Any] = {
    "app_env": "test",
    "database_url": FAKE_DATABASE_URL,
    "log_format": "text",
    "_env_file": None,
}


def _construir(**overrides: object) -> Any:
    return build_settings(**{**CONFIGURACION_MINIMA, **overrides})


class TestFormaAceptada:
    """Lo que la variable admite, y como queda normalizado."""

    def test_acepta_un_origen_http_y_lo_normaliza_sin_barra_final(self) -> None:
        settings = _construir(public_site_base_url="http://localhost:8081/")

        assert settings.public_site_base_url == "http://localhost:8081"

    def test_acepta_https_y_conserva_el_prefijo_de_ruta(self) -> None:
        settings = _construir(public_site_base_url="https://ejemplo.test/blog/")

        assert settings.public_site_base_url == "https://ejemplo.test/blog"

    def test_ignora_los_espacios_alrededor_del_valor(self) -> None:
        settings = _construir(public_site_base_url="  http://localhost:8081  ")

        assert settings.public_site_base_url == "http://localhost:8081"

    def test_varias_barras_finales_se_recortan(self) -> None:
        settings = _construir(public_site_base_url="http://localhost:8081///")

        assert settings.public_site_base_url == "http://localhost:8081"


class TestFailClosed:
    """Lo que rompe el arranque, que es el punto de la variable."""

    def test_falla_cuando_no_esta_definida(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sin la variable, el proceso no arranca.

        Hay que retirarla del entorno explicitamente: `tests/__init__.py` la
        repone para todo el proceso —igual que hace con la URL de base de datos—
        porque sin ella ningun `Settings()` seria construible. Es el mismo patron
        que `test_falla_si_falta_la_url_de_base_de_datos`.
        """
        monkeypatch.delenv("BLOG_PUBLIC_SITE_BASE_URL", raising=False)

        with pytest.raises(ConfigurationError) as error:
            build_settings(**CONFIGURACION_MINIMA)

        assert "public_site_base_url" in str(error.value)

    @pytest.mark.parametrize(
        "valor",
        [
            "",
            "   ",
            "/articulos",
            "ejemplo.test",
            "ftp://ejemplo.test",
            "http://",
        ],
    )
    def test_falla_ante_un_valor_no_utilizable(self, valor: str) -> None:
        with pytest.raises(ConfigurationError):
            _construir(public_site_base_url=valor)

    def test_el_mensaje_nombra_la_variable(self) -> None:
        with pytest.raises(ConfigurationError) as error:
            _construir(public_site_base_url="no-es-una-url")

        assert "BLOG_PUBLIC_SITE_BASE_URL" in str(error.value)


class TestNoSeConfundeConElApi:
    """El origen del sitio y el del API son cosas distintas (**D-15**)."""

    def test_el_origen_del_sitio_es_independiente_del_prefijo_del_api(self) -> None:
        settings = _construir(
            public_site_base_url="https://ejemplo.test",
            api_v1_prefix="/api/v1",
        )

        assert settings.public_site_base_url == "https://ejemplo.test"
        assert settings.api_v1_prefix == "/api/v1"
