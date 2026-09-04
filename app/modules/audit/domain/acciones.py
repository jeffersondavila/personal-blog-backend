"""Catalogo de acciones auditables (`Task/011` y `Task/012`).

`Task/008` dejo `AuditEvent.action` como cadena libre **a proposito**: congelarla
en un `CHECK` habria obligado a migrar el esquema cada vez que se decidiera una
accion nueva, y en aquel momento no habia ninguna decidida. El catalogo se cierra
"en `Task/011` y `Task/012`", y aqui estan las dos mitades.

Por que una enumeracion y no cadenas sueltas
--------------------------------------------

La restriccion no puede vivir en la base sin pagar una migracion por accion, pero
si puede vivir aqui: una errata en un literal escrito a mano —
`"authentication.login_suceeded"`— produciria un evento que **ninguna consulta
posterior encontraria**, y el defecto solo se veria el dia que alguien fuera a
leer el historial. Con la enumeracion, esa errata no compila.

Por que cada entrada existe
---------------------------

Cada entrada tiene un **productor real** en el codigo. Un catalogo con acciones
que nadie emite es documentacion que aparenta un historial inexistente.
`Task/011` cerro las cuatro de autenticacion; `Task/012` anade las once del CRUD
administrativo, y ni una mas.

Por que el contenido lleva el prefijo `content.` y no el del tipo
-----------------------------------------------------------------

Decision **D-012-N**. La tabla ya tiene la columna `entity_type` para decir de
que tipo es el elemento afectado (`data-model.md` D-M). Repetir el tipo dentro
de `action` —`posts.published`, `videos.published`…— daria **dos fuentes para el
mismo hecho**, que pueden discrepar, y obligaria a conocer cuatro literales para
responder a la pregunta natural del historial: *que se publico este mes*. El
prefijo sigue diciendo de que clase de modulo viene la entrada, que es lo que
pedia la nota original.

Lo que **no** se audita, y por que
----------------------------------

- Un rechazo por **limite de tasa** (`Task/011`). Es un hecho operativo del
  endpoint, no una accion administrativa: cualquiera desde fuera puede
  provocarlo a voluntad, asi que auditarlo permitiria llenar el historial de
  ruido justo antes de hacer algo que si conviene esconder. El contador deja
  constancia en su propia tabla y la peticion queda en el log estructurado.
- Las **lecturas** (`Task/012`). USER_FLOWS.md, regla transversal 3, audita
  *"todo flujo administrativo que **modifica** datos"*. Registrar cada listado
  del panel escondería lo que si importa detras de su propio ruido.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class AccionAuditada(StrEnum):
    """Acciones administrativas que dejan rastro en el historial.

    El prefijo no es decorativo: mantiene legible de un vistazo de que clase de
    modulo viene cada entrada del historial, sin tener que cruzarla con nada.
    """

    # --- `Task/011` — autenticacion ---------------------------------------
    #: El administrador inicio sesion correctamente.
    ACCESO_CORRECTO = "authentication.login_succeeded"
    #: Un intento de acceso no prospero. `actor_id` es nulo si el correo recibido
    #: no correspondia a ningun administrador.
    ACCESO_FALLIDO = "authentication.login_failed"
    #: El administrador cerro sesion.
    CIERRE_DE_SESION = "authentication.logout"
    #: Un intento fallido alcanzo el umbral y activo el bloqueo temporal. Se
    #: registra la **transicion**, no el estado: los intentos posteriores durante
    #: el mismo bloqueo no vuelven a emitirlo.
    CUENTA_BLOQUEADA = "authentication.account_locked"

    # --- `Task/012` — contenido publicable --------------------------------
    #: Se creo un borrador (USER_FLOWS.md B.2).
    CONTENIDO_CREADO = "content.created"
    #: Se edito un contenido, en cualquier estado (B.3).
    CONTENIDO_ACTUALIZADO = "content.updated"
    #: Un borrador paso a publicado (B.7).
    CONTENIDO_PUBLICADO = "content.published"
    #: Un contenido publicado volvio a borrador (B.8). Solo articulos y reviews.
    CONTENIDO_DESPUBLICADO = "content.unpublished"
    #: Un contenido se retiro sin eliminarse (B.9).
    CONTENIDO_ARCHIVADO = "content.archived"

    # --- `Task/012` — perfil, etiquetas y medios --------------------------
    #: Se edito el perfil singleton (B.10). No hay `created` ni `deleted`: el
    #: perfil no se crea ni se elimina por API (decision D-012-U).
    PERFIL_ACTUALIZADO = "profile.updated"
    #: Se creo una etiqueta (B.11).
    ETIQUETA_CREADA = "tag.created"
    #: Se renombro una etiqueta (B.11).
    ETIQUETA_ACTUALIZADA = "tag.updated"
    #: Se elimino una etiqueta; el contenido asociado se **desasocia**, no se
    #: borra (B.11).
    ETIQUETA_ELIMINADA = "tag.deleted"
    #: Se cargo una imagen (B.4).
    MEDIO_CARGADO = "media.uploaded"
    #: Se elimino una imagen que no estaba en uso (B.5).
    MEDIO_ELIMINADO = "media.deleted"


#: Tipo de entidad al que apuntan todos los eventos de autenticacion. Es el
#: administrador afectado, incluso cuando no se sabe quien es.
ENTIDAD_ADMINISTRADOR: Final = "administrator"

#: Tipos de entidad de los cuatro contenidos publicables.
#:
#: Son los **mismos literales** que `RepositorioDeMediosSQL.usos_de` devuelve
#: para decir donde se usa una imagen (`Task/010`). Que la auditoria usara otros
#: nombres para las mismas cosas obligaria a traducir entre dos vocabularios
#: internos sin ninguna ganancia.
ENTIDAD_ARTICULO: Final = "post"
ENTIDAD_REVIEW: Final = "book_review"
ENTIDAD_VIDEO: Final = "video"
ENTIDAD_PROYECTO: Final = "project"

#: Perfil singleton. Sin `slug`: no se navega por URL propia.
ENTIDAD_PERFIL: Final = "profile"

#: Etiqueta de clasificacion.
ENTIDAD_ETIQUETA: Final = "tag"

#: Imagen del almacenamiento de objetos. Se nombra en singular, como
#: `administrator`, y no como su tabla.
ENTIDAD_MEDIO: Final = "media_asset"

#: Los cuatro tipos publicables, para las comprobaciones que necesiten
#: recorrerlos. No es la fuente de los literales: lo son las constantes.
ENTIDADES_DE_CONTENIDO: Final[frozenset[str]] = frozenset(
    {ENTIDAD_ARTICULO, ENTIDAD_REVIEW, ENTIDAD_VIDEO, ENTIDAD_PROYECTO}
)
