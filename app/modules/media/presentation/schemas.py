"""Representacion publica de una referencia a un medio (decision D-009-O).

Que se expone hoy, y por que exactamente esto
---------------------------------------------

| Campo | Motivo |
| --- | --- |
| `alt_text` | Accesibilidad (requisito A-04). Sin el, la imagen no puede describirse |
| `width`, `height` | Permiten reservar el espacio antes de cargar la imagen |

Que **no** se expone
--------------------

- **`object_key`.** La invariante 9 de CONTENT_MODEL.md prohibe exponer claves
  de objeto *"sin control"*, y publicarla la convertiria ademas en parte del
  contrato `v1`, del que ya no podria retirarse (api-contracts.md seccion 10,
  regla 2).
- **Una URL construida a mano.** Seria inventarla. En produccion el bucket es
  privado y el acceso ocurre por URL prefirmada con expiracion: generarla es de
  **`Task/010`**, y persistir una estaria prohibido porque caduca.
- **`id`, `mime_type`, `size_bytes`, `checksum`, `original_filename`.** Son
  metadatos de gestion, propios de la biblioteca de medios administrativa.

Por que existe el objeto aunque todavia no lleve URL
-----------------------------------------------------

Omitir la portada por completo hasta `Task/010` obligaria despues a introducir
un campo nuevo en la raiz de cinco DTO. Con el objeto anidado ya presente,
`Task/010` solo tiene que **anadir** su campo de acceso, y anadir un campo
opcional no es un cambio incompatible (api-contracts.md seccion 10, regla 3).
La frontera queda declarada en lugar de bloquear la API publica entera.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.media.infrastructure.models import MediaAsset


class MedioPublico(BaseModel):
    """Metadatos publicos de una imagen asociada a un contenido."""

    alt_text: str | None = Field(
        default=None, description="Texto alternativo para lectores de pantalla."
    )
    width: int | None = Field(default=None, description="Ancho en pixeles, si se conoce.")
    height: int | None = Field(default=None, description="Alto en pixeles, si se conoce.")

    @classmethod
    def de_modelo(cls, medio: MediaAsset | None) -> MedioPublico | None:
        """Construye la representacion publica, o `None` si no hay medio."""
        if medio is None:
            return None
        return cls(alt_text=medio.alt_text, width=medio.width, height=medio.height)
