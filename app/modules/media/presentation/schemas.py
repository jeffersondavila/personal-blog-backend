"""Representacion publica de una referencia a un medio.

Decision **D-009-O** (`Task/009`), **completada por `Task/010`** con el campo de
acceso que aquella tarea dejo explicitamente pendiente.

Que se expone, y por que exactamente esto
------------------------------------------

| Campo | Motivo |
| --- | --- |
| `alt_text` | Accesibilidad (requisito A-04). Sin el, la imagen no puede describirse |
| `width`, `height` | Permiten reservar el espacio antes de cargar la imagen |
| `access_url` | El enlace con el que se descarga la imagen (`Task/010`) |
| `thumbnail_access_url` | El enlace de la **miniatura**, para listados (P-04) |

Que **no** se expone
--------------------

- **`object_key`.** La invariante 9 de CONTENT_MODEL.md prohibe exponer claves
  de objeto *"sin control"*, y publicarla la convertiria ademas en parte del
  contrato `v1`, del que ya no podria retirarse (api-contracts.md seccion 10,
  regla 2). El enlace de acceso la lleva firmada dentro, que es distinto:
  caduca, y no revela la clave como dato reutilizable del contrato.
- **`access_expires_at`.** Se evaluo y se descarto (decision D-010-L): declarar
  cuando caduca el enlace es describir su **semantica de cache**, que es
  literalmente una de las preguntas que **D-08** deja para `Task/030`. Anadirlo
  despues seria compatible; retirarlo, no.
- **`id`, `mime_type`, `size_bytes`, `checksum`, `original_filename`.** Son
  metadatos de gestion, propios de la biblioteca de medios administrativa
  (`Task/012`).

Por que la miniatura NO expone sus dimensiones
----------------------------------------------

La miniatura **no** es una fila: su clave se deriva de la del original (decision
D-010-I) y sus dimensiones no se persisten. `width` y `height` son los del
**original**, y sirven igual para reservar el espacio, porque la miniatura
conserva la proporcion (D-010-H: `thumbnail` nunca amplia). Derivarlas aqui seria
reimplementar el redimensionado en el DTO.

Y por que **no** es una URL estable
------------------------------------

`thumbnail_access_url` es tan temporal como `access_url`: se firma al servir y
caduca. Que exista una URL **estable** de medios sigue siendo la pregunta abierta
de **D-08**, propiedad de `Task/030`. Este campo no la responde y no debe usarse
como si lo hiciera — en particular, **no** vale como `og:image`.

Por que `access_url` es opcional en el esquema
----------------------------------------------

El campo se declara `str | None` porque el objeto entero puede ser `null` cuando
el contenido no tiene portada, y porque un contrato que promete siempre una URL
obligaria a fallar la peticion entera si el almacenamiento no pudiera firmarla.
En la practica, cuando hay medio hay enlace: prefirmar es una operacion local.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.modules.media.infrastructure.models import MediaAsset

if TYPE_CHECKING:  # pragma: no cover - solo para el tipado estatico
    from app.modules.media.presentation.acceso import AccesoAMedios


class MedioPublico(BaseModel):
    """Metadatos publicos de una imagen asociada a un contenido."""

    alt_text: str | None = Field(
        default=None, description="Texto alternativo para lectores de pantalla."
    )
    width: int | None = Field(default=None, description="Ancho en pixeles, si se conoce.")
    height: int | None = Field(default=None, description="Alto en pixeles, si se conoce.")
    access_url: str | None = Field(
        default=None,
        description=(
            "Enlace temporal de lectura de la imagen. Se genera al servir la respuesta y "
            "caduca: no debe almacenarse ni tratarse como identificador estable."
        ),
    )
    thumbnail_access_url: str | None = Field(
        default=None,
        description=(
            "Enlace temporal de lectura de la miniatura, para listados (requisito P-04). "
            "Misma naturaleza que `access_url`: se genera al servir y caduca. **No** es una "
            "URL estable de medios; eso sigue siendo la decision abierta D-08."
        ),
    )

    @classmethod
    def de_modelo(cls, medio: MediaAsset | None, acceso: AccesoAMedios) -> MedioPublico | None:
        """Construye la representacion publica, o `None` si no hay medio.

        `acceso` es un argumento obligatorio y no un valor por defecto: un DTO
        que pudiera construirse sin el emitiria medios sin enlace en silencio, y
        el defecto solo se veria en la respuesta.
        """
        if medio is None:
            return None
        return cls(
            alt_text=medio.alt_text,
            width=medio.width,
            height=medio.height,
            access_url=acceso.url_de(medio),
            thumbnail_access_url=acceso.url_de_la_miniatura(medio),
        )
