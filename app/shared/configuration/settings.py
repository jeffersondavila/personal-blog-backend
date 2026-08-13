"""Configuracion del proceso, leida de variables de entorno y validada al arrancar.

Reglas vigentes del proyecto:

- Toda la configuracion proviene de **variables de entorno** (requisito T-01).
  En local las aporta un archivo `.env`; en la nube, SSM Parameter Store. El
  codigo no distingue el origen.
- La validacion es **fail-fast**: si falta una variable obligatoria o su valor
  no es valido, el proceso no arranca (software-architecture.md, seccion 3.8).
- **Nunca se imprime una credencial.** `database_url` esta excluida de `repr`
  y solo se expone enmascarada mediante `database_url_safe` (requisito S-08).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Final, Literal, Self

from pydantic import Field, PostgresDsn, model_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Captura `esquema://usuario` y la contrasena que le sigue, para enmascararla.
_PASSWORD_IN_URL: Final[re.Pattern[str]] = re.compile(r"(://[^:/?#@]+):[^@/?#]+@")

Environment = Literal["local", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "text"]


class ConfigurationError(RuntimeError):
    """La configuracion del proceso es invalida o esta incompleta.

    Se lanza al arrancar. Su mensaje nombra las variables afectadas pero
    **nunca** incluye sus valores, para no filtrar credenciales en los logs.
    """


class Settings(BaseSettings):
    """Configuracion validada del backend.

    Todos los campos se leen de variables de entorno con el prefijo declarado
    en `model_config`. `extra="forbid"` convierte una variable mal escrita en
    un fallo de arranque en lugar de en un valor ignorado en silencio.
    """

    model_config = SettingsConfigDict(
        env_prefix="BLOG_",
        env_file=".env",
        # `utf-8-sig` y no `utf-8`: en Windows es habitual que un editor o un
        # `Set-Content` guarden el `.env` con BOM, y con `utf-8` ese BOM se
        # pega al nombre de la primera variable, que pasa a ser desconocida.
        # Con `extra="forbid"` eso rompe el arranque con un error desconcertante.
        # `utf-8-sig` lee correctamente el archivo lleve BOM o no.
        env_file_encoding="utf-8-sig",
        extra="forbid",
        frozen=True,
        case_sensitive=False,
    )

    # --- Aplicacion --------------------------------------------------------
    app_name: str = Field(
        default="personal-blog-backend",
        min_length=1,
        max_length=64,
        description="Nombre del servicio, usado en OpenAPI y en los logs.",
    )
    app_env: Environment = Field(
        default="local",
        description="Entorno de ejecucion. No cambia el codigo, solo la configuracion.",
    )
    app_debug: bool = Field(
        default=False,
        description="Modo depuracion. Deshabilitado por defecto y prohibido en produccion.",
    )
    api_v1_prefix: str = Field(
        default="/api/v1",
        pattern=r"^/[a-z0-9\-/]*[a-z0-9]$",
        description="Prefijo de la API versionada (api-contracts.md, seccion 1).",
    )

    # --- Observabilidad ----------------------------------------------------
    log_level: LogLevel = Field(default="INFO")
    log_format: LogFormat = Field(
        default="json",
        description="`json` para entornos desatendidos; `text` solo para depuracion local.",
    )

    # --- Base de datos -----------------------------------------------------
    # `repr=False`: la URL lleva la contrasena. No debe aparecer en trazas,
    # mensajes de error ni logs (requisito S-08).
    database_url: Annotated[PostgresDsn, Field(repr=False)] = Field(
        description="URL de conexion a PostgreSQL. Obligatoria: sin ella el proceso no arranca.",
    )
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_pool_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60)
    database_connect_timeout_seconds: int = Field(default=10, ge=1, le=60)
    database_echo: bool = Field(
        default=False,
        description="Registro de SQL. Siempre False fuera de una depuracion puntual: "
        "las sentencias pueden contener datos sensibles.",
    )

    @model_validator(mode="after")
    def _reject_unsafe_production_settings(self) -> Self:
        """Impide combinaciones peligrosas de configuracion."""
        if self.app_env == "production":
            if self.app_debug:
                raise ValueError("BLOG_APP_DEBUG no puede estar activo con BLOG_APP_ENV=production")
            if self.database_echo:
                raise ValueError(
                    "BLOG_DATABASE_ECHO no puede estar activo con BLOG_APP_ENV=production"
                )
        return self

    @property
    def database_url_safe(self) -> str:
        """URL de la base de datos con la contrasena enmascarada.

        Es la unica forma admitida de mostrar la conexion en un log, un mensaje
        de arranque o un reporte.
        """
        return _PASSWORD_IN_URL.sub(r"\1:***@", str(self.database_url), count=1)

    @property
    def sqlalchemy_url(self) -> str:
        """URL de conexion en el dialecto que usa SQLAlchemy.

        Fija el driver `psycopg` (psycopg 3) cuando la URL no declara uno, para
        que la eleccion no dependa de lo que haya instalado en el entorno.
        """
        url = str(self.database_url)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


def build_settings(**overrides: object) -> Settings:
    """Construye la configuracion y traduce el fallo de validacion a `ConfigurationError`.

    Pydantic produce un mensaje que puede incluir los valores recibidos. Aqui
    se reduce a la lista de campos afectados y su motivo, sin valores.
    """
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except PydanticValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '<raiz>'}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigurationError(f"Configuracion invalida o incompleta -> {problems}") from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devuelve la configuracion del proceso.

    Se memoriza porque la configuracion es inmutable durante la vida del
    proceso: no es estado de negocio en memoria, sino la lectura de un entorno
    que no cambia (compatible con la restriccion de ejecucion sin estado).
    """
    return build_settings()
