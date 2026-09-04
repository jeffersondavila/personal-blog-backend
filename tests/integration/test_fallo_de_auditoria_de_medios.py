"""Qué queda si la auditoría falla **después** de tocar el almacenamiento.

Por qué esta prueba existe
--------------------------

`Task/012` compone dos cosas que **no comparten transacción**:

    Task/010 (PostgreSQL + MinIO)  →  auditoría de Task/012 (PostgreSQL)

PostgreSQL revierte; MinIO **no**. Así que hay una ventana concreta que ninguna
prueba anterior cubría: el caso de uso de `Task/010` **termina con éxito** y el
evento de auditoría falla justo después. La transacción de la petición revierte
lo de PostgreSQL —incluido lo que hizo `Task/010`— pero lo que se escribió o se
borró en el almacenamiento ya no vuelve.

Qué se modela y por qué así
---------------------------

Se ejercita el **caso de uso**, no el endpoint. La razón es el harness: el
cliente de pruebas sustituye `get_session` por la sesión de la prueba, así que
una petición que falla **no** revierte —el `session_scope` real, que sí lo hace,
queda fuera—. Probarlo por HTTP mediría lo contrario de lo que ocurre en
producción.

Aquí la transacción de la petición se modela con un `SAVEPOINT` explícito
alrededor de la operación: `begin_nested()` y `rollback()` sobre él reproducen
exactamente lo que `session_scope` hace al propagarse una excepción, sin sacar la
prueba de su transacción externa.

El almacenamiento es el **real**: bucket efímero del harness de `Task/010`, con
su prefijo de pruebas y su borrado en el `finally`. Sin AWS.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.domain.acciones import AccionAuditada
from app.modules.audit.infrastructure.models import AuditEvent
from app.modules.audit.infrastructure.registro import RegistroSqlDeAuditoria
from app.modules.authentication.presentation.dependencias import ContextoDeLaPeticion
from app.modules.media.application.administracion import (
    ArchivoRecibido,
    EliminarMedioAdministrativo,
    SubirMedioAdministrativo,
)
from app.modules.media.application.eliminar_medio import EliminarMedio
from app.modules.media.application.subir_imagen import SubirImagen
from app.modules.media.domain.claves import clave_de_la_miniatura
from app.modules.media.infrastructure.models import MediaAsset
from app.modules.media.infrastructure.repositorio import RepositorioDeMediosSQL
from app.shared.storage import ObjectStorage
from tests.imagenes import imagen
from tests.integration.datos_de_autenticacion import administrador

pytestmark = pytest.mark.integration

CONTEXTO = ContextoDeLaPeticion(origen="203.0.113.7", request_id="peticion-de-prueba")


class AuditoriaRotaError(RuntimeError):
    """Fallo deliberado del historial, para observar qué sobrevive."""


class _AuditoriaQueFalla:
    """Registro de auditoría que **siempre** falla.

    Es un doble de frontera —el historial es uno de los límites que
    BACKEND_TESTING_STRATEGY.md §10 admite doblar— y falla del único modo en que
    esto importa: lanzando **después** de que la operación de medios haya
    terminado.
    """

    def registrar(self, accion: str, **_: object) -> None:
        raise AuditoriaRotaError(f"el historial no pudo escribir {accion!r}")


def _subida(
    almacenamiento: ObjectStorage, sesion: Session, auditoria: Any
) -> SubirMedioAdministrativo:
    return SubirMedioAdministrativo(
        caso_de_uso=SubirImagen(
            almacenamiento=almacenamiento, repositorio=RepositorioDeMediosSQL(sesion)
        ),
        auditoria=auditoria,
    )


def _borrado(
    almacenamiento: ObjectStorage, sesion: Session, auditoria: Any
) -> EliminarMedioAdministrativo:
    return EliminarMedioAdministrativo(
        caso_de_uso=EliminarMedio(
            almacenamiento=almacenamiento, repositorio=RepositorioDeMediosSQL(sesion)
        ),
        auditoria=auditoria,
    )


def _archivo() -> ArchivoRecibido:
    return ArchivoRecibido(
        contenido=imagen(ancho=48, alto=32), nombre="foto.png", alt_text="Un retrato"
    )


def _eventos(sesion: Session, accion: AccionAuditada) -> int:
    return sesion.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == accion.value)
    ).scalar_one()


# --- A. Carga + fallo de auditoría -----------------------------------------
def test_si_la_auditoria_falla_tras_cargar_no_queda_fila_ni_evento(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """La carga se revierte entera en PostgreSQL: ni medio, ni evento.

    Es la asimetría que `Task/010` eligió a propósito (**D-010-P**): persistir la
    fila al final significa que un fallo posterior deja, como mucho, **objetos
    huérfanos** —basura recuperable—, y **nunca** una fila que apunte a un objeto
    ausente.
    """
    actor = administrador(sesion_de_pruebas)

    punto = sesion_de_pruebas.begin_nested()
    with pytest.raises(AuditoriaRotaError):
        _subida(almacenamiento_minio, sesion_de_pruebas, _AuditoriaQueFalla())(
            archivo=_archivo(), actor_id=actor.id, contexto=CONTEXTO
        )
    punto.rollback()

    assert sesion_de_pruebas.execute(select(func.count()).select_from(MediaAsset)).scalar_one() == 0
    assert _eventos(sesion_de_pruebas, AccionAuditada.MEDIO_CARGADO) == 0


def test_la_carga_fallida_no_deja_ninguna_fila_que_apunte_a_un_objeto_ausente(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """La invariante que de verdad protege el orden de `Task/010`.

    Los objetos huérfanos son un coste **aceptado y documentado**; una fila sin
    objeto sería *"una imagen rota en el blog publicado"*. Esta prueba comprueba
    lo segundo, que es lo que no puede pasar.
    """
    actor = administrador(sesion_de_pruebas)

    punto = sesion_de_pruebas.begin_nested()
    with pytest.raises(AuditoriaRotaError):
        _subida(almacenamiento_minio, sesion_de_pruebas, _AuditoriaQueFalla())(
            archivo=_archivo(), actor_id=actor.id, contexto=CONTEXTO
        )
    punto.rollback()

    for fila in sesion_de_pruebas.execute(select(MediaAsset)).scalars():
        assert almacenamiento_minio.existe(fila.object_key), (
            "quedo una fila apuntando a un objeto que no existe"
        )


# --- B. Borrado + fallo de auditoría ---------------------------------------
def test_si_la_auditoria_falla_tras_borrar_la_fila_no_puede_quedar_sin_objetos(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """**El caso peligroso.**

    `EliminarMedio` borra la fila y **después** los objetos, y `Task/010` eligió
    ese orden justamente para no dejar nunca *"una fila sin objetos"*. Pero ese
    borrado de fila solo está **flushed**, no confirmado: si la auditoría falla
    después, la transacción de la petición revierte y **la fila vuelve**, mientras
    que los objetos de MinIO ya no.

    El estado resultante —fila viva apuntando a objetos inexistentes— es
    exactamente el que `Task/010` declaró inaceptable, y lo produce la
    **composición** de `Task/012`, no `Task/010`.
    """
    actor = administrador(sesion_de_pruebas)
    subido = _subida(
        almacenamiento_minio, sesion_de_pruebas, RegistroSqlDeAuditoria(sesion_de_pruebas)
    )(archivo=_archivo(), actor_id=actor.id, contexto=CONTEXTO)
    original = sesion_de_pruebas.execute(
        select(MediaAsset.object_key).where(MediaAsset.id == subido)
    ).scalar_one()
    miniatura = clave_de_la_miniatura(original)
    assert almacenamiento_minio.existe(original)
    assert almacenamiento_minio.existe(miniatura)

    punto = sesion_de_pruebas.begin_nested()
    with pytest.raises(AuditoriaRotaError):
        _borrado(almacenamiento_minio, sesion_de_pruebas, _AuditoriaQueFalla())(
            identificador=subido,
            nombre_original="foto.png",
            actor_id=actor.id,
            contexto=CONTEXTO,
        )
    punto.rollback()

    fila = sesion_de_pruebas.get(MediaAsset, subido)
    if fila is not None:
        assert almacenamiento_minio.existe(fila.object_key), (
            "la fila volvio con el rollback pero su objeto ya estaba borrado: "
            "es exactamente la 'imagen rota en el blog publicado' que D-010-P prohibe"
        )


def test_un_borrado_que_no_se_audita_no_puede_ser_durable(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """Regla transversal 3 de USER_FLOWS.md, llevada a su consecuencia.

    *Todo flujo administrativo que modifica datos genera un `AuditEvent`.* Si el
    evento no se puede escribir, la modificación **no puede quedar hecha**: o las
    dos cosas, o ninguna. Un borrado sin rastro es justo lo que la auditoría
    existe para impedir.
    """
    actor = administrador(sesion_de_pruebas)
    subido = _subida(
        almacenamiento_minio, sesion_de_pruebas, RegistroSqlDeAuditoria(sesion_de_pruebas)
    )(archivo=_archivo(), actor_id=actor.id, contexto=CONTEXTO)
    original = sesion_de_pruebas.execute(
        select(MediaAsset.object_key).where(MediaAsset.id == subido)
    ).scalar_one()

    punto = sesion_de_pruebas.begin_nested()
    with pytest.raises(AuditoriaRotaError):
        _borrado(almacenamiento_minio, sesion_de_pruebas, _AuditoriaQueFalla())(
            identificador=subido,
            nombre_original="foto.png",
            actor_id=actor.id,
            contexto=CONTEXTO,
        )
    punto.rollback()

    assert _eventos(sesion_de_pruebas, AccionAuditada.MEDIO_ELIMINADO) == 0
    assert almacenamiento_minio.existe(original), (
        "el objeto se borro de forma irreversible aunque la operacion no llego a auditarse"
    )


def test_un_borrado_rechazado_por_uso_no_deja_evento_durable(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """Un medio en uso se rechaza, y del intento no queda rastro.

    Con el orden *auditar y despues borrar*, el evento llega a escribirse y la
    transaccion de la peticion lo deshace junto con todo lo demas. La garantia
    —*el historial registra lo que paso, no lo que se intento*— se mantiene; lo
    que cambia es de que depende, y es de la misma unidad de atomicidad
    (**D-012-V**) de la que ya dependen todas las operaciones administrativas.
    """
    from app.modules.media.domain.errores import MedioEnUsoError
    from tests.integration.datos import articulo

    actor = administrador(sesion_de_pruebas)
    auditoria = RegistroSqlDeAuditoria(sesion_de_pruebas)
    subido = _subida(almacenamiento_minio, sesion_de_pruebas, auditoria)(
        archivo=_archivo(), actor_id=actor.id, contexto=CONTEXTO
    )
    imagen_guardada = sesion_de_pruebas.get(MediaAsset, subido)
    sesion_de_pruebas.add(articulo("con-portada", portada=imagen_guardada))
    sesion_de_pruebas.flush()

    punto = sesion_de_pruebas.begin_nested()
    with pytest.raises(MedioEnUsoError):
        _borrado(almacenamiento_minio, sesion_de_pruebas, auditoria)(
            identificador=subido,
            nombre_original="foto.png",
            actor_id=actor.id,
            contexto=CONTEXTO,
        )
    punto.rollback()

    assert _eventos(sesion_de_pruebas, AccionAuditada.MEDIO_ELIMINADO) == 0
    assert sesion_de_pruebas.get(MediaAsset, subido) is not None


# --- Control positivo: sin fallo, todo queda coherente ---------------------
def test_con_la_auditoria_sana_el_borrado_es_completo_y_coherente(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """Control del caso anterior: sin él, las pruebas de arriba pasarían aunque
    el borrado no llegara a funcionar nunca."""
    actor = administrador(sesion_de_pruebas)
    auditoria = RegistroSqlDeAuditoria(sesion_de_pruebas)
    subido = _subida(almacenamiento_minio, sesion_de_pruebas, auditoria)(
        archivo=_archivo(), actor_id=actor.id, contexto=CONTEXTO
    )
    original = sesion_de_pruebas.execute(
        select(MediaAsset.object_key).where(MediaAsset.id == subido)
    ).scalar_one()

    _borrado(almacenamiento_minio, sesion_de_pruebas, auditoria)(
        identificador=subido,
        nombre_original="foto.png",
        actor_id=actor.id,
        contexto=CONTEXTO,
    )

    assert sesion_de_pruebas.get(MediaAsset, subido) is None
    assert not almacenamiento_minio.existe(original)
    assert not almacenamiento_minio.existe(clave_de_la_miniatura(original))
    assert _eventos(sesion_de_pruebas, AccionAuditada.MEDIO_ELIMINADO) == 1


def test_un_borrado_rechazado_no_deja_evento_durable(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """El historial registra lo que pasó, no lo que se intentó.

    Con el orden *auditar y después borrar*, un rechazo escribe el evento y lo
    **deshace** al revertir la petición. La garantía sigue siendo la misma —no
    queda rastro de algo que no ocurrió— pero conviene decir de qué depende: de
    la **transacción de la petición**, que es la unidad de atomicidad que fija la
    decisión **D-012-V** y de la que ya dependen todas las demás operaciones
    administrativas.

    En la ruta HTTP real este caso ni siquiera llega hasta aquí: el endpoint lee
    el medio antes —necesita su `original_filename`— y responde `404` sin invocar
    el caso de uso. Esta prueba cubre el nivel de abajo, que es donde la garantía
    tiene que sostenerse por sí sola.
    """
    from app.shared.errors import ResourceNotFoundError

    actor = administrador(sesion_de_pruebas)

    punto = sesion_de_pruebas.begin_nested()
    with pytest.raises(ResourceNotFoundError):
        _borrado(
            almacenamiento_minio, sesion_de_pruebas, RegistroSqlDeAuditoria(sesion_de_pruebas)
        )(
            identificador=uuid.uuid4(),
            nombre_original="inexistente.png",
            actor_id=actor.id,
            contexto=CONTEXTO,
        )
    punto.rollback()

    assert _eventos(sesion_de_pruebas, AccionAuditada.MEDIO_ELIMINADO) == 0
