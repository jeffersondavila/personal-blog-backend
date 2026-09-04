"""Envoltura administrativa de los casos de uso de medios (`Task/012`).

Que aportan estas dos clases y que **no**
------------------------------------------

Aportan **una** cosa: el evento de auditoria. Todo lo demas —validar la imagen
decodificandola, derivar la miniatura, generar una clave no predecible,
compensar un fallo parcial, comprobar los cinco origenes de uso y borrar en el
orden correcto— es de `Task/010`, y se invoca tal cual. `data-model.md`,
invariante 12, ya lo repartia asi: el comportamiento vive alli y *"`Task/012` lo
expondra por HTTP"*.

Por que la auditoria no se metio dentro de `SubirImagen`
---------------------------------------------------------

Porque `Task/010` esta **aprobada** y su caso de uso declara por escrito lo que
no hace: *"no expone HTTP —eso es `Task/012`—, no comprueba permisos
—`Task/011`—"*. Un evento de auditoria necesita saber **quien** actuo y **desde
que peticion**, que son datos de la sesion y del transporte; meterlos ahi
obligaria a que un caso de uso de almacenamiento conociera ambas cosas.

Componer es la alternativa barata: estas clases reciben el caso de uso ya
construido y le anaden el rastro. Si manana la carga cambia, cambia en un solo
sitio y aqui no hay nada que tocar.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.modules.audit.domain.acciones import ENTIDAD_MEDIO, AccionAuditada
from app.modules.audit.domain.puertos import ContextoDeAuditoria, RegistroDeAuditoria
from app.modules.media.application.eliminar_medio import EliminarMedio
from app.modules.media.application.subir_imagen import SubirImagen


@dataclass(frozen=True, slots=True)
class ArchivoRecibido:
    """El archivo tal como llego, ya leido en memoria.

    Se lee entero antes de llamar al caso de uso porque la validacion de
    `Task/010` **decodifica** la imagen, y decodificar exige tener los bytes. El
    limite de tamano lo aplica esa misma validacion (5 MiB), asi que no hay
    ninguna ruta por la que un archivo mayor llegue a almacenarse.
    """

    contenido: bytes
    nombre: str
    alt_text: str | None


class SubirMedioAdministrativo:
    """Carga una imagen (flujo B.4) y deja constancia en el historial."""

    def __init__(self, *, caso_de_uso: SubirImagen, auditoria: RegistroDeAuditoria) -> None:
        self._caso_de_uso = caso_de_uso
        self._auditoria = auditoria

    def __call__(
        self, *, archivo: ArchivoRecibido, actor_id: uuid.UUID, contexto: ContextoDeAuditoria
    ) -> uuid.UUID:
        """Sube la imagen y devuelve el identificador del medio registrado.

        El evento se escribe **despues** de la carga: si la validacion o el
        almacenamiento fallan, no ha pasado nada que auditar.
        """
        subido = self._caso_de_uso(
            contenido=archivo.contenido,
            nombre_original=archivo.nombre,
            alt_text=archivo.alt_text,
        )
        self._auditar(AccionAuditada.MEDIO_CARGADO, subido.id, archivo.nombre, actor_id, contexto)
        return subido.id

    def _auditar(
        self,
        accion: AccionAuditada,
        identificador: uuid.UUID,
        nombre: str,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> None:
        self._auditoria.registrar(
            accion.value,
            entidad=ENTIDAD_MEDIO,
            actor_id=actor_id,
            entidad_id=identificador,
            request_id=contexto.request_id,
            ip=contexto.origen,
            # El nombre original y nada mas (decision D-012-O). Es lo unico que
            # permite reconocer la imagen en el historial cuando la fila ya no
            # existe. **No** la clave del objeto: es interna, y un historial no
            # es sitio para repetirla (invariante 9 de CONTENT_MODEL.md).
            metadatos={"original_filename": nombre},
        )


class EliminarMedioAdministrativo:
    """Elimina una imagen que no este en uso (flujo B.5) y lo audita."""

    def __init__(self, *, caso_de_uso: EliminarMedio, auditoria: RegistroDeAuditoria) -> None:
        self._caso_de_uso = caso_de_uso
        self._auditoria = auditoria

    def __call__(
        self,
        *,
        identificador: uuid.UUID,
        nombre_original: str,
        actor_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> None:
        """Deja constancia **y despues** borra el medio. El orden es la regla.

        El nombre llega desde fuera porque despues del borrado ya no se puede
        leer, y un historial que no dijera **que** se borro no serviria de nada.
        Un rechazo por medio en uso lanza dentro del caso de uso, asi que no deja
        evento: el historial registra lo que paso, no lo que se intento.

        Por que se audita ANTES de borrar
        ---------------------------------

        Porque PostgreSQL revierte y el almacenamiento **no**, y con el orden
        contrario esa asimetria produce el unico estado que `Task/010` declaro
        inaceptable.

        `EliminarMedio` borra la fila y **despues** los objetos, y eligio ese
        orden a proposito (**D-010-P**): de los dos estados a medias posibles,
        *objetos sin fila* es basura recuperable y *fila sin objetos* es **una
        imagen rota en el blog publicado**. Pero ese borrado de fila queda en un
        `flush`, no confirmado. Si la auditoria fallara despues, la transaccion
        de la peticion revertiria y **la fila volveria**, mientras que los
        objetos de MinIO ya no: exactamente la fila-sin-objetos que aquel orden
        existia para evitar.

        Auditando primero, un fallo del historial ocurre **antes** de tocar nada:
        no hay fila borrada ni objeto perdido, y la peticion revierte entera. Y
        si lo que falla es el borrado, la transaccion se lleva tambien el evento,
        asi que tampoco queda rastro de algo que no ocurrio.

        Es el mismo orden —y por la misma razon— que usa `EliminarEtiqueta`. La
        correccion vive **aqui**, en la frontera de composicion que introdujo
        `Task/012`, y no toca `Task/010`: su caso de uso, su orden interno y su
        compensacion quedan intactos.
        """
        self._auditoria.registrar(
            AccionAuditada.MEDIO_ELIMINADO.value,
            entidad=ENTIDAD_MEDIO,
            actor_id=actor_id,
            entidad_id=identificador,
            request_id=contexto.request_id,
            ip=contexto.origen,
            metadatos={"original_filename": nombre_original},
        )
        self._caso_de_uso(identificador)
