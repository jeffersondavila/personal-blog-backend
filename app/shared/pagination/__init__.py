"""Parametros, orden y envoltura de las colecciones paginadas.

Aplazado deliberadamente desde `Task/005` hasta que hubiera duplicacion real que
eliminar. `Task/009` la trae: seis listados publicos y una busqueda comparten la
misma envoltura, los mismos limites y las mismas reglas de orden.

**Lo que hay aqui es agnostico del modelo.** No conoce `Post`, ni `status`, ni
las tablas puente de etiquetado: recibe columnas y devuelve clausulas. Esa es la
condicion para que pueda vivir en `shared`, que tiene prohibido contener reglas
de negocio (software-architecture.md seccion 3.4).

**Lo que NO hay, y por que.** No hay constructor generico de consultas ni
repositorio universal. Un constructor que supiera filtrar por `status`,
`featured` y etiqueta tendria que conocer el modelo de contenido, es decir,
meteria negocio en `shared`. Cada modulo escribe su propia consulta y acepta la
duplicacion, que es el mismo criterio con el que `Task/008` decidio no crear una
superentidad `Content` (data-model.md, decision D-P).
"""

from app.shared.pagination.ordenacion import (
    ORDEN_POR_DEFECTO,
    OrdenPublico,
    clausula_de_orden,
)
from app.shared.pagination.pagina import Pagina, numero_de_paginas
from app.shared.pagination.parametros import (
    PAGE_SIZE_MAXIMO,
    PAGE_SIZE_POR_DEFECTO,
    ParametrosDePagina,
    parametros_de_pagina,
)

__all__ = [
    "ORDEN_POR_DEFECTO",
    "PAGE_SIZE_MAXIMO",
    "PAGE_SIZE_POR_DEFECTO",
    "OrdenPublico",
    "Pagina",
    "ParametrosDePagina",
    "clausula_de_orden",
    "numero_de_paginas",
    "parametros_de_pagina",
]
