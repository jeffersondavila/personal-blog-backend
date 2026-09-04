"""Dos primeros usos simultáneos de la misma imagen (D-012-Y y D-012-Z).

Por qué esta prueba existe
--------------------------

`_asignar_texto_alternativo` es una **lectura-decisión-escritura** sobre
`media_assets.alt_text`:

    actual = repositorio.texto_alternativo_del_medio(id)
    nuevo  = texto_a_escribir(actual=actual, propuesto=...)
    if nuevo: repositorio.escribir_texto_alternativo(id, nuevo)

El proyecto trabaja en **READ COMMITTED** —el valor por defecto de PostgreSQL,
que no se sobrescribe en ningún sitio—. Sin cerrojo, dos transacciones pueden
leer las dos `NULL`, concluir las dos que son el primer uso y escribir las dos:
la segunda espera al cerrojo de fila del `UPDATE`, y en cuanto la primera
confirma, **la pisa**. Las dos terminan con éxito y gana la última.

Eso haría **falso a D-012-Z** bajo concurrencia: el texto de un `MediaAsset` que
ya tenía uno acabaría sobrescrito, en silencio, que es justamente lo que la
decisión existe para impedir.

Va contra **dos conexiones reales**, con datos confirmados: el cerrojo lo da
PostgreSQL, y con una sola conexión no hay nada que serializar. Es el mismo
patrón con el que se demostró la publicación simultánea.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditEvent
from app.modules.audit.infrastructure.registro import RegistroSqlDeAuditoria
from app.modules.authentication.presentation.dependencias import ContextoDeLaPeticion
from app.modules.book_reviews.application.administracion import CrearReview, DatosDeLaReview
from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.book_reviews.infrastructure.repositorio import RepositorioSqlDeReviews
from app.modules.media.domain.texto_alternativo import TextoAlternativoEnConflictoError
from app.modules.media.infrastructure.models import MediaAsset
from app.modules.posts.application.administracion import CrearArticulo, DatosDelArticulo
from app.modules.posts.infrastructure.models import Post
from app.modules.posts.infrastructure.repositorio import RepositorioSqlDeArticulos
from app.modules.profile.application.administracion import ActualizarPerfil, DatosDelPerfil
from app.modules.profile.infrastructure.models import Profile
from app.modules.profile.infrastructure.repositorio import RepositorioSqlDelPerfil
from app.modules.projects.application.administracion import CrearProyecto, DatosDelProyecto
from app.modules.projects.domain import ProjectWorkStatus
from app.modules.projects.infrastructure.models import Project
from app.modules.projects.infrastructure.repositorio import RepositorioSqlDeProyectos
from app.modules.videos.application.administracion import CrearVideo, DatosDelVideo
from app.modules.videos.infrastructure.models import Video
from app.modules.videos.infrastructure.repositorio import RepositorioSqlDeVideos
from tests.integration.datos_de_autenticacion import administrador, limpiar_autenticacion

pytestmark = pytest.mark.integration

CONTEXTO = ContextoDeLaPeticion(origen="203.0.113.7", request_id="peticion-de-prueba")

#: Los dos textos de la carrera. Distintos a proposito: si el diseno fuera
#: seguro, solo uno puede quedar escrito.
TEXTO_A = "Retrato del autor"
TEXTO_B = "Diagrama de arquitectura"


@dataclass(frozen=True)
class Consumidor:
    """Uno de los cinco sitios donde `Task/012` fija el texto en el primer uso."""

    nombre: str
    #: Ejecuta un primer uso sobre `medio_id` proponiendo `texto`.
    usar: Callable[[Session, uuid.UUID, uuid.UUID, str, str], None]


def _articulo(sesion: Session, actor: uuid.UUID, medio: uuid.UUID, texto: str, sufijo: str) -> None:
    CrearArticulo(
        repositorio=RepositorioSqlDeArticulos(sesion), auditoria=RegistroSqlDeAuditoria(sesion)
    )(
        datos=DatosDelArticulo(
            title=f"Articulo {sufijo}",
            slug=f"articulo-{sufijo}",
            summary="Resumen.",
            content="Cuerpo.",
            featured=False,
            seo_title=None,
            seo_description=None,
            cover_id=medio,
            tag_ids=(),
            imagen_alt_text=texto,
        ),
        actor_id=actor,
        contexto=CONTEXTO,
    )


def _review(sesion: Session, actor: uuid.UUID, medio: uuid.UUID, texto: str, sufijo: str) -> None:
    CrearReview(
        repositorio=RepositorioSqlDeReviews(sesion), auditoria=RegistroSqlDeAuditoria(sesion)
    )(
        datos=DatosDeLaReview(
            title=f"Review {sufijo}",
            slug=f"review-{sufijo}",
            summary="Resumen.",
            content="Cuerpo.",
            featured=False,
            seo_title=None,
            seo_description=None,
            cover_id=medio,
            tag_ids=(),
            imagen_alt_text=texto,
            book_title="El libro",
            book_author="La autora",
            rating=4,
            external_link=None,
        ),
        actor_id=actor,
        contexto=CONTEXTO,
    )


def _video(sesion: Session, actor: uuid.UUID, medio: uuid.UUID, texto: str, sufijo: str) -> None:
    CrearVideo(
        repositorio=RepositorioSqlDeVideos(sesion), auditoria=RegistroSqlDeAuditoria(sesion)
    )(
        datos=DatosDelVideo(
            title=f"Video {sufijo}",
            slug=f"video-{sufijo}",
            summary="Resumen.",
            featured=False,
            seo_title=None,
            seo_description=None,
            thumbnail_id=medio,
            tag_ids=(),
            imagen_alt_text=texto,
            provider="youtube",
            video_url="https://example.invalid/v/1",
            embed_reference=None,
            duration_seconds=None,
        ),
        actor_id=actor,
        contexto=CONTEXTO,
    )


def _proyecto(sesion: Session, actor: uuid.UUID, medio: uuid.UUID, texto: str, sufijo: str) -> None:
    CrearProyecto(
        repositorio=RepositorioSqlDeProyectos(sesion), auditoria=RegistroSqlDeAuditoria(sesion)
    )(
        datos=DatosDelProyecto(
            title=f"Proyecto {sufijo}",
            slug=f"proyecto-{sufijo}",
            summary="Resumen.",
            content="Cuerpo.",
            featured=False,
            seo_title=None,
            seo_description=None,
            cover_id=medio,
            tag_ids=(),
            imagen_alt_text=texto,
            project_status=ProjectWorkStatus.ACTIVE,
            technologies=(),
            repository_url=None,
            demo_url=None,
        ),
        actor_id=actor,
        contexto=CONTEXTO,
    )


def _perfil(sesion: Session, actor: uuid.UUID, medio: uuid.UUID, texto: str, sufijo: str) -> None:
    ActualizarPerfil(
        repositorio=RepositorioSqlDelPerfil(sesion), auditoria=RegistroSqlDeAuditoria(sesion)
    )(
        datos=DatosDelPerfil(
            full_name=f"Autor {sufijo}",
            headline=None,
            biography="",
            contact_email=None,
            photo_id=medio,
            photo_alt_text=texto,
            seo_title=None,
            seo_description=None,
            social_links=(),
        ),
        actor_id=actor,
        contexto=CONTEXTO,
    )


CONSUMIDORES = [
    Consumidor("articulo", _articulo),
    Consumidor("review", _review),
    Consumidor("video", _video),
    Consumidor("proyecto", _proyecto),
    Consumidor("perfil", _perfil),
]
IDS = [consumidor.nombre for consumidor in CONSUMIDORES]


def _limpiar(engine: Engine) -> None:
    """Deja la base como estaba. El orden respeta las claves foraneas."""
    with Session(engine) as limpieza:
        for modelo in (Post, BookReview, Video, Project, Profile):
            limpieza.execute(delete(modelo))
        limpiar_autenticacion(limpieza)
        limpieza.execute(delete(MediaAsset))
        limpieza.commit()


def _preparar(engine: Engine, *, con_perfil: bool) -> tuple[uuid.UUID, uuid.UUID]:
    """Administrador y medio **sin texto alternativo**, ya confirmados."""
    _limpiar(engine)
    with Session(engine) as preparacion:
        actor = administrador(preparacion)
        medio = MediaAsset(
            object_key=f"medios/{uuid.uuid4()}/original.png",
            original_filename="foto.png",
            mime_type="image/png",
            size_bytes=1024,
            alt_text=None,
        )
        preparacion.add(medio)
        if con_perfil:
            preparacion.add(Profile(full_name="Autor"))
        preparacion.commit()
        return actor.id, medio.id


def _carrera(
    engine: Engine,
    consumidor: Consumidor,
    actor: uuid.UUID,
    medio: uuid.UUID,
    textos: tuple[str, str],
) -> list[str]:
    """Lanza dos primeros usos a la vez y devuelve el veredicto de cada uno."""
    barrera = threading.Barrier(2)
    resultados: list[str] = []
    cerrojo = threading.Lock()

    def intentar(texto: str, sufijo: str) -> None:
        with Session(engine) as sesion:
            barrera.wait(timeout=10)
            try:
                consumidor.usar(sesion, actor, medio, texto, sufijo)
                sesion.commit()
                veredicto = "ok"
            except TextoAlternativoEnConflictoError:
                sesion.rollback()
                veredicto = "conflicto"
            except Exception as error:  # pragma: no cover - diagnostico si algo mas falla
                sesion.rollback()
                veredicto = f"error:{type(error).__name__}"
        with cerrojo:
            resultados.append(veredicto)

    hilos = [
        threading.Thread(target=intentar, args=(textos[0], "a")),
        threading.Thread(target=intentar, args=(textos[1], "b")),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=30)
    return resultados


def _texto_final(engine: Engine, medio: uuid.UUID) -> str | None:
    with Session(engine) as comprobacion:
        return comprobacion.execute(
            select(MediaAsset.alt_text).where(MediaAsset.id == medio)
        ).scalar_one()


# --- La carrera: dos textos DISTINTOS --------------------------------------
@pytest.mark.parametrize("consumidor", CONSUMIDORES, ids=IDS)
def test_dos_primeros_usos_con_texto_distinto_no_pueden_prosperar_los_dos(
    database_engine: Engine,
    database_settings: object,
    esquema_migrado: None,
    consumidor: Consumidor,
) -> None:
    """Solo una politica puede ganar, y el valor final es **exactamente** el suyo.

    Con la lectura sin cerrojo, las dos transacciones leen `NULL`, las dos
    concluyen que es el primer uso y las dos escriben: el resultado es
    *last-write-wins*, y **D-012-Z queda desmentida**.
    """
    actor, medio = _preparar(database_engine, con_perfil=consumidor.nombre == "perfil")
    try:
        resultados = _carrera(database_engine, consumidor, actor, medio, (TEXTO_A, TEXTO_B))

        assert sorted(resultados) == ["conflicto", "ok"], (
            f"los dos primeros usos prosperaron ({resultados}): la decision "
            "set-on-first-use no esta serializada y un texto alternativo puede "
            "sobrescribirse en silencio"
        )
        assert _texto_final(database_engine, medio) in (TEXTO_A, TEXTO_B)
    finally:
        _limpiar(database_engine)


@pytest.mark.parametrize("consumidor", CONSUMIDORES, ids=IDS)
def test_el_valor_final_es_el_del_ganador_y_nunca_un_tercer_estado(
    database_engine: Engine,
    database_settings: object,
    esquema_migrado: None,
    consumidor: Consumidor,
) -> None:
    """El perdedor no deja rastro: ni su texto, ni su contenido, ni su evento."""
    actor, medio = _preparar(database_engine, con_perfil=consumidor.nombre == "perfil")
    try:
        _carrera(database_engine, consumidor, actor, medio, (TEXTO_A, TEXTO_B))

        final = _texto_final(database_engine, medio)
        assert final in (TEXTO_A, TEXTO_B)
        with Session(database_engine) as comprobacion:
            eventos = list(comprobacion.execute(select(AuditEvent.action)).scalars())
        # Un unico evento de contenido: el del ganador. El del perdedor se fue
        # con su rollback.
        assert len([accion for accion in eventos if not accion.startswith("authentication.")]) == 1
    finally:
        _limpiar(database_engine)


# --- El control: dos textos IGUALES ---------------------------------------
@pytest.mark.parametrize("consumidor", CONSUMIDORES, ids=IDS)
def test_dos_primeros_usos_con_el_mismo_texto_son_coherentes(
    database_engine: Engine,
    database_settings: object,
    esquema_migrado: None,
    consumidor: Consumidor,
) -> None:
    """Proponer lo mismo **no** es un conflicto.

    Es el control que impide que la correccion se pase de frenada: serializar la
    decision no puede convertir en error dos peticiones que piden exactamente lo
    mismo. Una escribe y la otra encuentra el valor ya puesto; el resultado es
    el texto acordado y **las dos operaciones terminan correctamente**.

    La expectativa es la fuerte a proposito: los dos veredictos deben ser `ok`.
    Comprobar solo la ausencia de `conflicto` dejaria pasar un
    `error:DeadlockDetected` o cualquier otro fallo del cerrojo, que tambien
    incumple la garantia.
    """
    actor, medio = _preparar(database_engine, con_perfil=consumidor.nombre == "perfil")
    try:
        resultados = _carrera(database_engine, consumidor, actor, medio, (TEXTO_A, TEXTO_A))

        assert sorted(resultados) == ["ok", "ok"], (
            f"proponer el mismo texto no prospero en los dos usos ({resultados}): "
            "la igualdad no debe convertirse en conflicto ni en ningun otro error"
        )
        assert _texto_final(database_engine, medio) == TEXTO_A
    finally:
        _limpiar(database_engine)
