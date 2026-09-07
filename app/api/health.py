"""Endpoint de vivacidad del servicio.

`GET /health` responde afirmativamente **si el proceso esta en pie**, sin
comprobar ninguna dependencia (api-contracts.md, seccion 2; requisito O-03).

Esa separacion es deliberada, y la razon es **semantica**: `/health` responde a
*"el proceso esta vivo"*, y la respuesta a esa pregunta no cambia porque
PostgreSQL se caiga. Mezclarlas dejaria el sistema sin forma de distinguir un
proceso muerto de una dependencia caida, que es justo la distincion que O-03 y
O-04 existen para crear.

> **Precision de `Task/017`.** Hasta esta tarea, este comentario justificaba lo
> mismo diciendo que un healthcheck que consulta la base de datos *"reinicia el
> contenedor"*. La conclusion era correcta, pero esa razon **no se sostiene**:
> Docker Compose no reinicia un contenedor por el resultado de su `HEALTHCHECK`
> —la politica `restart` reacciona a que el proceso termine—, y el reinicio
> automatico por sonda es comportamiento de Docker Swarm, que este proyecto no
> usa. La consecuencia real de mantener `/health` aqui es otra, y tambien
> importa: durante un incidente de dependencias el contenedor sigue **sano y en
> marcha**, asi que sus logs siguen siendo consultables desde Portainer.

`GET /ready` —la comprobacion real de PostgreSQL y del almacenamiento, requisito
O-04— vive en `app/api/readiness.py` desde `Task/017`. Es la sonda que consume
Traefik, porque su consecuencia si es de rotacion.

**Fuera del prefijo `/api/v1` a proposito.** El prefijo versiona el contrato de
datos con el frontend; la sonda de vivacidad la consume la plataforma —Docker,
API Gateway, un balanceador— y no debe cambiar de ruta cuando el contrato pase
a `v2`.

La respuesta no expone entorno, dependencias ni detalles internos
(api-contracts.md, seccion 2).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app import __version__
from app.shared.configuration import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Cuerpo de la respuesta de vivacidad."""

    status: Literal["ok"] = Field(description="Estado del proceso.")
    service: str = Field(description="Nombre del servicio.")
    version: str = Field(description="Version de la aplicacion.")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Vivacidad del servicio",
    description="Responde 200 si el proceso esta en pie. No comprueba dependencias.",
)
def read_health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Devuelve el estado de vivacidad del proceso."""
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)
