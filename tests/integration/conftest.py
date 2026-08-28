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

Garantia *fail-closed* del harness (vigente desde `Task/005.7`)
---------------------------------------------------------------

**Ninguna fixture de este harness entrega `Settings`, `Engine`, `Session`,
conexion o `Config` de Alembic para el destino de integracion sin que la guarda
haya verificado antes que ese destino es seguro.** Todas se derivan de
`destino_de_integracion_verificado`, que verifica antes de hacer `yield`.

Lo que **no** se afirma —seria falso— es que resulte imposible que codigo Python
cualquiera abra una conexion a otra base: `create_engine` esta al alcance de
quien lo escriba. La garantia es sobre el harness oficial, que es donde una
prueba futura se equivocaria por accidente.

Comprobaciones: `tests/integration/test_guarda_del_destino.py` (comportamiento) y
`tests/test_grafo_de_fixtures_de_integracion.py` (estructura del grafo).

Provisionar la base de pruebas:
`personal-blog-infra/docs/runbooks/local-environment.md` seccion 9.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.shared.configuration import Settings, build_settings, get_settings
from app.shared.database.session import create_database_engine

RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parents[2]

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
def destino_de_integracion_verificado() -> Iterator[tuple[Settings, Engine]]:
    """Resuelve el destino de integracion y **lo verifica antes de entregarlo**.

    Es el unico punto del harness que convierte
    `PERSONAL_BLOG_TEST_DATABASE_URL` en configuracion y motor. Todo lo demas
    —`database_settings`, `database_engine`, `configured_process`,
    `alembic_config`, `tabla_de_pruebas`— se deriva de aqui.

    Por que un unico resolutor (`CERT-AUD-002`)
    -------------------------------------------

    Hasta `Task/005.6` la guarda vivia en `database_engine`, pero
    `database_settings` era una fixture publica que devolvia la configuracion
    **sin verificar nada**. La suite existente no la usaba mal; el harness
    permitia usarla mal. Una prueba futura podia pedirla, construirse su propio
    motor con `create_database_engine` y ejecutar DDL contra un destino que nadie
    habia comprobado. Se reprodujo contra una base `_test` sin marca.

    Concentrar la resolucion en una sola fixture que verifica **antes** de hacer
    `yield` elimina la ruta insegura en lugar de confiar en que nadie la tome. No
    quedan dos caminos, uno seguro y otro no, entre los que haya que acordarse de
    elegir. `tests/test_grafo_de_fixtures_de_integracion.py` comprueba que sigue
    siendo asi.

    Alcance de la garantia: **las fixtures oficiales del harness**. Cualquiera
    puede llamar a `create_engine` por su cuenta desde codigo Python arbitrario,
    y eso ni se impide ni se pretende impedir.

    Unico `skip` admitido en toda la integracion: la variable no esta definida,
    es decir, no hay entorno de integracion que ejecutar.
    """
    url = _url_de_pruebas()
    if not url:
        pytest.skip(f"{TEST_DATABASE_URL_VARIABLE} no definida: se omite la integracion")

    configuracion = build_settings(
        app_env="test", database_url=url, log_format="text", _env_file=None
    )
    engine = create_database_engine(configuracion)
    try:
        # Antes del `yield`: nada sale de aqui sin haber pasado la guarda.
        _verificar_que_el_destino_es_de_pruebas(engine)
        yield configuracion, engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def database_settings(destino_de_integracion_verificado: tuple[Settings, Engine]) -> Settings:
    """Configuracion apuntando a la base de datos real de pruebas, ya verificada."""
    configuracion, _ = destino_de_integracion_verificado
    return configuracion


@pytest.fixture(scope="session")
def database_engine(destino_de_integracion_verificado: tuple[Settings, Engine]) -> Engine:
    """Motor conectado a la base de pruebas, **ya verificada como segura**."""
    _, engine = destino_de_integracion_verificado
    return engine


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


# ---------------------------------------------------------------------------
# Esquema real: Alembic y sesion transaccional (anadido en `Task/008`)
# ---------------------------------------------------------------------------
#
# Todo lo de aqui deriva de `destino_de_integracion_verificado`, igual que el
# resto del harness: `tests/test_grafo_de_fixtures_de_integracion.py` lo exige y
# lo comprueba recorriendo el grafo.


@contextmanager
def _proceso_apuntando_a(configuracion: Settings) -> Iterator[None]:
    """Deja `get_settings()` resolviendo hacia la base de pruebas verificada.

    Lo necesitan `alembic/env.py` y cualquier funcion que resuelva la
    configuracion por si misma. Se restaura siempre: la fixture `autouse`
    `_isolated_environment` repone la URL ficticia antes de cada prueba, y este
    contexto no debe dejar rastro fuera de su bloque.
    """
    anterior = os.environ.get("BLOG_DATABASE_URL")
    os.environ["BLOG_DATABASE_URL"] = str(configuracion.database_url)
    get_settings.cache_clear()
    try:
        yield
    finally:
        if anterior is None:
            os.environ.pop("BLOG_DATABASE_URL", None)
        else:
            os.environ["BLOG_DATABASE_URL"] = anterior
        get_settings.cache_clear()


def _construir_configuracion_de_alembic() -> Config:
    configuracion = Config(str(RAIZ_DEL_REPOSITORIO / "alembic.ini"))
    configuracion.set_main_option("script_location", str(RAIZ_DEL_REPOSITORIO / "alembic"))
    return configuracion


@pytest.fixture
def alembic_config(database_settings: Settings, database_engine: Engine) -> Iterator[Config]:
    """Configuracion de Alembic apuntando a la base de datos de pruebas.

    Depende de `database_engine` **a proposito**, aunque no lo use: es la cadena
    que pasa por la guarda *fail-closed*. Asi ninguna prueba futura puede obtener
    un `Config` capaz de hacer `downgrade` sin haber verificado antes el destino.
    La proteccion es estructural, no una convencion que haya que recordar.

    Vivia en `tests/integration/test_migrations.py` hasta `Task/008`; se movio
    aqui para que las pruebas de esquema pudieran reutilizar la misma maquinaria
    en lugar de duplicarla.
    """
    with _proceso_apuntando_a(database_settings):
        yield _construir_configuracion_de_alembic()


@pytest.fixture(scope="session")
def esquema_migrado(destino_de_integracion_verificado: tuple[Settings, Engine]) -> None:
    """Garantiza que la base de pruebas esta en `head` antes de usar el esquema.

    Las pruebas de esquema no pueden depender de que otro modulo haya ejecutado
    las migraciones antes: pytest no garantiza ese orden y una base recien
    creada no tiene ninguna tabla. Se ejecuta una sola vez por sesion.
    """
    configuracion, _ = destino_de_integracion_verificado
    with _proceso_apuntando_a(configuracion):
        command.upgrade(_construir_configuracion_de_alembic(), "head")


@pytest.fixture
def sesion_de_pruebas(database_engine: Engine, esquema_migrado: None) -> Iterator[Session]:
    """Sesion aislada: todo lo que escriba la prueba se revierte al terminar.

    La sesion se ata a una conexion con una transaccion **externa** abierta, y el
    `rollback` final la deshace entera. Ninguna prueba deja filas para la
    siguiente y ninguna necesita borrar lo que creo, ni siquiera si falla a la
    mitad.

    Es tambien la razon de que las pruebas de restricciones puedan provocar
    `IntegrityError` sin ensuciar nada: la transaccion abortada se revierte
    igual.

    `join_transaction_mode="create_savepoint"` no es un detalle: sin el, la
    sesion se **adueña** de la transaccion externa y al cerrarse la deja
    desasociada, de modo que el `rollback` final emite
    `SAWarning: transaction already deassociated from connection`. El proyecto no
    tolera advertencias sin documentar y ejecuta la suite con `-W error`. Con el
    modo de punto de guardado, la sesion trabaja dentro de un `SAVEPOINT` y la
    transaccion externa sigue siendo de esta fixture de principio a fin.

    **Lo que esta fixture no puede observar:** en PostgreSQL, `now()` devuelve el
    instante de **inicio de la transaccion**, no la hora de reloj. Todo lo que
    ocurra aqui comparte marca temporal. Una prueba sobre el avance de
    `updated_at` entre modificaciones necesita transacciones distintas, y por eso
    se escribe aparte.
    """
    conexion = database_engine.connect()
    transaccion = conexion.begin()
    sesion = Session(
        bind=conexion,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield sesion
    finally:
        sesion.close()
        transaccion.rollback()
        conexion.close()


# ---------------------------------------------------------------------------
# API publica sobre PostgreSQL real (anadido en `Task/009`)
# ---------------------------------------------------------------------------


class _ClienteQueSiempreConsulta(TestClient):
    """`TestClient` que invalida el estado en memoria antes de cada peticion.

    Sin esto, las pruebas de integracion medirian menos de lo que dicen. La
    prueba y la aplicacion comparten la sesion, asi que los objetos que la
    prueba acaba de crear siguen en el *identity map* con sus colecciones ya
    pobladas. Una consulta posterior devuelve **esos mismos objetos** y las
    relaciones no se cargan: el `order_by` de una relacion no se aplica, la
    estrategia de carga explicita no se ejercita, y una regresion de N+1 pasaria
    inadvertida porque no habria ninguna consulta que contar.

    En produccion cada peticion abre su propia sesion y **siempre** lee de
    PostgreSQL. Expirar antes de cada peticion reproduce esa situacion, que es
    la que las pruebas deben comprobar.

    Se detecto al escribir la prueba del orden de los enlaces sociales: pasaba
    por el orden de insercion, no por el orden que aplica la base.
    """

    def __init__(self, *args: object, sesion: Session, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._sesion = sesion

    def request(self, *args: object, **kwargs: object) -> Any:
        """Expira el estado en memoria y delega en el cliente real."""
        self._sesion.expire_all()
        return super().request(*args, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def cliente_de_la_api(
    database_settings: Settings, sesion_de_pruebas: Session
) -> Iterator[TestClient]:
    """Cliente HTTP cuya sesion es la transaccion aislada de la prueba.

    Es lo que permite ejercitar la API **de extremo a extremo contra PostgreSQL
    real** —que es donde se demuestra que un borrador no sale— sin que una
    prueba deje filas para la siguiente: cuanto escriba la prueba se revierte
    con la transaccion externa de `sesion_de_pruebas`.

    Se sustituye `get_session` y no la configuracion del proceso porque la
    dependencia real abre su **propia** sesion con `session_scope`, que confirma
    al salir. Con ella, cada peticion escaparia del aislamiento y el contenido
    de una prueba seria visible para las siguientes.

    La cadena hasta la guarda *fail-closed* se mantiene intacta: esta fixture
    depende de `database_settings` y de `sesion_de_pruebas`, y ambas se derivan
    de `destino_de_integracion_verificado`.
    `tests/test_grafo_de_fixtures_de_integracion.py` lo comprueba recorriendo el
    grafo, asi que la garantia no depende de que nadie lo olvide.
    """
    from app.main import create_app
    from app.shared.database import get_session

    aplicacion = create_app(settings=database_settings)
    aplicacion.dependency_overrides[get_session] = lambda: sesion_de_pruebas

    with _ClienteQueSiempreConsulta(
        aplicacion, raise_server_exceptions=False, sesion=sesion_de_pruebas
    ) as cliente:
        yield cliente
