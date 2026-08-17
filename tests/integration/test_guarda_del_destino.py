"""Regresion permanente de `CERT-AUD-002`: el harness de integracion es *fail-closed*.

Que se garantiza, exactamente
-----------------------------

**Ninguna fixture del harness oficial de integracion entrega `Settings`, `Engine`,
`Session`, conexion o `Config` de Alembic apuntando al destino de integracion
antes de haber demostrado que ese destino es seguro.**

Lo que **no** se garantiza —y no se puede— es que ningun codigo Python imaginable
sea capaz de abrir una conexion por su cuenta. Cualquiera puede llamar a
`create_engine`. La proteccion es del harness, y es ahi donde debe ser
estructural en lugar de una convencion que haya que recordar.

Hasta `Task/005.6` la proteccion vivia solo en `database_engine`, pero
`database_settings` era una fixture publica que entregaba la configuracion **sin
verificar nada**. Una prueba futura podia pedirla y construir su propio motor sin
pasar por la guarda. La suite existente no lo hacia; el harness lo permitia.

Como se comprueba
-----------------

Con subprocesos de pytest apuntados a bases descartables. Es la unica forma
honesta: la guarda usa `pytest.fail`, asi que hay que observarla desde fuera. Y
se elige a proposito un nodo de prueba que **haria DDL** —`tabla_de_pruebas`
ejecuta `CREATE TABLE`— para poder afirmar que el rechazo ocurre *antes* del
punto destructivo y no despues.

La concurrencia de esta suite sobre una misma base queda pendiente
(`CERT-AUD-009`, propietario `Task/020`): estas pruebas asumen la ejecucion
secuencial que hoy es la unica oficial.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.shared.configuration import Settings

pytestmark = pytest.mark.integration

RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parents[2]

#: Nodo que ejecuta `CREATE TABLE` a traves de `tabla_de_pruebas`. Si la guarda
#: no cortara antes, la tabla apareceria en el destino.
NODO_QUE_HARIA_DDL = (
    "tests/integration/test_database_connection.py::test_session_scope_confirma_y_el_dato_persiste"
)

#: Nodo que recorre la ruta **mas baja** que el harness expone: pide la
#: configuracion y construye el motor por su cuenta. Es exactamente el camino que
#: `CERT-AUD-002` senalo como no verificado.
NODO_DE_LA_RUTA_MAS_BAJA = (
    "tests/integration/test_guarda_del_destino.py"
    "::test_la_ruta_mas_baja_del_harness_esta_verificada"
)

TABLA_QUE_NO_DEBE_APARECER = "prueba_transaccional_005_6"

BASE_SIN_MARCA = "personal_blog_guarda_005_7_test"
BASE_SIN_SUFIJO = "personal_blog_guarda_005_7_dev"


def _apuntar_a(url_original: str, nombre_de_la_base: str) -> str:
    """Devuelve la misma URL apuntando a otra base de datos.

    `render_as_string(hide_password=False)` es obligatorio: `str(URL)` enmascara
    la contrasena —comportamiento por defecto de SQLAlchemy, pensado para no
    filtrarla en un log— y la URL resultante no sirve para conectarse.
    """
    return (
        make_url(url_original).set(database=nombre_de_la_base).render_as_string(hide_password=False)
    )


def _url_administrativa(configuracion: Settings) -> str:
    """URL con las mismas credenciales pero contra la base `postgres`.

    Crear o eliminar una base de datos exige estar conectado a otra distinta.
    """
    return _apuntar_a(configuracion.sqlalchemy_url, "postgres")


@pytest.fixture(scope="session")
def motor_administrativo(database_settings: Settings) -> Iterator[Engine]:
    """Motor contra `postgres`, para crear y destruir bases descartables.

    Depende de `database_settings`, que ya solo se entrega verificada: estas
    pruebas tampoco escapan de la guarda.
    """
    engine = create_engine(_url_administrativa(database_settings), isolation_level="AUTOCOMMIT")
    try:
        yield engine
    finally:
        engine.dispose()


def _crear_base(engine: Engine, nombre: str, comentario: str | None) -> None:
    with engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{nombre}"'))
        connection.execute(text(f'CREATE DATABASE "{nombre}"'))
        if comentario is not None:
            connection.execute(text(f"COMMENT ON DATABASE \"{nombre}\" IS '{comentario}'"))


def _eliminar_base(engine: Engine, nombre: str) -> None:
    with engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))


def _tablas_de(configuracion: Settings, nombre_de_la_base: str) -> set[str]:
    engine = create_engine(_apuntar_a(configuracion.sqlalchemy_url, nombre_de_la_base))
    try:
        with engine.connect() as connection:
            filas = connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            )
            return {fila[0] for fila in filas}
    finally:
        engine.dispose()


def _ejecutar_la_integracion_contra(
    configuracion: Settings, nombre_de_la_base: str, nodo: str = NODO_QUE_HARIA_DDL
) -> subprocess.CompletedProcess[str]:
    """Lanza el harness oficial apuntado a `nombre_de_la_base`, en subproceso."""
    url = _apuntar_a(str(configuracion.database_url), nombre_de_la_base)

    entorno = {clave: valor for clave, valor in os.environ.items() if not clave.startswith("BLOG_")}
    entorno["PYTHONPATH"] = str(RAIZ_DEL_REPOSITORIO)
    entorno["PERSONAL_BLOG_TEST_DATABASE_URL"] = url

    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-c",
            str(RAIZ_DEL_REPOSITORIO / "pyproject.toml"),
            "--rootdir",
            str(RAIZ_DEL_REPOSITORIO),
            nodo,
        ],
        cwd=str(RAIZ_DEL_REPOSITORIO),
        env=entorno,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture
def base_sin_marca(motor_administrativo: Engine) -> Iterator[str]:
    """Base descartable con el sufijo correcto y **sin** la marca obligatoria."""
    _crear_base(motor_administrativo, BASE_SIN_MARCA, comentario=None)
    try:
        yield BASE_SIN_MARCA
    finally:
        _eliminar_base(motor_administrativo, BASE_SIN_MARCA)


@pytest.fixture
def base_sin_sufijo(motor_administrativo: Engine) -> Iterator[str]:
    """Base descartable cuyo nombre **no** termina en `_test`."""
    _crear_base(motor_administrativo, BASE_SIN_SUFIJO, comentario=None)
    try:
        yield BASE_SIN_SUFIJO
    finally:
        _eliminar_base(motor_administrativo, BASE_SIN_SUFIJO)


def test_la_ruta_mas_baja_del_harness_esta_verificada(database_settings: Settings) -> None:
    """Pide la configuracion y construye el motor a mano, sin `database_engine`.

    Es el patron que `CERT-AUD-002` describio como peligroso: una prueba futura
    que pide la fixture de configuracion y se fabrica su propio motor. Que este
    aqui, escrito a proposito, es lo que permite comprobarlo desde fuera: el
    subproceso de `test_la_ruta_mas_baja_no_permite_saltarse_la_guarda` apunta
    **este** nodo a una base insegura y exige que ni siquiera llegue a ejecutarse.

    Que este nodo pase en una ejecucion normal significa que la configuracion que
    entrega el harness ya venia verificada.
    """
    engine = create_engine(database_settings.sqlalchemy_url)
    try:
        with engine.begin() as connection:
            nombre = connection.execute(text("SELECT current_database()")).scalar_one()
            assert nombre.endswith("_test")
    finally:
        engine.dispose()


def test_la_ruta_mas_baja_no_permite_saltarse_la_guarda(
    database_settings: Settings, base_sin_marca: str
) -> None:
    """`CERT-AUD-002`: la fixture de configuracion tampoco entrega un destino sin verificar.

    Antes de `Task/005.7` la guarda vivia solo en `database_engine`.
    `database_settings` era publica y no verificaba nada, asi que este subproceso
    terminaba en verde contra una base sin marca. Ahora debe fallar en la propia
    fixture, antes de que el cuerpo de la prueba llegue a ejecutarse.
    """
    resultado = _ejecutar_la_integracion_contra(
        database_settings, base_sin_marca, nodo=NODO_DE_LA_RUTA_MAS_BAJA
    )
    salida = resultado.stdout + resultado.stderr

    assert resultado.returncode != 0, (
        "la ruta mas baja del harness entrego un destino sin verificar: "
        f"una prueba futura puede saltarse la guarda\n{salida}"
    )
    assert "no lleva la marca" in salida, salida


def test_una_base_test_sin_marca_se_rechaza_antes_de_cualquier_ddl(
    database_settings: Settings, base_sin_marca: str
) -> None:
    """Barrera 2: el sufijo correcto no basta, hace falta la marca.

    Es el caso peligroso de verdad: el nombre parece bueno. La marca vive dentro
    de la base justo para que escribir bien la URL no sea suficiente.
    """
    resultado = _ejecutar_la_integracion_contra(database_settings, base_sin_marca)
    salida = resultado.stdout + resultado.stderr

    assert resultado.returncode != 0, f"el harness acepto una base sin marca\n{salida}"
    assert "no lleva la marca" in salida, salida

    assert TABLA_QUE_NO_DEBE_APARECER not in _tablas_de(database_settings, base_sin_marca), (
        "la guarda dejo llegar la ejecucion hasta el CREATE TABLE"
    )


def test_una_base_sin_el_sufijo_se_rechaza_antes_de_cualquier_ddl(
    database_settings: Settings, base_sin_sufijo: str
) -> None:
    """Barrera 1: el nombre debe terminar en `_test`."""
    resultado = _ejecutar_la_integracion_contra(database_settings, base_sin_sufijo)
    salida = resultado.stdout + resultado.stderr

    assert resultado.returncode != 0, f"el harness acepto una base sin sufijo\n{salida}"
    assert "no termina en '_test'" in salida, salida

    assert TABLA_QUE_NO_DEBE_APARECER not in _tablas_de(database_settings, base_sin_sufijo), (
        "la guarda dejo llegar la ejecucion hasta el CREATE TABLE"
    )


def test_la_base_de_desarrollo_no_puede_ser_destino_y_queda_intacta(
    database_settings: Settings, motor_administrativo: Engine
) -> None:
    """`personal_blog` no es alcanzable como destino destructivo del harness.

    No se ejecuta ningun `downgrade` contra ella: lo que se demuestra es que el
    rechazo ocurre **antes** del punto destructivo. Se comprueba ademas que su
    esquema y su revision de Alembic son identicos antes y despues.
    """
    nombre_de_desarrollo = make_url(str(database_settings.database_url)).database
    assert nombre_de_desarrollo is not None
    nombre_de_desarrollo = nombre_de_desarrollo.removesuffix("_test")

    with motor_administrativo.connect() as connection:
        existe = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :nombre"),
            {"nombre": nombre_de_desarrollo},
        ).scalar_one_or_none()

    if existe is None:
        pytest.fail(
            f"la base de desarrollo '{nombre_de_desarrollo}' no existe en este PostgreSQL: "
            "no puede comprobarse que sea inalcanzable. Levantar el entorno local "
            "(runbook local-environment.md) antes de ejecutar la integracion.",
            pytrace=False,
        )

    def _instantanea() -> tuple[set[str], str | None]:
        tablas = _tablas_de(database_settings, nombre_de_desarrollo)
        revision: str | None = None
        if "alembic_version" in tablas:
            engine = create_engine(
                _apuntar_a(database_settings.sqlalchemy_url, nombre_de_desarrollo)
            )
            try:
                with engine.connect() as connection:
                    revision = connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one_or_none()
            finally:
                engine.dispose()
        return tablas, revision

    antes = _instantanea()

    resultado = _ejecutar_la_integracion_contra(database_settings, nombre_de_desarrollo)
    salida = resultado.stdout + resultado.stderr

    assert resultado.returncode != 0, f"el harness acepto la base de desarrollo\n{salida}"
    assert "no termina en '_test'" in salida, salida

    despues = _instantanea()
    assert despues == antes, (
        f"la base de desarrollo '{nombre_de_desarrollo}' cambio: "
        f"antes={antes!r} despues={despues!r}"
    )
    assert TABLA_QUE_NO_DEBE_APARECER not in despues[0]
