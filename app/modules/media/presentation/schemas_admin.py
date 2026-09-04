"""Representacion **administrativa** de un medio (`Task/012`).

Por que no basta con `MedioPublico`
------------------------------------

`MedioPublico` responde a la pregunta del visitante —*como muestro esta
imagen*— y por eso lleva exactamente cuatro campos. El administrador tiene otra
pregunta: *cual de mis imagenes es esta*. Para elegir una portada de la
biblioteca (USER_FLOWS.md B.5) necesita distinguirlas, y para eliminarla
necesita su identificador.

Cada campo adicional se justifica, que es lo que exige el alcance de la tarea:

| Campo | Por que esta aqui y no en el contrato publico |
| --- | --- |
| `id` | Es lo que se envia como `cover_id` y lo que identifica la ruta de borrado (D-012-I) |
| `original_filename` | Es como el administrador reconoce el archivo que subio |
| `mime_type`, `size_bytes` | La biblioteca los muestra para decidir que conservar |
| `checksum` | Ver abajo |
| `created_at` | MVP_SCOPE.md 3.1: *"consultar fechas de creacion y actualizacion"* |

**Sobre `checksum`.** `data-model.md` 4.1 dice que `Task/010` lo calcula pero
**no deduplica**, y deja a `Task/012` *"presentar el duplicado al
administrador"*. Exponerlo es lo minimo que permite hacerlo: el panel agrupa por
checksum sin que el backend decida por nadie reutilizar un medio, que es
justamente lo que D-010-J rechazo.

Lo que **sigue sin salir**, tambien aqui
-----------------------------------------

**`object_key`.** La invariante 9 de CONTENT_MODEL.md prohibe exponer claves de
objeto sin control, y no hace ninguna excepcion para el administrador. Tampoco
la necesita: nada de lo que el panel hace requiere la clave — la imagen se ve
con `access_url`, se elige por `id` y se borra por `id`. Publicarla solo
anadiria una ruta por la que puede filtrarse.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.modules.media.infrastructure.models import MediaAsset

if TYPE_CHECKING:  # pragma: no cover - solo para el tipado estatico
    from app.modules.media.presentation.acceso import AccesoAMedios


class MedioAdministrativo(BaseModel):
    """Imagen tal como la ve el administrador en su biblioteca."""

    id: uuid.UUID = Field(description="Identificador interno; es lo que se usa como referencia.")
    original_filename: str = Field(description="Nombre con el que se subio el archivo.")
    mime_type: str = Field(description="Tipo MIME **validado por decodificacion** (`Task/010`).")
    size_bytes: int = Field(description="Tamano en bytes del original almacenado.")
    width: int | None = Field(default=None, description="Ancho en pixeles.")
    height: int | None = Field(default=None, description="Alto en pixeles.")
    alt_text: str | None = Field(default=None, description="Texto alternativo (A-04).")
    checksum: str | None = Field(
        default=None,
        description=(
            "SHA-256 de los bytes almacenados. El backend **no deduplica**; sirve para que "
            "el panel pueda senalar una carga repetida."
        ),
    )
    created_at: datetime = Field(description="Fecha de carga, en UTC.")
    access_url: str | None = Field(
        default=None,
        description=(
            "Enlace temporal de lectura. Se genera al servir y caduca: no debe almacenarse."
        ),
    )

    @classmethod
    def de_modelo(cls, medio: MediaAsset, acceso: AccesoAMedios) -> MedioAdministrativo:
        """Proyecta el modelo ORM sobre los campos administrativos."""
        return cls(
            id=medio.id,
            original_filename=medio.original_filename,
            mime_type=medio.mime_type,
            size_bytes=medio.size_bytes,
            width=medio.width,
            height=medio.height,
            alt_text=medio.alt_text,
            checksum=medio.checksum,
            created_at=medio.created_at,
            access_url=acceso.url_de(medio),
        )

    @classmethod
    def opcional(
        cls, medio: MediaAsset | None, acceso: AccesoAMedios
    ) -> MedioAdministrativo | None:
        """Igual, pero admite la ausencia de medio.

        `acceso` es obligatorio y no un valor por defecto: un DTO que pudiera
        construirse sin el emitiria medios sin enlace en silencio.
        """
        if medio is None:
            return None
        return cls.de_modelo(medio, acceso)
