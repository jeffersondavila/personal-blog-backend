"""Utilidades comunes de las pruebas de la API administrativa (`Task/012`).

Mismo criterio que `datos.py` y `datos_de_autenticacion.py`: **funciones
normales, no fixtures**. El harness de integracion exige que toda fixture derive
del resolutor verificado (`CERT-AUD-002`), y estas funciones no resuelven ningun
destino: reciben el cliente y la sesion que la prueba ya obtuvo por el camino
comprobado.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditEvent
from app.modules.authentication.infrastructure.models import Administrator
from tests.integration.datos_de_autenticacion import CONTRASENA, CORREO, administrador

#: Prefijo administrativo del contrato (api-contracts.md seccion 4).
ADMIN = "/api/v1/admin"

ACCESO = f"{ADMIN}/auth/login"


def administrador_con_sesion(cliente: TestClient, sesion: Session) -> Administrator:
    """Crea el administrador de la prueba y deja al cliente con sesion abierta.

    Devuelve la fila para que la prueba pueda comprobar `actor_id` en la
    auditoria sin volver a consultarla.
    """
    fila = administrador(sesion)
    respuesta = cliente.post(ACCESO, json={"email": CORREO, "password": CONTRASENA})
    assert respuesta.status_code == 200, respuesta.text
    return fila


def eventos_de(sesion: Session, accion: str) -> list[AuditEvent]:
    """Eventos de auditoria de esa accion, en orden de escritura."""
    return list(
        sesion.execute(
            select(AuditEvent).where(AuditEvent.action == accion).order_by(AuditEvent.occurred_at)
        )
        .scalars()
        .all()
    )


def cuerpo(respuesta: Any) -> dict[str, Any]:
    """Cuerpo JSON de la respuesta, con el estado en el mensaje si falla."""
    contenido: dict[str, Any] = respuesta.json()
    return contenido


def codigo_de_error(respuesta: Any) -> str:
    """`error.code` de una respuesta de error del proyecto."""
    codigo: str = respuesta.json()["error"]["code"]
    return codigo
