"""Emision del enlace de acceso a un medio.

Es la pieza que cierra **D-009-O**: `Task/009` dejo `MedioPublico` sin campo de
acceso porque la forma de ese acceso —bucket privado, URL prefirmada,
expiracion— era de `Task/010`.

Que decide `Task/010` y que sigue siendo de `Task/030` (**D-08**)
-----------------------------------------------------------------

| Aqui, en `Task/010` | En `Task/030` |
| --- | --- |
| El acceso existe y es un enlace **temporal**, para el original y —desde
`Task/016`— para la miniatura | Si ademas hay una URL **estable** |
| Se genera al servir y **no** se persiste | La semantica de cache y el CDN |
| El TTL es **configuracion** (D-010-M) | El **valor** productivo del TTL |
| `object_key` no es un campo del contrato | Bucket, CORS y *lifecycle* |

Por que emitir un enlace por elemento no cuesta una llamada de red
------------------------------------------------------------------

Prefirmar es un HMAC sobre la peticion canonica: aritmetica local, sin ningun
viaje al almacenamiento. Un listado de doce articulos con portada emite doce
enlaces sin doce peticiones. Esta afirmado por prueba en
`tests/unit/test_adaptadores_de_almacenamiento.py`, apuntando a un puerto
cerrado: si hubiera E/S, fallaria.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import Depends

from app.modules.media.domain.claves import clave_de_la_miniatura
from app.modules.media.infrastructure.models import MediaAsset
from app.shared.configuration import Settings, get_settings
from app.shared.storage import ObjectStorage
from app.shared.storage.fabrica import obtener_almacenamiento


class AccesoAMedios:
    """Convierte la clave de un medio en un enlace utilizable."""

    def __init__(self, *, almacenamiento: ObjectStorage, duracion: timedelta) -> None:
        self._almacenamiento = almacenamiento
        self._duracion = duracion

    def url_de(self, medio: MediaAsset) -> str:
        """Enlace temporal de lectura del **original** del medio."""
        return self._almacenamiento.acceso_temporal(medio.object_key, duracion=self._duracion).url

    def url_de_la_miniatura(self, medio: MediaAsset) -> str:
        """Enlace temporal de lectura de la **miniatura** del medio.

        Anadido por `Task/016` (requisito P-04), que cierra la deuda 2 de
        `Task/010`: la miniatura se generaba y se almacenaba desde entonces, pero
        no se exponia. Se expone ahora porque ahora hay un consumidor real —los
        listados publicos, que descargaban el original para pintarlo pequeno—.

        La clave **se deriva** de la del original (decision D-010-I): la
        miniatura no es una fila, asi que esto no consulta la base de datos ni
        exige ninguna columna nueva.

        **Es un enlace temporal, igual que el del original.** No es una URL
        estable de medios: eso es la pregunta abierta de **D-08**, propiedad de
        `Task/030`, y esta tarea no la responde. Prefirmar es aritmetica local,
        asi que emitir dos enlaces por medio no anade ningun viaje de red.
        """
        clave = clave_de_la_miniatura(medio.object_key)
        return self._almacenamiento.acceso_temporal(clave, duracion=self._duracion).url


def obtener_acceso_a_medios(
    configuracion: Annotated[Settings, Depends(get_settings)],
) -> AccesoAMedios:
    """Dependencia de FastAPI que entrega el emisor de enlaces.

    Es el unico punto donde el *wiring* del almacenamiento toca la capa HTTP.
    `app/main.py` no se convierte en un contenedor de dependencias: la
    aplicacion sigue componiendose con el mecanismo del framework, como exige el
    principio 6 de software-architecture.md.

    El almacenamiento se memoriza por configuracion (`obtener_almacenamiento`),
    asi que esta dependencia no construye un cliente del SDK por peticion.
    """
    return AccesoAMedios(
        almacenamiento=obtener_almacenamiento(configuracion),
        duracion=timedelta(seconds=configuracion.storage_access_ttl_seconds),
    )


#: Alias para las firmas de los endpoints, que ya son largas de por si.
AccesoAMediosDependencia = Annotated[AccesoAMedios, Depends(obtener_acceso_a_medios)]
