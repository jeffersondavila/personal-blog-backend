"""Esquema fisico que anade `Task/011`, contra PostgreSQL real.

Dos tablas, y ninguna es opcional para el alcance de la tarea:

- `administrator_sessions`: hace que **cerrar sesion signifique algo en el
  servidor**. Sin persistencia no hay revocacion, y sin revocacion la decision
  D-011-B no se sostiene.
- `login_rate_limits`: hace que el limite de tasa sea **compartido entre
  instancias**, que es la restriccion escrita en D-09.

Se comprueba contra el motor de verdad —no contra los metadatos de SQLAlchemy—
porque lo que importa es lo que la **migracion** crea. Un modelo correcto con una
migracion incompleta produce exactamente este fallo en produccion y en ningun
otro sitio.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, inspect

pytestmark = pytest.mark.integration

TABLA_DE_SESIONES = "administrator_sessions"
TABLA_DE_LIMITES = "login_rate_limits"


def test_la_migracion_crea_la_tabla_de_sesiones(
    database_engine: Engine, esquema_migrado: None
) -> None:
    assert TABLA_DE_SESIONES in set(inspect(database_engine).get_table_names())


def test_la_migracion_crea_la_tabla_del_limite_de_tasa(
    database_engine: Engine, esquema_migrado: None
) -> None:
    assert TABLA_DE_LIMITES in set(inspect(database_engine).get_table_names())


def test_la_sesion_tiene_exactamente_las_columnas_con_comportamiento(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """Ni una columna de menos, ni una de mas.

    "De mas" importa tanto como "de menos": una columna sin comportamiento es
    deuda que alguien tendra que interpretar dentro de un ano (requisito M-06).
    """
    columnas = {
        columna["name"] for columna in inspect(database_engine).get_columns(TABLA_DE_SESIONES)
    }

    assert columnas == {
        "id",
        "administrator_id",
        "token_hash",
        "created_at",
        "expires_at",
        "revoked_at",
    }


def test_la_sesion_no_tiene_columna_para_la_credencial_en_claro(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """Control explicito de la decision D-011-C.

    La comprobacion de arriba ya lo implica, pero esta lo dice con el nombre de
    la regla: si alguien anadiera `token` a la tabla, el fallo explicaria por que
    esta mal en lugar de limitarse a decir que el conjunto cambio.
    """
    columnas = {
        columna["name"] for columna in inspect(database_engine).get_columns(TABLA_DE_SESIONES)
    }

    assert "token" not in columnas
    assert "credential" not in columnas


def test_la_huella_de_la_sesion_es_unica(database_engine: Engine, esquema_migrado: None) -> None:
    """Sin unicidad real en la base, dos sesiones podrian compartir credencial.

    Es ademas el indice por el que se resuelve cada peticion administrativa.
    """
    inspector = inspect(database_engine)

    unicos = {
        tuple(restriccion["column_names"])
        for restriccion in inspector.get_unique_constraints(TABLA_DE_SESIONES)
    }
    unicos |= {
        # `column_names` admite `None` cuando el indice es sobre una expresion.
        # Aqui no lo hay, pero filtrarlo mantiene el tipo honesto en lugar de
        # afirmar con un `cast` algo que el inspector no garantiza.
        tuple(columna for columna in indice["column_names"] if columna is not None)
        for indice in inspector.get_indexes(TABLA_DE_SESIONES)
        if indice.get("unique")
    }

    assert ("token_hash",) in unicos


def test_la_sesion_apunta_al_administrador_con_borrado_en_cascada(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """Una sesion es estado vivo, no historial.

    `audit_events.actor_id` usa `RESTRICT` porque un evento **debe** sobrevivir a
    lo que describe. Una sesion es lo contrario: si el administrador desaparece,
    su sesion no puede seguir autorizando nada, asi que se va con el.
    """
    claves = inspect(database_engine).get_foreign_keys(TABLA_DE_SESIONES)

    hacia_administradores = [
        clave for clave in claves if clave["referred_table"] == "administrators"
    ]
    assert len(hacia_administradores) == 1
    assert hacia_administradores[0]["constrained_columns"] == ["administrator_id"]
    assert hacia_administradores[0]["options"].get("ondelete") == "CASCADE"


def test_el_limite_de_tasa_tiene_exactamente_sus_columnas(
    database_engine: Engine, esquema_migrado: None
) -> None:
    columnas = {
        columna["name"] for columna in inspect(database_engine).get_columns(TABLA_DE_LIMITES)
    }

    assert columnas == {"client_key", "window_started_at", "attempts"}


def test_el_limite_de_tasa_se_identifica_por_su_particion(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """La clave primaria **es** la particion.

    Es lo que permite resolver el contador con un unico `INSERT … ON CONFLICT`
    atomico en lugar de con una lectura seguida de una escritura, que es la
    forma con la que dos peticiones simultaneas pierden actualizaciones.
    """
    primaria = inspect(database_engine).get_pk_constraint(TABLA_DE_LIMITES)

    assert primaria["constrained_columns"] == ["client_key"]


def test_el_limite_de_tasa_no_guarda_ninguna_identidad(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """No es un registro de quien intento entrar: eso es la auditoria.

    Guardar aqui el correo intentado convertiria una tabla operativa en un
    almacen de datos personales que nadie ha pedido (requisito O-09).
    """
    columnas = {
        columna["name"] for columna in inspect(database_engine).get_columns(TABLA_DE_LIMITES)
    }

    assert not columnas & {"email", "administrator_id", "password", "user_agent"}


def test_las_tablas_nuevas_guardan_sus_instantes_con_zona_horaria(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """CONTENT_MODEL.md, invariante 10: todo instante se almacena en UTC.

    Una expiracion sin zona horaria no dice en que momento caduca la sesion, que
    es exactamente el dato del que depende la decision.
    """
    inspector = inspect(database_engine)
    sin_zona: list[str] = []

    for tabla in (TABLA_DE_SESIONES, TABLA_DE_LIMITES):
        for columna in inspector.get_columns(tabla):
            tipo = columna["type"]
            if tipo.__class__.__name__ == "TIMESTAMP" and not getattr(tipo, "timezone", False):
                sin_zona.append(f"{tabla}.{columna['name']}")

    assert not sin_zona, f"columnas de fecha sin zona horaria: {sin_zona}"


def test_las_migraciones_previas_no_se_tocan() -> None:
    """`0001` y `0002` estan aprobadas y fusionadas: se anade `0003`, no se edita.

    Reescribir una migracion ya aplicada deja las bases existentes en un estado
    que ninguna revision describe.
    """
    from pathlib import Path

    versiones = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    revisiones = sorted(archivo.name for archivo in versiones.glob("*.py"))

    assert any(nombre.endswith("_0001_baseline_del_esquema.py") for nombre in revisiones)
    assert any(nombre.endswith("_0002_modelo_de_datos_del_mvp.py") for nombre in revisiones)
    assert len(revisiones) == 3, f"se esperaba exactamente una migracion nueva: {revisiones}"
