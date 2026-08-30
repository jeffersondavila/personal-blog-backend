"""Caso de uso: subir una imagen (flujo B.4 de USER_FLOWS.md).

```
1. validar la imagen        -> falla aqui = no se ha tocado nada
2. derivar la miniatura     -> falla aqui = no se ha tocado nada
3. generar las claves
4. guardar el original      -> falla = nada escrito, nada en la base
5. guardar la miniatura     -> falla = se borra el original
6. persistir el MediaAsset  -> falla = se borran las dos claves
```

Por que este orden (decision D-010-P)
-------------------------------------

**No existe transaccion entre PostgreSQL y el almacenamiento de objetos.** No es
un detalle que se pueda posponer: es la propiedad que decide el diseno. Sin
transaccion comun, cualquier orden deja una ventana en la que un fallo produce
un estado a medias, y lo unico que se puede elegir es **cual** de los dos
estados a medias es tolerable.

- **Validar y derivar primero** significa que un archivo invalido no llega a
  escribir nada, asi que no hay nada que compensar en el caso mas frecuente.
- **Persistir al ultimo** significa que la fila —el indice de lo que existe— es
  el ultimo paso. Un fallo antes deja, como mucho, objetos huerfanos; nunca una
  fila que apunte a un objeto que no esta. Es la asimetria correcta: un objeto
  sin fila es basura que ocupa espacio, y una fila sin objeto es una imagen rota
  en el blog publicado.
- **La compensacion borra en orden inverso** y es *best effort*: si tambien
  falla, se **registra** y se propaga el error **original**, porque es el que
  explica lo que paso.

Lo que este caso de uso **no** hace: no expone HTTP —eso es `Task/012`—, no
comprueba permisos —`Task/011`— y no deduplica por `checksum` (decision
D-010-J).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.modules.media.application.repositorio import MedioParaRegistrar, RepositorioDeMedios
from app.modules.media.domain.claves import generar_claves
from app.modules.media.domain.miniaturas import generar_miniatura
from app.modules.media.domain.validacion import validar_imagen
from app.shared.logging import get_logger
from app.shared.storage import ObjectStorage

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MedioSubido:
    """Resultado de la subida.

    No lleva URL: el enlace de acceso se genera al servir, con su expiracion, y
    quien lo necesite lo pide entonces.
    """

    id: uuid.UUID
    object_key: str
    clave_de_la_miniatura: str
    mime_type: str
    width: int
    height: int
    size_bytes: int
    checksum: str


class SubirImagen:
    """Valida una imagen, la almacena con su miniatura y registra sus metadatos."""

    def __init__(self, *, almacenamiento: ObjectStorage, repositorio: RepositorioDeMedios) -> None:
        self._almacenamiento = almacenamiento
        self._repositorio = repositorio

    def __call__(
        self, *, contenido: bytes, nombre_original: str, alt_text: str | None = None
    ) -> MedioSubido:
        """Ejecuta la subida completa.

        `alt_text` es opcional (decision D-010-N): `data-model.md` dice que se
        escribe **al usar** la imagen, no al subirla, y el flujo B.4 no lo pide.
        Exigirlo aqui obligaria a inventar un texto alternativo antes de saber
        en que contenido va a aparecer la imagen.
        """
        validada = validar_imagen(contenido)
        miniatura = generar_miniatura(validada)
        claves = generar_claves(extension=validada.extension)

        self._almacenamiento.guardar(
            clave=claves.original,
            contenido=validada.contenido,
            tipo_de_contenido=validada.mime_type,
        )

        try:
            self._almacenamiento.guardar(
                clave=claves.miniatura,
                contenido=miniatura.contenido,
                tipo_de_contenido=miniatura.mime_type,
            )
        except Exception as error:
            self._compensar(claves.original, motivo=error)
            raise

        try:
            identificador = self._repositorio.registrar(
                MedioParaRegistrar(
                    object_key=claves.original,
                    original_filename=nombre_original,
                    mime_type=validada.mime_type,
                    size_bytes=validada.size_bytes,
                    width=validada.width,
                    height=validada.height,
                    checksum=validada.checksum,
                    alt_text=alt_text,
                )
            )
        except Exception as error:
            self._compensar(claves.miniatura, claves.original, motivo=error)
            raise

        return MedioSubido(
            id=identificador,
            object_key=claves.original,
            clave_de_la_miniatura=claves.miniatura,
            mime_type=validada.mime_type,
            width=validada.width,
            height=validada.height,
            size_bytes=validada.size_bytes,
            checksum=validada.checksum,
        )

    def _compensar(self, *claves: str, motivo: BaseException) -> None:
        """Deshace lo ya escrito. Nunca sustituye al error que la provoco.

        Si la limpieza falla, se registra y se sigue: propagar el fallo de la
        compensacion taparia la causa real —el error `motivo`— y el diagnostico
        apuntaria al sitio equivocado. El registro es la unica pista de que
        quedan objetos huerfanos, asi que perderlo convertiria un incidente
        diagnosticable en uno invisible.
        """
        for clave in claves:
            try:
                self._almacenamiento.eliminar(clave)
            except Exception:
                _logger.exception(
                    "Fallo la compensacion de una subida: queda un objeto huerfano",
                    extra={"object_key": clave, "causa": type(motivo).__name__},
                )
