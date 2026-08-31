"""Claves de objeto de un medio.

Formato (decision D-010-G):

```
medios/<uuid4>/original.<ext>
medios/<uuid4>/thumbnail.webp
```

Tres propiedades, y las tres son deliberadas:

**No es predecible.** El UUID v4 aporta 122 bits aleatorios. `software-
architecture.md` seccion 3.7 lo pide con esas palabras —"nombres de objeto no
predecibles, para que conocer una URL no permita adivinar otras"— y es lo unico
que impide enumerar el bucket a partir de un enlace filtrado.

**El nombre original no participa.** Ni sanitizado ni codificado: no es un
argumento de esta funcion. Un `../../etc/passwd` no puede escapar del prefijo
porque nunca llega hasta aqui. La alternativa habitual —limpiar el nombre y
conservarlo— obliga a razonar sobre travesia de rutas, separadores de Windows,
bytes nulos y codificaciones dobles; no aceptarlo elimina la categoria entera de
defectos. El nombre original **si** se conserva, como metadato informativo, en
`media_assets.original_filename`.

**La miniatura se deriva.** Comparte el prefijo del original y solo cambia el
nombre del objeto, asi que conocer `object_key` basta para alcanzarla. Por eso
no hace falta ni una columna ni una tabla para ella (decision D-010-I), y por
eso `Task/010` no modifica el esquema fisico.

No hay prefijo por fecha. Solo serviria a una regla de *lifecycle*, que es de
`Task/030`; anadirlo ahora seria disenar para una politica que todavia no
existe.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

#: Prefijo comun de todos los medios del blog.
PREFIJO_DE_MEDIOS: Final = "medios"

#: Nombre del objeto original dentro de su carpeta.
NOMBRE_DEL_ORIGINAL: Final = "original"

#: Nombre y formato del derivado. Uno solo, sea cual sea el formato de origen
#: (decision D-010-H).
NOMBRE_DE_LA_MINIATURA: Final = "thumbnail"
EXTENSION_DE_LA_MINIATURA: Final = "webp"

#: Limite de `media_assets.object_key` (data-model.md seccion 4.1). El formato
#: de arriba produce claves de unos 55 caracteres, asi que hay holgura de sobra;
#: la constante existe para que la prueba compare contra el limite real de la
#: columna y no contra un numero copiado.
LONGITUD_MAXIMA_DE_CLAVE: Final = 512


@dataclass(frozen=True, slots=True)
class ClavesDelMedio:
    """Las dos claves que produce una subida."""

    original: str
    miniatura: str


def generar_claves(*, extension: str) -> ClavesDelMedio:
    """Genera un par de claves nuevo.

    `extension` procede del **formato validado** de la imagen, nunca del nombre
    que declaro el cliente: un archivo llamado `foto.jpg` que en realidad es un
    PNG recibe la extension `png`.
    """
    carpeta = f"{PREFIJO_DE_MEDIOS}/{uuid.uuid4()}"
    return ClavesDelMedio(
        original=f"{carpeta}/{NOMBRE_DEL_ORIGINAL}.{extension}",
        miniatura=f"{carpeta}/{NOMBRE_DE_LA_MINIATURA}.{EXTENSION_DE_LA_MINIATURA}",
    )


def clave_de_la_miniatura(clave_del_original: str) -> str:
    """Deriva la clave de la miniatura a partir de la del original.

    Lo necesita todo lo que parte de un `MediaAsset` ya persistido —el borrado,
    la compensacion— y solo dispone de su `object_key`.
    """
    carpeta = clave_del_original.rsplit("/", 1)[0]
    return f"{carpeta}/{NOMBRE_DE_LA_MINIATURA}.{EXTENSION_DE_LA_MINIATURA}"
