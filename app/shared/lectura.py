"""Tiempo estimado de lectura de un contenido.

Es una **capacidad tecnica transversal** —contar palabras de una cadena— sin
ninguna regla de negocio, que es la condicion para vivir en `app/shared`
(software-architecture.md seccion 3.4). La usan los tres tipos que tienen
contenido en Markdown: `Post`, `BookReview` y `Project`. `Video` no lo tiene
(ADR-005, decision 7).

Por que se calcula y no se guarda
---------------------------------

`data-model.md` (decision D-O) lo decidio en `Task/008`: `reading_time` y
`thumbnail_url` **no se persisten**. Ambos son derivables, y persistirlos crea
un segundo estado que queda obsoleto en cuanto se edita el original. Se calculan
**al servir**, aqui.

Que NO hace esta funcion
------------------------

No renderiza Markdown ni lo interpreta. `Task/009` no es un renderer (ADR-005):
el render y la sanitizacion son de `Task/014` y `Task/015`. La sintaxis Markdown
se cuenta como parte del texto, y eso es aceptable porque el resultado es una
**estimacion** que se presenta redondeada a minutos: descontar los guiones de
una lista no cambiaria el numero que ve el lector.
"""

from __future__ import annotations

from typing import Final

#: Velocidad de lectura asumida. Valor convencional para prosa tecnica; se
#: declara como constante para que la prueba lo use en lugar de repetirlo, y
#: para que cambiarlo sea una decision visible y no un numero suelto.
PALABRAS_POR_MINUTO: Final[int] = 200


def minutos_de_lectura(contenido: str) -> int:
    """Minutos estimados de lectura, redondeados hacia arriba.

    Devuelve `0` solo cuando no hay nada que leer. Para cualquier contenido no
    vacio devuelve al menos `1`: anunciar "0 minutos" de un texto que existe
    seria falso, y el redondeo hacia arriba evita quedarse corto.
    """
    palabras = len(contenido.split())
    if palabras == 0:
        return 0
    return -(-palabras // PALABRAS_POR_MINUTO)
