"""Endpoint de vivacidad del servicio.

`GET /health` responde afirmativamente **si el proceso esta en pie**, sin
comprobar ninguna dependencia (api-contracts.md, seccion 2; requisito O-03).
Esa separacion es deliberada: un healthcheck que consulta la base de datos
reinicia el contenedor cuando el problema esta en la base de datos, no en el
servicio.

`GET /ready` —la comprobacion real de PostgreSQL y del almacenamiento— es
requisito O-04 y corresponde a `Task/017`. No se adelanta aqui.

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
