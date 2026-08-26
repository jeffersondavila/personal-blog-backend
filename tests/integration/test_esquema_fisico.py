"""Inspeccion fisica del esquema creado por la migracion (matriz H).

`test_migrations.py` demuestra el **contrato durable de M-04**: la migracion
aplica, revierte y reaplica sin dejar objetos huerfanos. Este modulo comprueba
otra cosa, complementaria: que lo que la migracion crea es **lo que el modelo
dice**, hasta el nivel de restricciones e indices.

Las dos comprobaciones sirven a proposito distinto y ninguna sustituye a la otra:
una migracion puede ser perfectamente reversible y aun asi olvidarse una
restriccion.

La comprobacion de *drift* (`compare_metadata`) es la que hace que esto no
caduque: si manana alguien anade una columna al modelo y olvida la migracion, la
suite lo dice sin que nadie tenga que actualizar una lista.
"""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect

from app.shared.database import Base

pytestmark = pytest.mark.integration

#: Tablas del MVP. Es una **guarda**, no la fuente: los metadatos mandan, y la
#: comparacion de mas abajo es la que detecta cualquier diferencia. Esta lista
#: existe para que un descubrimiento roto no deje la comprobacion vacia.
TABLAS_DEL_MVP = {
    "administrators",
    "audit_events",
    "book_review_tags",
    "book_reviews",
    "media_assets",
    "post_tags",
    "posts",
    "profile_social_links",
    "profiles",
    "project_tags",
    "projects",
    "tags",
    "video_tags",
    "videos",
}


# --- H-02 ------------------------------------------------------------------
def test_la_migracion_crea_todas_las_tablas_del_mvp(
    database_engine: Engine, esquema_migrado: None
) -> None:
    presentes = set(inspect(database_engine).get_table_names())

    ausentes = TABLAS_DEL_MVP - presentes
    assert not ausentes, f"la migracion no creo {sorted(ausentes)}"


def test_los_nueve_tipos_conceptuales_tienen_tabla(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """CONTENT_MODEL.md seccion 1: nueve tipos, ninguno sin persistencia."""
    tablas_por_tipo = {
        "Profile": "profiles",
        "Post": "posts",
        "BookReview": "book_reviews",
        "Video": "videos",
        "Project": "projects",
        "Tag": "tags",
        "MediaAsset": "media_assets",
        "Administrator": "administrators",
        "AuditEvent": "audit_events",
    }
    presentes = set(inspect(database_engine).get_table_names())

    sin_tabla = sorted(tipo for tipo, tabla in tablas_por_tipo.items() if tabla not in presentes)
    assert not sin_tabla, f"tipos conceptuales sin persistencia: {sin_tabla}"


# --- H-03 ------------------------------------------------------------------
def test_cada_slug_tiene_su_indice_unico(database_engine: Engine, esquema_migrado: None) -> None:
    """Sin unicidad real en la base, dos borradores podrian ocupar la misma URL."""
    inspector = inspect(database_engine)

    for tabla in ("posts", "book_reviews", "videos", "projects", "tags"):
        unicos = {
            tuple(restriccion["column_names"])
            for restriccion in inspector.get_unique_constraints(tabla)
        }
        assert ("slug",) in unicos, f"'{tabla}' no protege la unicidad de su slug"


def test_las_restricciones_de_comprobacion_declaradas_existen(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """Las invariantes que se delegaron a PostgreSQL, uno a uno."""
    inspector = inspect(database_engine)
    esperadas = {
        "posts": {"ck_posts_publicado_exige_fecha", "ck_posts_post_status"},
        "book_reviews": {
            "ck_book_reviews_publicado_exige_fecha",
            "ck_book_reviews_valoracion_en_escala",
            "ck_book_reviews_book_review_status",
        },
        "videos": {"ck_videos_publicado_exige_fecha", "ck_videos_duracion_positiva"},
        "projects": {
            "ck_projects_publicado_exige_fecha",
            "ck_projects_project_work_status",
        },
        "profiles": {"ck_profiles_perfil_unico"},
        "administrators": {
            "ck_administrators_administrador_unico",
            "ck_administrators_intentos_no_negativos",
        },
        "media_assets": {"ck_media_assets_tamano_positivo"},
    }

    for tabla, nombres in esperadas.items():
        presentes = {
            str(restriccion["name"]) for restriccion in inspector.get_check_constraints(tabla)
        }
        ausentes = nombres - presentes
        assert not ausentes, f"'{tabla}' no tiene {sorted(ausentes)}; hay {sorted(presentes)}"


def test_las_referencias_a_medios_restringen_el_borrado(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """Invariante 5: un medio en uso no se borra. `RESTRICT`, nunca `CASCADE`.

    Si alguna de estas claves llegara a ser `CASCADE`, borrar una imagen borraria
    el articulo que la usa. La comprobacion es explicita por eso.
    """
    inspector = inspect(database_engine)
    referencias = {
        "posts": "cover_id",
        "book_reviews": "cover_id",
        "projects": "cover_id",
        "videos": "thumbnail_id",
        "profiles": "photo_id",
    }

    for tabla, columna in referencias.items():
        claves = [
            clave
            for clave in inspector.get_foreign_keys(tabla)
            if clave["constrained_columns"] == [columna]
        ]
        assert len(claves) == 1, f"'{tabla}.{columna}' no tiene su clave foranea"
        assert claves[0]["referred_table"] == "media_assets"
        assert claves[0]["options"].get("ondelete") == "RESTRICT", (
            f"'{tabla}.{columna}' no restringe el borrado del medio"
        )


def test_las_tablas_puente_desasocian_en_cascada(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """Aqui la cascada si es correcta: borra asociaciones, nunca contenido."""
    inspector = inspect(database_engine)
    puentes = {
        "post_tags": "posts",
        "book_review_tags": "book_reviews",
        "video_tags": "videos",
        "project_tags": "projects",
    }

    for puente, tabla_de_contenido in puentes.items():
        claves = inspector.get_foreign_keys(puente)
        destinos = {clave["referred_table"] for clave in claves}
        assert destinos == {tabla_de_contenido, "tags"}
        for clave in claves:
            assert clave["options"].get("ondelete") == "CASCADE", (
                f"'{puente}' no desasocia en cascada hacia {clave['referred_table']}"
            )

        primaria = inspector.get_pk_constraint(puente)
        assert len(primaria["constrained_columns"]) == 2, (
            f"'{puente}' necesita clave primaria compuesta para rechazar duplicados"
        )


def test_los_indices_de_listado_publico_existen(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """Un indice por consulta ya prevista, no por intuicion (requisito P-08).

    El listado publico de cada tipo filtra por `status` y ordena por
    `published_at` (USER_FLOWS.md A.2, api-contracts.md seccion 6).
    """
    inspector = inspect(database_engine)

    for tabla in ("posts", "book_reviews", "videos", "projects"):
        indices = {
            str(indice["name"]): list(indice["column_names"])
            for indice in inspector.get_indexes(tabla)
        }
        nombre = f"ix_{tabla}_status_published_at"
        assert nombre in indices, f"falta '{nombre}'; hay {sorted(indices)}"
        assert indices[nombre] == ["status", "published_at"]


def test_la_comprobacion_de_uso_de_medios_esta_indexada(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """USER_FLOWS.md B.5 consulta por la columna que referencia el medio.

    PostgreSQL no indexa las claves foraneas por su cuenta: sin estos indices,
    comprobar si una imagen esta en uso recorreria cinco tablas enteras.
    """
    inspector = inspect(database_engine)
    referencias = {
        "posts": "cover_id",
        "book_reviews": "cover_id",
        "projects": "cover_id",
        "videos": "thumbnail_id",
        "profiles": "photo_id",
    }

    for tabla, columna in referencias.items():
        columnas_indexadas = [
            list(indice["column_names"]) for indice in inspector.get_indexes(tabla)
        ]
        assert [columna] in columnas_indexadas, f"'{tabla}.{columna}' no esta indexada"


def test_el_historial_de_auditoria_esta_indexado_por_sus_consultas(
    database_engine: Engine, esquema_migrado: None
) -> None:
    inspector = inspect(database_engine)
    indices = {
        str(indice["name"]): list(indice["column_names"])
        for indice in inspector.get_indexes("audit_events")
    }

    assert indices.get("ix_audit_events_occurred_at") == ["occurred_at"]
    assert indices.get("ix_audit_events_entity_type_entity_id") == ["entity_type", "entity_id"]
    assert indices.get("ix_audit_events_request_id") == ["request_id"]


def test_ninguna_columna_de_fecha_pierde_la_zona_horaria(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """CONTENT_MODEL.md, invariante 10: todo instante se almacena en UTC.

    Se recorren **todas** las tablas, no una lista: una columna de fecha nueva
    entra en la comprobacion por existir.
    """
    inspector = inspect(database_engine)
    sin_zona: list[str] = []

    for tabla in sorted(TABLAS_DEL_MVP):
        for columna in inspector.get_columns(tabla):
            tipo = columna["type"]
            if tipo.__class__.__name__ == "TIMESTAMP" and not getattr(tipo, "timezone", False):
                sin_zona.append(f"{tabla}.{columna['name']}")

    assert not sin_zona, f"columnas de fecha sin zona horaria: {sin_zona}"


# --- H-06 ------------------------------------------------------------------
def test_el_esquema_aplicado_coincide_con_el_modelo(
    database_engine: Engine, esquema_migrado: None
) -> None:
    """No hay *drift* entre `Base.metadata` y lo que hay en la base.

    Es la comprobacion que no caduca: detecta tanto una migracion que se quedo
    corta como un modelo editado sin migrar, y lo hace sin enumerar nada.
    """
    with database_engine.connect() as conexion:
        contexto = MigrationContext.configure(
            conexion,
            opts={"compare_type": True, "compare_server_default": True},
        )
        diferencias = compare_metadata(contexto, Base.metadata)

    assert diferencias == [], (
        "el esquema aplicado y el modelo no coinciden. Falta una migracion, o la "
        f"migracion no refleja el modelo. Diferencias: {diferencias}"
    )
