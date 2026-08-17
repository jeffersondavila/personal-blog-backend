"""Hermeticidad del camino de integracion (`CERT-AUD-001`, manifestacion A).

`configured_process` deja el proceso apuntando a la base real de pruebas para las
funciones que resuelven la configuracion por si mismas —`session_scope`,
`get_session`, `alembic/env.py`—. Esas funciones llaman a `get_settings()`, que
construye `Settings` **sin** overrides: hasta `Task/005.7` eso significaba leer el
`.env` del directorio de trabajo para todo campo que la fixture no fijara.

La fixture solo fija `BLOG_DATABASE_URL`. `app_name`, `log_level`, `app_debug` y
el resto de campos `BLOG_*` venian, por tanto, del `.env` del desarrollador: la
integracion se ejecutaba con una configuracion que dependia de la maquina.

`tests/test_hermeticidad.py` cubre el arranque de la suite. Esta prueba cubre la
ruta de integracion, que es la que llega hasta PostgreSQL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

DOTENV_INTRUSO = "BLOG_APP_NAME=nombre-intruso\nBLOG_LOG_LEVEL=CRITICAL\nBLOG_APP_DEBUG=true\n"


def test_configured_process_no_hereda_campos_de_un_dotenv(
    configured_process: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`get_settings()` bajo `configured_process` no toma nada del `.env` del cwd.

    El `.env` intruso se coloca **despues** de que la fixture haya preparado el
    proceso, que es exactamente el orden real: la configuracion se resuelve de
    forma perezosa, en la primera llamada, ya dentro de la prueba.
    """
    from app.shared.configuration import get_settings

    (tmp_path / ".env").write_text(DOTENV_INTRUSO, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    configuracion = get_settings()

    # Ningun valor intruso entro...
    assert configuracion.app_name != "nombre-intruso"
    assert configuracion.log_level != "CRITICAL"
    assert configuracion.app_debug is not True

    # ...y los valores son los controlados por el harness.
    assert configuracion.app_name == "personal-blog-backend"
    assert configuracion.log_level == "INFO"
    assert configuracion.app_debug is False

    # La unica variable que `configured_process` fija de verdad sigue en pie: el
    # destino real de integracion, que la guarda ya verifico.
    assert str(configuracion.database_url).endswith("_test")
