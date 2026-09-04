"""Persistencia administrativa del perfil sobre SQLAlchemy (`Task/012`).

Implementa `RepositorioDelPerfil` traduciendo entre las estructuras planas de la
capa de aplicacion y el modelo ORM, igual que hizo `Task/010` con los medios.

Por que los enlaces sociales se reemplazan enteros
---------------------------------------------------

`Profile.social_links` tiene `cascade="all, delete-orphan"`, asi que asignar una
lista nueva **borra los que dejan de estar** sin necesidad de un `DELETE`
explicito. Es lo que corresponde a un `PUT` (decision D-012-C): lo que llega es
la coleccion resultante, no un incremento.

El `flush` no es opcional
-------------------------

Es la misma convencion que `Task/010` y `Task/011` fijaron para los repositorios
de escritura: sin el, una violacion de restriccion no aparece hasta el `commit`
—fuera del alcance del caso de uso— y la respuesta ya estaria construida.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.media.infrastructure.models import MediaAsset
from app.modules.profile.application.administracion import DatosDelPerfil
from app.modules.profile.infrastructure.models import Profile, ProfileSocialLink


class RepositorioSqlDelPerfil:
    """Repositorio del perfil sobre una sesion de SQLAlchemy."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def identificador(self) -> uuid.UUID | None:
        """Identificador del unico perfil, o `None` si todavia no existe."""
        return self._sesion.execute(select(Profile.id).limit(1)).scalar_one_or_none()

    def medio_existe(self, identificador: uuid.UUID) -> bool:
        """Comprueba que la imagen referenciada existe.

        Se consulta **antes** de asignarla en lugar de dejar que falle la clave
        foranea: un `IntegrityError` no distingue que columna lo provoco, y el
        mensaje que llega al administrador tiene que decir **cual** referencia
        esta mal (decision D-012-J).
        """
        return (
            self._sesion.execute(
                select(MediaAsset.id).where(MediaAsset.id == identificador)
            ).scalar_one_or_none()
            is not None
        )

    def bloquear_texto_alternativo(self, identificador: uuid.UUID) -> str | None:
        """Lee el texto alternativo **bloqueando la fila** del medio.

        Es la lectura de la decision *set-on-first-use* (D-012-Y), y necesita
        el cerrojo porque esa decision es una **lectura-decision-escritura**:
        sin el, dos primeros usos simultaneos leen los dos `NULL`, concluyen
        los dos que son el primero y escriben los dos — el segundo `UPDATE`
        espera al cerrojo de fila y **pisa** al primero en cuanto confirma.
        Eso convertiria **D-012-Z** en falsa bajo concurrencia. Se comprobo:
        con la lectura sin cerrojo las dos transacciones terminaban en `ok`.

        `SELECT ... FOR UPDATE` lo resuelve entero en **READ COMMITTED**, que
        es el nivel en el que trabaja el proyecto: quien llega segundo espera
        al cerrojo y, al obtenerlo, **relee la ultima version confirmada** —no
        la instantanea con la que empezo—. Asi ve el texto del ganador y la
        regla del dominio lo convierte en conflicto, o en no-op si resulta ser
        el mismo texto. La igualdad no se convierte en error.

        El cerrojo lo da **el motor**, asi que funciona con varios *workers* y
        varias instancias: no depende del GIL ni de que haya un solo proceso.
        Es el mismo mecanismo que `Task/011` uso para el contador de intentos
        fallidos y que las transiciones de publicacion usan para su estado.

        **Es la unica lectura del texto en este modulo.** El perfil no tiene
        publicacion, asi que no hay una segunda lectura de validacion como en
        los cuatro tipos publicables: asignar la foto *es* usarla, y esa misma
        lectura decide. Las lecturas publicas y la biblioteca no pasan por
        aqui, y siguen sin cerrojo.
        """
        return self._sesion.execute(
            select(MediaAsset.alt_text).where(MediaAsset.id == identificador).with_for_update()
        ).scalar_one_or_none()

    def escribir_texto_alternativo(self, identificador: uuid.UUID, texto: str) -> None:
        """Persiste el texto alternativo del medio, en **esta** transaccion.

        La escritura y la asignacion de `photo_id` pertenecen a la misma
        transaccion de la peticion (decision D-012-V): un fallo posterior las
        revierte juntas.
        """
        fila = self._sesion.execute(
            select(MediaAsset).where(MediaAsset.id == identificador)
        ).scalar_one()
        fila.alt_text = texto
        self._sesion.flush()

    def guardar(self, perfil_id: uuid.UUID, datos: DatosDelPerfil) -> None:
        """Deja el perfil con exactamente estos valores y estos enlaces."""
        perfil = self._sesion.get(Profile, perfil_id)
        if perfil is None:  # pragma: no cover - el caso de uso ya lo comprobo
            raise AssertionError("el perfil desaparecio entre la comprobacion y la escritura")

        perfil.full_name = datos.full_name
        perfil.headline = datos.headline
        perfil.biography = datos.biography
        perfil.contact_email = datos.contact_email
        perfil.photo_id = datos.photo_id
        perfil.seo_title = datos.seo_title
        perfil.seo_description = datos.seo_description
        # Los enlaces se vacian y se **confirman** antes de insertar los nuevos.
        #
        # No es ceremonia: la unidad de trabajo de SQLAlchemy emite los `INSERT`
        # de una coleccion **antes** que los `DELETE` de sus huerfanos, asi que
        # reemplazar la lista de una vez intenta insertar el nuevo enlace con
        # `display_order = 0` mientras el antiguo todavia lo ocupa, y
        # `uq_profile_social_links_profile_id_display_order` lo rechaza. El
        # defecto lo encontro `test_los_enlaces_sociales_se_reemplazan_por_completo`
        # contra PostgreSQL real; ningun doble lo habria mostrado.
        perfil.social_links = []
        self._sesion.flush()

        # `display_order` sale del indice, no del cliente (decision D-012-Q).
        perfil.social_links = [
            ProfileSocialLink(label=enlace.label, url=enlace.url, display_order=orden)
            for orden, enlace in enumerate(datos.social_links)
        ]
        self._sesion.flush()
