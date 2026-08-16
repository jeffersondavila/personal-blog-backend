"""Configuracion de las pruebas de integracion contra PostgreSQL real.

Estas pruebas son **destructivas**: el ciclo de migraciones ejecuta
`alembic downgrade base`, que revierte el esquema entero. Por eso el destino
nunca puede ser la base de datos cotidiana de desarrollo.

Politica vigente desde `Task/005.6` — dos casos, y solo dos:

| Caso | Situacion | Resultado |
| --- | --- | --- |
| 1 | `PERSONAL_BLOG_TEST_DATABASE_URL` **no definida** | `SKIP` con motivo |
| 2 | Definida | PostgreSQL **debe** funcionar: cualquier fallo es `FAIL` |

En el caso 2 **nada se convierte en `skip`**: ni credenciales incorrectas, ni
host caido, ni driver ausente, ni una regresion del motor. Un `skip` ahi
ocultaria exactamente el defecto que la integracion existe para detectar.

La URL no lleva el prefijo `BLOG_` a proposito: las pruebas limpian ese prefijo
del entorno para aislarse de la configuracion de la maquina.

Provisionar la base de pruebas:
`personal-blog-infra/docs/runbooks/local-environment.md` seccion 9.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from app.shared.configuration import Settings, build_settings
from app.shared.database.session import create_database_engine

TEST_DATABASE_URL_VARIABLE = "PERSONAL_BLOG_TEST_DATABASE_URL"

#: El nombre de la base debe terminar asi. Primera barrera, barata y legible.
SUFIJO_OBLIGATORIO = "_test"

#: Marca que la base de datos debe llevar en su comentario de PostgreSQL.
#: Segunda barrera, y la que de verdad importa: **vive dentro de la base**, no
#: en la URL. Escribir bien una URL no la fabrica; apuntar por error a la base
#: de desarrollo no la encuentra. Se coloca al provisionar la base, con
#: `COMMENT ON DATABASE ... IS ...` (ver runbook).
MARCA_OBLIGATORIA = "personal-blog:test-database"

#: Consulta el comentario de la base actual. `shobj_description` es la funcion
#: de catalogo para objetos compartidos, que es lo que es una base de datos.
_CONSULTA_DE_LA_MARCA = text(
    "SELECT shobj_description(oid, 'pg_database') "
    "FROM pg_database WHERE datname = current_database()"
)


def _url_de_pruebas() -> str | None:
    return os.environ.get(TEST_DATABASE_URL_VARIABLE)


def _verificar_que_el_destino_es_de_pruebas(engine: Engine) -> None:
    """Guarda *fail-closed* previa a cualquier operacion destructiva.

    No comprueba que el destino sea peligroso: exige **demostrar** que es
    seguro. Si algo no puede comprobarse —la conexion falla, no hay marca, el
    nombre no encaja— la respuesta es `FAIL`, nunca `skip` y nunca continuar.
    """
    try:
        with engine.connect() as connection:
            nombre = connection.execute(text("SELECT current_database()")).scalar_one()
            marca = connection.execute(_CONSULTA_DE_LA_MARCA).scalar_one_or_none()
    # `Exception` a proposito y sin excepciones: credenciales, host, driver o
    # una regresion del motor son todos fallos reales del entorno de
    # integracion, y ninguno puede degradarse a `skip`.
    except Exception as error:
        pytest.fail(
            f"{TEST_DATABASE_URL_VARIABLE} esta definida pero PostgreSQL no responde: "
            f"{type(error).__name__}: {error}. "
            "Con la variable definida, la integracion NO se omite: se exige que funcione.",
            pytrace=False,
        )

    if not nombre.endswith(SUFIJO_OBLIGATORIO):
        pytest.fail(
            f"Destino rechazado: la base '{nombre}' no termina en '{SUFIJO_OBLIGATORIO}'. "
            "Las pruebas de integracion ejecutan 'alembic downgrade base' y no pueden "
            "apuntar a una base que no sea inequivocamente de pruebas.",
            pytrace=False,
        )

    if marca is None or MARCA_OBLIGATORIA not in marca:
        pytest.fail(
            f"Destino rechazado: la base '{nombre}' no lleva la marca '{MARCA_OBLIGATORIA}' "
            "en su comentario de PostgreSQL. La marca vive DENTRO de la base a proposito: "
            "asi la guarda no depende de que la URL este bien escrita. "
            "Provisionar segun el runbook del entorno local, seccion 9.",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def database_settings() -> Settings:
    """Configuracion apuntando a la base de datos real de pruebas.

    Unico `skip` admitido en toda la integracion: la variable no esta definida,
    es decir, no hay entorno de integracion que ejecutar.
    """
    url = _url_de_pruebas()
    if not url:
        pytest.skip(f"{TEST_DATABASE_URL_VARIABLE} no definida: se omite la integracion")
    return build_settings(app_env="test", database_url=url, log_format="text", _env_file=None)


@pytest.fixture(scope="session")
def database_engine(database_settings: Settings) -> Iterator[Engine]:
    """Motor conectado a la base de pruebas, **ya verificada como segura**.

    Ninguna prueba de integracion recibe un motor sin que la guarda haya pasado:
    es la fixture por la que todas entran.
    """
    engine = create_database_engine(database_settings)
    try:
        _verificar_que_el_destino_es_de_pruebas(engine)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def configured_process(database_settings: Settings, database_engine: Engine) -> Iterator[None]:
    """Deja el proceso configurado contra la base de datos real.

    Lo necesitan las funciones que resuelven la configuracion por si mismas
    —`session_scope`, `get_session`— en lugar de recibirla como argumento.
    """
    from app.shared.configuration import get_settings
    from app.shared.database import dispose_engine

    anterior = os.environ.get("BLOG_DATABASE_URL")
    os.environ["BLOG_DATABASE_URL"] = str(database_settings.database_url)
    get_settings.cache_clear()
    dispose_engine()
    try:
        yield
    finally:
        dispose_engine()
        if anterior is None:
            os.environ.pop("BLOG_DATABASE_URL", None)
        else:
            os.environ["BLOG_DATABASE_URL"] = anterior
        get_settings.cache_clear()


@pytest.fixture
def tabla_de_pruebas(database_engine: Engine) -> Iterator[str]:
    """Tabla real y descartable para comprobar commit y rollback.

    No es `TEMPORARY`: una tabla temporal de PostgreSQL solo existe dentro de su
    propia sesion, y estas pruebas necesitan justo lo contrario —que **otra**
    sesion vea, o no vea, el dato—.

    No forma parte de las migraciones de negocio: se crea y se destruye aqui, y
    el `DROP` esta en un `finally` para que sobreviva a un fallo de la prueba.
    """
    nombre = "prueba_transaccional_005_6"
    with database_engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {nombre}"))
        connection.execute(text(f"CREATE TABLE {nombre} (id integer PRIMARY KEY, nota text)"))
    try:
        yield nombre
    finally:
        with database_engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {nombre}"))
