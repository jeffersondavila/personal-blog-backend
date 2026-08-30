"""Caso de uso: eliminar un medio (flujo B.5 de USER_FLOWS.md).

```
1. buscar el medio          -> no existe = ResourceNotFoundError
2. comprobar sus usos       -> hay usos = MedioEnUsoError, y no se toca nada
3. borrar la fila           -> falla = no se ha borrado ningun objeto
4. borrar los dos objetos
```

Por que este caso de uso es de `Task/010`
-----------------------------------------

`data-model.md`, invariante 12, se lo asigna por nombre: la base lo garantiza
con `ON DELETE RESTRICT`, *"y `Task/010`: comprobacion previa que dice **donde**
se usa (B.5)"*. `Task/012` expondra el `DELETE /api/v1/admin/media/{id}`; el
comportamiento vive aqui.

Por que la fila se borra antes que los objetos (decision D-010-P)
-----------------------------------------------------------------

Es la misma asimetria que en la subida, aplicada al reves. De los dos estados a
medias posibles hay que elegir el tolerable:

| Orden | Si falla a la mitad | Consecuencia |
| --- | --- | --- |
| Fila primero | Quedan objetos sin fila | Basura en el bucket: ocupa espacio y es recuperable |
| Objetos primero | Queda una fila sin objetos | **Imagen rota en el blog publicado** |

Se elige el primero. La comprobacion de uso ocurre antes que las dos cosas, asi
que un medio referenciado no llega a tocarse.

`eliminar` del almacenamiento es idempotente (decision D-010-C), de modo que
reintentar un borrado a medias termina el trabajo en lugar de fallar.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from app.modules.media.application.repositorio import RepositorioDeMediosCompleto
from app.modules.media.domain.claves import clave_de_la_miniatura
from app.modules.media.domain.errores import MedioEnUsoError
from app.shared.errors.exceptions import ResourceNotFoundError
from app.shared.storage import ObjectStorage


class EliminarMedio:
    """Elimina un medio y sus objetos, si no esta en uso."""

    def __init__(
        self, *, almacenamiento: ObjectStorage, repositorio: RepositorioDeMediosCompleto
    ) -> None:
        self._almacenamiento = almacenamiento
        self._repositorio = repositorio

    def __call__(self, identificador: uuid.UUID) -> None:
        """Ejecuta el borrado completo."""
        medio = self._repositorio.buscar(identificador)
        if medio is None:
            raise ResourceNotFoundError("El medio solicitado no existe.")

        usos = self._repositorio.usos_de(identificador)
        if usos:
            raise MedioEnUsoError(
                f"El medio esta en uso en {len(usos)} contenido(s) y no puede eliminarse.",
                usos=[asdict(uso) for uso in usos],
            )

        self._repositorio.eliminar(identificador)

        # Despues de la fila, y en este orden: la miniatura es un derivado, asi
        # que si algo quedara a medias es preferible que sea ella.
        self._almacenamiento.eliminar(clave_de_la_miniatura(medio.object_key))
        self._almacenamiento.eliminar(medio.object_key)
