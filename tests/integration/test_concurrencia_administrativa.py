"""Dos transiciones simultaneas sobre el mismo contenido (caso PO-24).

Va contra **dos conexiones reales** —y por eso no usa la sesion transaccional
del harness—: el cerrojo de fila lo da PostgreSQL, y con una sola conexion no
hay nada que serializar. Es el mismo patron con el que `Task/011` demostro que
el contador de intentos fallidos no pierde actualizaciones (B-07).

Que se protege exactamente (decision D-012-P)
----------------------------------------------

Publicar es una **lectura-modificacion-escritura** sobre el estado: se lee
`status` y `published_at`, el dominio decide la transicion y se escribe el
resultado. Sin cerrojo, dos peticiones simultaneas leen las dos el mismo
`draft`, las dos concluyen que la transicion es valida, las dos escriben y las
dos emiten un evento de auditoria — con `published_at` distintos, porque cada
una usa su propio instante.

Con `SELECT … FOR UPDATE`, la segunda espera, relee `published`, y su transicion
**falla** con el conflicto que le corresponde.

Lo que esta prueba **no** afirma
---------------------------------

No afirma que la edicion concurrente este protegida. No lo esta, y es
deliberado: un cerrojo optimista exigiria una columna de version —un cambio de
esquema— para un MVP con **un** administrador. Queda registrado como deuda.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import AccionAuditada
from app.modules.audit.infrastructure.models import AuditEvent
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import Post
from app.shared.configuration import Settings
from tests.integration.administracion import ACCESO, ADMIN
from tests.integration.datos_de_autenticacion import (
    CONTRASENA,
    CORREO,
    administrador,
    limpiar_autenticacion,
)

pytestmark = pytest.mark.integration

ARTICULOS = f"{ADMIN}/posts"


def _limpiar(engine: Engine) -> None:
    """Deja la base como estaba. El orden respeta `ON DELETE RESTRICT`."""
    with Session(engine) as limpieza:
        limpieza.execute(delete(Post))
        limpiar_autenticacion(limpieza)
        limpieza.commit()


def test_dos_publicaciones_simultaneas_solo_prosperan_una(
    database_engine: Engine,
    database_settings: Settings,
    esquema_migrado: None,
    configured_process: None,
) -> None:
    """Una responde `200` y la otra `409`, y queda **un solo** evento.

    La prueba es determinista y no depende de ganar ninguna carrera: las dos
    peticiones se lanzan a la vez y **se exige el resultado correcto**. Con la
    implementacion ingenua —sin `with_for_update()`— los dos codigos serian
    `200` y habria dos eventos de publicacion sobre el mismo articulo.
    """
    from app.main import create_app

    _limpiar(database_engine)
    with Session(database_engine) as preparacion:
        administrador(preparacion)
        preparacion.add(
            Post(
                slug="carrera",
                title="Carrera",
                summary="Un resumen.",
                content="Cuerpo.",
                status=PostStatus.DRAFT,
            )
        )
        preparacion.commit()
        identificador = preparacion.execute(select(Post.id)).scalar_one()

    aplicacion = create_app(
        settings=database_settings.model_copy(update={"auth_cookie_secure": False})
    )
    barrera = threading.Barrier(2)
    respuestas: list[int] = []

    def publicar() -> None:
        with TestClient(aplicacion) as cliente:
            acceso = cliente.post(ACCESO, json={"email": CORREO, "password": CONTRASENA})
            assert acceso.status_code == 200, acceso.text
            barrera.wait(timeout=10)
            respuestas.append(cliente.post(f"{ARTICULOS}/{identificador}/publish").status_code)

    hilos = [threading.Thread(target=publicar) for _ in range(2)]
    try:
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)

        with Session(database_engine) as comprobacion:
            eventos = (
                comprobacion.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == AccionAuditada.CONTENIDO_PUBLICADO.value
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(respuestas) == [200, 409], (
                "las dos publicaciones prosperaron: la transicion no esta protegida "
                "frente a peticiones simultaneas"
            )
            assert len(eventos) == 1, "quedaron dos eventos de publicacion para un solo articulo"
    finally:
        _limpiar(database_engine)
