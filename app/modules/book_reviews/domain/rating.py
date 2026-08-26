"""Valoracion de una review de libro.

CONTENT_MODEL.md seccion 3.3 dejaba **abierta** la escala exacta y encargaba
cerrarla a `Task/008`. Queda fijada aqui:

> **Entero de 1 a 5, ambos inclusive.**

Por que 1..5 y no otra escala
-----------------------------

Es la escala que el lector reconoce sin leyenda —la de las estrellas— y la que
el sitio publico muestra en los listados de reviews (USER_FLOWS.md A.4). Una
escala de 1 a 10 obliga a explicar si 7 es bueno; media estrella multiplica los
valores sin anadir informacion real sobre un libro. El MVP asumia ya "un entero
acotado": esto solo fija el acotamiento.

Donde vive la regla
-------------------

Aqui y en PostgreSQL, y en cada sitio por un motivo distinto:

- **Dominio:** rechaza el valor en el momento de construirlo, sin base de datos
  de por medio, y con un error de la aplicacion que la API sabra traducir.
- **PostgreSQL:** *check constraint* real, ultima linea de defensa frente a
  cualquier camino que no pase por el dominio (una carga manual, una migracion
  futura, un `UPDATE` directo).

No es duplicacion sin proposito: cada capa protege de algo distinto
(BACKEND_TESTING_STRATEGY.md seccion 8.3).

La valoracion es **opcional en la base de datos**: un borrador puede existir
antes de que su autor decida la nota (USER_FLOWS.md B.2 solo exige el titulo).
Que una review **publicada** deba tenerla es una validacion de publicacion, y
pertenece a `Task/012`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.shared.errors.exceptions import ValidationFailedError

#: Extremos de la escala, ambos inclusive.
RATING_MINIMO: Final[int] = 1
RATING_MAXIMO: Final[int] = 5


class InvalidRatingError(ValidationFailedError):
    """La valoracion recibida no pertenece a la escala del proyecto."""

    code = "invalid_rating"


@dataclass(frozen=True, slots=True)
class Rating:
    """Valoracion de una review: entero de 1 a 5, inmutable."""

    value: int

    def __post_init__(self) -> None:
        if not RATING_MINIMO <= self.value <= RATING_MAXIMO:
            raise InvalidRatingError(
                f"La valoracion debe estar entre {RATING_MINIMO} y {RATING_MAXIMO}, "
                "ambos inclusive.",
            )

    @classmethod
    def of(cls, value: object) -> Rating:
        """Construye una valoracion a partir de un valor no confiable.

        Es la puerta de entrada para datos que vienen de fuera del proceso —una
        peticion HTTP, un formulario, una importacion—, donde el tipo todavia no
        esta garantizado.

        `bool` se rechaza de forma explicita: en Python es una subclase de `int`,
        asi que `True` pasaria por un 1 y `False` por un 0 sin este control.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidRatingError("La valoracion debe ser un numero entero.")
        return cls(value=value)
