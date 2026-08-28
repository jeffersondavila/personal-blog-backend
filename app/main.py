"""Punto de entrada de la aplicacion FastAPI.

`create_app()` construye la aplicacion; `app` es la instancia ASGI que ejecutan
uvicorn en local y, mas adelante, el adaptador Lambda (`Task/023`). Ese
adaptador sera una capa fina que envuelve **esta misma** instancia: el codigo de
aqui no conoce Lambda (requisito T-04).

Importar este modulo con una configuracion invalida falla de inmediato: es la
validacion fail-fast exigida por el requisito T-01.
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.api import health_router
from app.api.public import routers_publicos
from app.shared.configuration import Settings, get_settings
from app.shared.errors.handlers import register_error_handlers
from app.shared.logging import configure_logging, get_logger

_logger = get_logger(__name__)

_DESCRIPTION = """API del blog personal.

**API publica de solo lectura** (`Task/009`): perfil, articulos, reviews de
libros, videos, proyectos, etiquetas y busqueda. Toda coleccion esta paginada y
**solo** se expone contenido publicado: los borradores y los archivados no
aparecen en ninguna respuesta.

La API administrativa (`/api/v1/admin/*`) llega en `Task/011` y `Task/012`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construye la aplicacion FastAPI.

    Recibir `settings` permite a las pruebas montar la aplicacion con una
    configuracion propia sin tocar el entorno del proceso.
    """
    resolved = settings or get_settings()

    configure_logging(level=resolved.log_level, log_format=resolved.log_format)

    application = FastAPI(
        title=resolved.app_name,
        version=__version__,
        description=_DESCRIPTION,
        debug=resolved.app_debug,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )

    # Sin middleware de CORS: en `Task/005` ningun navegador consume esta API.
    # Los origenes permitidos se definen, por ambiente y de forma explicita, al
    # integrar el frontend (`Task/007`) y se endurecen en `Task/018` y
    # `Task/033`. No configurarlo es lo seguro: el valor por defecto de un
    # navegador es denegar, y `*` esta prohibido (requisito S-04).

    if settings is not None:
        # La aplicacion se construyo con una configuracion explicita, asi que
        # las dependencias deben resolver esa misma y no la del entorno del
        # proceso. Lo usan las pruebas para no depender del `.env` local.
        application.dependency_overrides[get_settings] = lambda: resolved

    register_error_handlers(application)
    application.include_router(health_router)

    # Los routers de contenido viven en la capa de presentacion de su modulo
    # (software-architecture.md seccion 3.2) y se montan aqui bajo el prefijo
    # versionado. El prefijo es configuracion, no una constante incrustada.
    for router_publico in routers_publicos:
        application.include_router(router_publico, prefix=resolved.api_v1_prefix)

    _logger.info(
        "Aplicacion inicializada",
        extra={
            "service": resolved.app_name,
            "version": __version__,
            "environment": resolved.app_env,
            "api_prefix": resolved.api_v1_prefix,
            # Enmascarada: la URL completa lleva la contrasena (requisito S-08).
            "database": resolved.database_url_safe,
        },
    )
    return application


app = create_app()
