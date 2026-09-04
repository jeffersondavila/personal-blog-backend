"""Catalogo de acciones auditables del CRUD administrativo (`Task/012`).

`Task/008` dejo `audit_events.action` como **cadena libre** a proposito y anoto
que el catalogo se cierra *"en `Task/011` y `Task/012`"*. `Task/011` cerro las
cuatro de autenticacion; esta es la otra mitad.

Decision **D-012-N**: las acciones de contenido llevan el prefijo `content.` y
**no** el del tipo. `audit_events` ya tiene la columna `entity_type` para decir
de que tipo es el elemento (`data-model.md` D-M); repetirlo dentro de `action`
daria dos fuentes para el mismo hecho, que pueden discrepar, y obligaria a
conocer cuatro literales para responder *"que se publico este mes"*.
"""

from __future__ import annotations

from app.modules.audit.domain.acciones import (
    ENTIDAD_ADMINISTRADOR,
    ENTIDAD_ETIQUETA,
    ENTIDAD_MEDIO,
    ENTIDAD_PERFIL,
    AccionAuditada,
)
from app.modules.audit.infrastructure.models import LONGITUD_DE_ACCION


def test_el_catalogo_cubre_las_acciones_del_crud_administrativo() -> None:
    """Once acciones nuevas, cada una con un productor real en esta tarea.

    El conjunto se escribe entero a mano: derivarlo de la enumeracion haria que
    la prueba se adaptara sola a cualquier accion nueva, que es justo lo que no
    debe hacer. Aqui el contrato es la lista.
    """
    valores = {accion.value for accion in AccionAuditada}

    assert valores == {
        # `Task/011` — autenticacion, intactas
        "authentication.login_succeeded",
        "authentication.login_failed",
        "authentication.logout",
        "authentication.account_locked",
        # `Task/012` — contenido publicable
        "content.created",
        "content.updated",
        "content.published",
        "content.unpublished",
        "content.archived",
        # `Task/012` — perfil, etiquetas y medios
        "profile.updated",
        "tag.created",
        "tag.updated",
        "tag.deleted",
        "media.uploaded",
        "media.deleted",
    }


def test_las_cuatro_acciones_de_autenticacion_no_cambian() -> None:
    """Regresion de `Task/011`: sus literales ya estan escritos en el historial."""
    assert AccionAuditada.ACCESO_CORRECTO.value == "authentication.login_succeeded"
    assert AccionAuditada.ACCESO_FALLIDO.value == "authentication.login_failed"
    assert AccionAuditada.CIERRE_DE_SESION.value == "authentication.logout"
    assert AccionAuditada.CUENTA_BLOQUEADA.value == "authentication.account_locked"


def test_ninguna_accion_excede_el_ancho_de_la_columna() -> None:
    """`action` es `VARCHAR(64)` (`data-model.md` 4.10)."""
    for accion in AccionAuditada:
        assert len(accion.value) <= LONGITUD_DE_ACCION, accion


def test_los_tipos_de_entidad_son_los_del_repositorio_de_medios() -> None:
    """El mismo vocabulario en los dos sitios donde el proyecto nombra un tipo.

    `RepositorioDeMediosSQL.usos_de` ya devuelve `post`, `book_review`,
    `project`, `video` y `profile` para decir donde se usa una imagen
    (`Task/010`). Que la auditoria usara otros nombres para las mismas cosas
    obligaria a traducir entre dos vocabularios internos sin ninguna ganancia.
    """
    from app.modules.audit.domain.acciones import ENTIDADES_DE_CONTENIDO

    assert ENTIDADES_DE_CONTENIDO == {"post", "book_review", "video", "project"}
    assert ENTIDAD_PERFIL == "profile"
    assert ENTIDAD_ETIQUETA == "tag"
    assert ENTIDAD_MEDIO == "media_asset"
    assert ENTIDAD_ADMINISTRADOR == "administrator"


def test_el_puerto_del_historial_vive_en_el_modulo_de_auditoria() -> None:
    """Lo declara quien es dueno del historial, y `Task/011` lo reexporta.

    `Task/011` declaro `RegistroDeAuditoria` dentro de
    `authentication.domain.puertos` porque era su unico consumidor. Con
    `Task/012` lo consumen ademas los cuatro tipos de contenido, el perfil, las
    etiquetas y los medios: que todos ellos tuvieran que importar el modulo de
    **autenticacion** para escribir en el historial seria una dependencia que no
    describe ninguna relacion real.

    Se mueve al modulo `audit`, que es su dueno segun software-architecture.md
    seccion 3.3, y `authentication` lo reexporta para no romper nada.
    """
    from app.modules.audit.domain.puertos import RegistroDeAuditoria
    from app.modules.authentication.domain.puertos import (
        RegistroDeAuditoria as ReexportadoPorAutenticacion,
    )

    assert ReexportadoPorAutenticacion is RegistroDeAuditoria
