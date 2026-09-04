"""Caso de uso: editar el perfil (flujo B.10 de USER_FLOWS.md).

Por que el modulo `profile` gana capa de aplicacion en `Task/012`
-----------------------------------------------------------------

`Task/009` no la creo, y con razon: leer el perfil no orquesta nada
(decision D-009-Q, y software-architecture.md seccion 3.2 prohibe las capas
vacias). Editarlo si: comprueba que el perfil existe, valida una referencia a
otro modulo, reemplaza una coleccion dependiente y escribe en el historial. Eso
es orquestacion con un limite transaccional, que es exactamente lo que esta capa
existe para albergar.

Lo que este caso de uso **no** hace
------------------------------------

**No crea el perfil.** Decision **D-012-U**, tomada de `data-model.md`
seccion 5, que lo asigna por nombre: *"El perfil no se crea ni se elimina por
API — `Task/012` — solo expone lectura y edicion"*. Crear el perfil real es de
`Task/036` (produccion) y sembrarlo en local, de `Task/022`. Un `PUT` sobre una
base sin perfil responde `404`, y **no deja ninguna fila detras**.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.modules.audit.domain.acciones import ENTIDAD_PERFIL, AccionAuditada
from app.modules.audit.domain.puertos import ContextoDeAuditoria, RegistroDeAuditoria
from app.modules.media.domain.texto_alternativo import texto_a_escribir
from app.shared.errors.exceptions import (
    MedioSinTextoAlternativoError,
    ReferenciaDesconocidaError,
    ResourceNotFoundError,
)


@dataclass(frozen=True, slots=True)
class EnlaceSocialParaGuardar:
    """Un enlace social, **sin su orden**.

    El orden no viaja aqui: lo da la posicion en la lista (decision D-012-Q).
    `uq_profile_social_links_profile_id_display_order` haria fallar dos enlaces
    con el mismo valor, y derivarlo del indice hace ese estado
    **irrepresentable** en lugar de detectarlo con un error.
    """

    label: str
    url: str


@dataclass(frozen=True, slots=True)
class DatosDelPerfil:
    """Representacion completa del perfil que se quiere dejar guardada.

    Es completa y no parcial porque el contrato usa `PUT` (decision D-012-C):
    lo que llega **es** el perfil resultante.
    """

    full_name: str
    headline: str | None
    biography: str
    contact_email: str | None
    photo_id: uuid.UUID | None
    #: Texto alternativo propuesto para la foto. Se escribe en el **primer uso**
    #: (decision D-012-Y): las fuentes dicen que `alt_text` se escribe al usar la
    #: imagen, no al cargarla.
    photo_alt_text: str | None
    seo_title: str | None
    seo_description: str | None
    social_links: tuple[EnlaceSocialParaGuardar, ...]


class RepositorioDelPerfil(Protocol):
    """Persistencia del perfil singleton.

    Habla de **datos**, no de modelos ORM: asi la capa de aplicacion no depende
    de SQLAlchemy (regla 9 de software-architecture.md seccion 3.5).
    """

    def identificador(self) -> uuid.UUID | None:
        """Identificador del unico perfil, o `None` si todavia no existe."""
        ...

    def medio_existe(self, identificador: uuid.UUID) -> bool:
        """Comprueba que la imagen referenciada existe."""
        ...

    def bloquear_texto_alternativo(self, identificador: uuid.UUID) -> str | None:
        """Lee el texto alternativo del medio **bloqueando su fila** (D-012-Y)."""
        ...

    def escribir_texto_alternativo(self, identificador: uuid.UUID, texto: str) -> None:
        """Persiste el texto alternativo del medio, en esta misma transaccion."""
        ...

    def guardar(self, perfil_id: uuid.UUID, datos: DatosDelPerfil) -> None:
        """Deja el perfil con exactamente estos valores y estos enlaces."""
        ...


class ActualizarPerfil:
    """Edita el perfil singleton y deja constancia en el historial."""

    def __init__(
        self, *, repositorio: RepositorioDelPerfil, auditoria: RegistroDeAuditoria
    ) -> None:
        self._repositorio = repositorio
        self._auditoria = auditoria

    def __call__(
        self,
        *,
        datos: DatosDelPerfil,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> uuid.UUID:
        """Guarda el perfil y devuelve su identificador.

        El orden importa: **primero se comprueba todo, despues se escribe**. Si
        la foto referenciada no existiera despues de haber guardado el resto, la
        peticion dejaria el perfil a medias — y aunque la transaccion de la
        peticion lo revertiria, dependeria de que nadie confirme por el camino.
        Comprobar antes no depende de nada.
        """
        perfil_id = self._repositorio.identificador()
        if perfil_id is None:
            raise ResourceNotFoundError("El recurso solicitado no existe.")

        if datos.photo_id is not None:
            if not self._repositorio.medio_existe(datos.photo_id):
                raise ReferenciaDesconocidaError(
                    "La imagen indicada no existe.",
                    campo="photo_id",
                    valores=[str(datos.photo_id)],
                )
            # Requisito A-04, en el perfil. No tiene `status`, asi que *"siempre
            # existe y siempre esta visible"* (CONTENT_MODEL.md seccion 2): no hay
            # un "publicar" posterior donde exigirlo, al contrario que en los
            # cuatro tipos publicables. Asignar la foto **es** usarla.
            #
            # Y usarla es tambien el momento de **escribir** el texto si la imagen
            # todavia no lo tiene (decision D-012-Y): las fuentes dicen que
            # `alt_text` se escribe al usar la imagen, no al cargarla, asi que
            # obligar a borrar y volver a cargarla para corregirlo seria lo
            # contrario de lo que dicen.
            # Lectura **con cerrojo**: sin el, dos ediciones simultaneas del
            # perfil podrian fijar textos distintos para la misma imagen
            # (D-012-Y, D-012-Z).
            actual = self._repositorio.bloquear_texto_alternativo(datos.photo_id)
            escribir = texto_a_escribir(
                actual=actual, propuesto=datos.photo_alt_text, campo="photo_alt_text"
            )
            if escribir is not None:
                self._repositorio.escribir_texto_alternativo(datos.photo_id, escribir)
            elif not (actual and actual.strip()):
                raise MedioSinTextoAlternativoError(
                    "La imagen indicada no tiene texto alternativo, y el perfil es "
                    "siempre visible. Indicalo en `photo_alt_text`.",
                    campo="photo_id",
                    valor=str(datos.photo_id),
                )

        self._repositorio.guardar(perfil_id, datos)
        self._auditoria.registrar(
            AccionAuditada.PERFIL_ACTUALIZADO.value,
            entidad=ENTIDAD_PERFIL,
            actor_id=actor_id,
            entidad_id=perfil_id,
            request_id=contexto.request_id,
            ip=contexto.origen,
            # Sin metadatos (decision D-012-O). Lo unico que podria ponerse aqui
            # —los valores nuevos— incluye la biografia en Markdown, que
            # CONTENT_MODEL.md 3.9 excluye del historial. Que el perfil se edito
            # ya lo dice la accion, y quien lo hizo, `actor_id`.
        )
        return perfil_id
