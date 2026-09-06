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
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Captura `esquema://usuario` y la contrasena que le sigue, para enmascararla.
_PASSWORD_IN_URL: Final[re.Pattern[str]] = re.compile(r"(://[^:/?#@]+):[^@/?#]+@")

Environment = Literal["local", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "text"]
#: Implementacion de `ObjectStorage` que usa el proceso. Tipo cerrado a
#: proposito: una cadena libre convertiria una errata en un fallo en la primera
#: subida en lugar de en un fallo de arranque.
StorageProvider = Literal["minio", "s3"]


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

    # --- Sitio publico -----------------------------------------------------
    # Anadido por `Task/016`. Obligatoria y sin valor por defecto, como
    # `database_url` y `storage_bucket`: el sitemap enumera URL del SITIO, y un
    # origen inventado produciria un sitemap que apunta a otro sitio.
    #
    # No se deduce de la peticion: `Host` lo escribe el cliente y, detras de un
    # proxy o de API Gateway, nombra el API y no el sitio (**D-15**: el sitio
    # vive en el dominio raiz y el API en un subdominio).
    #
    # No fija ningun dominio: el dominio concreto es **D-07**, todavia abierta.
    public_site_base_url: str = Field(
        description="Origen publico del sitio, sin barra final. Obligatoria: la usa el "
        "sitemap (requisito E-05) para emitir URL absolutas del sitio.",
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

    # --- Almacenamiento de objetos (`Task/010`) ----------------------------
    #
    # La aplicacion depende de la **interfaz** `ObjectStorage`; estas variables
    # son lo unico que decide que implementacion la satisface, tal como exige
    # software-architecture.md seccion 3.7: cambiar de MinIO a S3 es cambiar
    # configuracion, no codigo.
    storage_provider: StorageProvider = Field(
        default="minio",
        description="Implementacion de ObjectStorage: `minio` en local, `s3` en produccion.",
    )
    storage_bucket: str = Field(
        min_length=3,
        max_length=63,
        description="Bucket de los medios. Obligatorio: no existe un valor por defecto "
        "seguro, y equivocarlo significaria escribir donde no toca.",
    )
    storage_region: str = Field(
        default="us-east-1",
        min_length=1,
        description="Region declarada al firmar. MinIO acepta cualquiera; en S3 determina "
        "ademas el endpoint cuando no se declara uno.",
    )
    storage_endpoint_url: str | None = Field(
        default=None,
        description="Endpoint **operativo**: el que usa el backend para leer y escribir. "
        "Obligatorio con `minio`; con `s3` se omite en produccion para que el SDK "
        "resuelva el de AWS.",
    )
    storage_access_endpoint_url: str | None = Field(
        default=None,
        description="Endpoint **de acceso**: el anfitrion que aparece en el enlace "
        "temporal de una imagen. Solo hace falta cuando el consumidor del enlace no ve "
        "el mismo anfitrion que el backend, que es el caso dentro de Docker Compose. "
        "Omitido, se firma contra el operativo.",
    )
    # `repr=False` en las dos credenciales, y `SecretStr` ademas en el secreto:
    # la configuracion se registra al arrancar (requisito S-08).
    storage_access_key: Annotated[str | None, Field(repr=False)] = Field(
        default=None,
        description="Clave de acceso. Ausente en produccion, donde se usa el rol de "
        "ejecucion de la Lambda (requisito S-01).",
    )
    storage_secret_key: Annotated[SecretStr | None, Field(repr=False)] = Field(
        default=None,
        description="Secreto de acceso. Nunca se imprime.",
    )
    storage_access_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=604800,
        description="Validez del enlace temporal de un medio. La politica de expiracion "
        "de produccion la fija `Task/030` (D-08); aqui es configuracion, no una "
        "constante enterrada en el adaptador.",
    )

    # --- Autenticacion administrativa (`Task/011`) -------------------------
    #
    # La decision D-011-B —sesion opaca en el servidor con cookie `HttpOnly`—
    # **no necesita ningun secreto de firma**, y por eso no hay ninguno aqui.
    # Reservar un `JWT_SECRET` "por si acaso" no es prudencia: es un secreto que
    # alguien tendria que custodiar, rotar y explicar sin que nada lo use.
    auth_session_ttl_seconds: int = Field(
        default=43200,
        ge=60,
        le=604800,
        description="Duracion ABSOLUTA de la sesion administrativa, en segundos. "
        "12 h por defecto. No hay renovacion deslizante ni caducidad por inactividad.",
    )
    auth_cookie_secure: bool = Field(
        default=True,
        description="Marca `Secure` de la cookie. Solo puede desactivarse fuera de "
        "produccion, donde el entorno local sirve por HTTP.",
    )
    auth_max_failed_attempts: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Fallos consecutivos que activan el bloqueo temporal de la cuenta.",
    )
    auth_lockout_seconds: int = Field(
        default=900,
        ge=1,
        le=86400,
        description="Duracion del bloqueo temporal. Nunca es permanente: hay un solo "
        "administrador y dejarlo fuera para siempre seria peor que el ataque.",
    )
    auth_rate_limit_max_attempts: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Intentos de acceso admitidos por ventana y por origen.",
    )
    auth_rate_limit_window_seconds: int = Field(
        default=300,
        ge=1,
        le=86400,
        description="Ventana fija del limite de tasa del acceso, en segundos.",
    )
    admin_allowed_origins: str = Field(
        default="",
        description="Origenes del panel administrativo, separados por comas. Nunca `*`. "
        "Vacio significa que ninguna peticion con `Origin` puede cambiar estado: es "
        "fail-closed a proposito, porque no existe un origen por defecto seguro.",
    )
    trusted_proxy_hop_count: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Numero de proxies de confianza delante del backend. Con 0 se IGNORA "
        "`X-Forwarded-For` por completo: es una cabecera que cualquier cliente puede "
        "escribir, y creersela permitiria falsificar una IP por intento.",
    )

    @model_validator(mode="after")
    def _validate_admin_origins(self) -> Self:
        """Comprueba que cada origen declarado es realmente un origen.

        Un origen es **esquema + anfitrion + puerto**: sin ruta, sin consulta y
        sin barra final. Comparar la cabecera `Origin` recibida con una cadena
        que no tiene esa forma no falla de manera ruidosa —falla **rechazando
        siempre**—, y eso se descubre el dia que el panel deja de entrar.

        El comodin se rechaza sin excepciones (requisito S-04): junto a una
        cookie de sesion es la combinacion que ningun navegador deberia tener que
        rechazar en nuestro lugar.
        """
        for origen in self.origenes_administrativos_permitidos:
            if origen == "*":
                raise ValueError(
                    "BLOG_ADMIN_ALLOWED_ORIGINS no admite '*': un origen comodin con "
                    "credenciales esta prohibido (requisito S-04)"
                )
            partes = urlsplit(origen)
            if (
                partes.scheme not in {"http", "https"}
                or not partes.hostname
                or partes.path
                or partes.query
                or partes.fragment
                or partes.username
            ):
                raise ValueError(
                    "BLOG_ADMIN_ALLOWED_ORIGINS debe listar origenes con la forma "
                    "'esquema://anfitrion[:puerto]', sin ruta ni barra final; "
                    "valor rechazado en la posicion correspondiente"
                )
        return self

    @property
    def origenes_administrativos_permitidos(self) -> tuple[str, ...]:
        """Origenes declarados, ya separados y sin entradas vacias."""
        return tuple(
            fragmento.strip()
            for fragmento in self.admin_allowed_origins.split(",")
            if fragmento.strip()
        )

    @property
    def auth_cookie_path(self) -> str:
        """`Path` de la cookie de sesion: el prefijo administrativo.

        Se deriva del prefijo configurado en lugar de escribirse a mano para que
        no puedan separarse. Es higiene de exposicion —la cookie no viaja a los
        endpoints publicos—, **no** una frontera de seguridad: quien la aplica es
        el navegador.
        """
        return f"{self.api_v1_prefix}/admin"

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
            if self.storage_provider == "minio":
                raise ValueError(
                    "BLOG_STORAGE_PROVIDER=minio no es valido con BLOG_APP_ENV=production: "
                    "MinIO es el almacenamiento del entorno local"
                )
            if not self.auth_cookie_secure:
                raise ValueError(
                    "BLOG_AUTH_COOKIE_SECURE no puede ser false con "
                    "BLOG_APP_ENV=production: la cookie de sesion viajaria por Internet "
                    "sin exigir HTTPS"
                )
        return self

    @model_validator(mode="after")
    def _validate_access_endpoint(self) -> Self:
        """Comprueba la forma del endpoint de acceso, si se declara.

        Fail-fast (requisito T-01): un valor invalido debe romper el arranque y
        no el primer enlace que se emita, que es cuando lo veria un visitante.

        **No** se exige: sin endpoint de acceso se firma contra el operativo,
        que es lo correcto cuando los dos coinciden —y es el caso de produccion,
        donde el endpoint lo resuelve el SDK—.
        """
        if self.storage_access_endpoint_url is None:
            return self
        partes = urlsplit(self.storage_access_endpoint_url.strip())
        if partes.scheme not in {"http", "https"} or not partes.hostname:
            raise ValueError(
                "BLOG_STORAGE_ACCESS_ENDPOINT_URL debe ser una URL HTTP explicita, "
                "por ejemplo 'http://localhost:9000'"
            )
        return self

    @model_validator(mode="after")
    def _normalize_public_site_base_url(self) -> Self:
        """Valida y normaliza el origen del sitio.

        *Fail-closed* (requisito T-01): un valor ausente o no utilizable rompe
        el arranque, no la primera peticion al sitemap. Un sitemap que apunta a
        un sitio equivocado es peor que no publicar sitemap.

        Se normaliza a una sola forma canonica —sin barra final— para que quien
        construya una URL pueda concatenar la ruta sin comprobar el separador.
        Se usa `object.__setattr__` porque el modelo es `frozen`.
        """
        recortado = self.public_site_base_url.strip()
        partes = urlsplit(recortado)
        if partes.scheme not in {"http", "https"} or not partes.hostname:
            raise ValueError(
                "BLOG_PUBLIC_SITE_BASE_URL debe ser una URL absoluta http o https, "
                "por ejemplo 'http://localhost:8081'"
            )
        object.__setattr__(self, "public_site_base_url", recortado.rstrip("/"))
        return self

    @model_validator(mode="after")
    def _require_local_storage_credentials(self) -> Self:
        """Exige lo que `minio` no puede resolver por su cuenta.

        La obligatoriedad depende del proveedor y por eso no se expresa como
        campo obligatorio: `s3` **si** puede prescindir de claves explicitas,
        porque en produccion las aporta el rol de ejecucion. Exigirselas a los
        dos empujaria a poner una credencial estatica donde no hace falta.
        """
        if self.storage_provider != "minio":
            return self
        faltantes = [
            nombre
            for nombre, valor in (
                ("endpoint_url", self.storage_endpoint_url),
                ("access_key", self.storage_access_key),
                ("secret_key", self.storage_secret_key),
            )
            if valor is None
        ]
        if faltantes:
            raise ValueError(
                "BLOG_STORAGE_PROVIDER=minio exige "
                + ", ".join(f"BLOG_STORAGE_{nombre.upper()}" for nombre in faltantes)
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
