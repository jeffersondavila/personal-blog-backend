"""Forma documentada de una respuesta de error.

Por que existe este modulo
--------------------------

El cuerpo de error ya lo construye `app.shared.errors.handlers`, y lo hace bien.
Lo que faltaba era **declararlo en OpenAPI**. FastAPI documenta por su cuenta un
`422` con su propia forma (`HTTPValidationError`, con una lista `detail`), pero
este proyecto responde con la envoltura comun de api-contracts.md seccion 7:

```json
{ "error": { "code": "...", "message": "...", "details": {}, "request_id": "..." } }
```

Sin declararlo, la especificacion describiria una respuesta que la API **no
devuelve**, y un cliente generado a partir de ella fallaria al leer el primer
error. `Task/009` deja OpenAPI coherente con lo que ocurre de verdad.

Estos modelos **solo documentan**: no participan en la construccion de la
respuesta, que sigue viviendo en un unico punto (`handlers`). Duplicar ahi la
serializacion crearia dos formas de error que podrian divergir.

No se reexportan desde `app.shared.errors`: ese paquete se importa desde el
dominio y su `__init__` se mantiene reducido a las excepciones, por la razon que
`Task/008` documento al retirar de el los manejadores.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DetalleDeError(BaseModel):
    """Contenido del objeto `error` de cualquier respuesta de error."""

    code: str = Field(
        description="Codigo estable y legible por maquina, por ejemplo `resource_not_found`.",
        examples=["resource_not_found"],
    )
    message: str = Field(
        description="Mensaje breve para humanos. Nunca incluye trazas ni detalles internos."
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Contexto estructurado adicional; en validacion, los campos afectados.",
    )
    request_id: str = Field(description="Correlation ID, para localizar la peticion en los logs.")


class RespuestaDeError(BaseModel):
    """Envoltura comun de error (api-contracts.md seccion 7)."""

    error: DetalleDeError


#: Respuestas de error que declaran **todos** los endpoints publicos de lectura.
#: Se pasan al `APIRouter` para no repetirlas endpoint a endpoint y para que
#: ninguno pueda quedarse documentando la forma por defecto de FastAPI.
RESPUESTAS_DE_ERROR: dict[int | str, dict[str, Any]] = {
    422: {
        "model": RespuestaDeError,
        "description": "Parametros de consulta invalidos o no admitidos.",
    }
}
