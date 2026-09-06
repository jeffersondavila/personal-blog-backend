"""Utilidades comunes de las pruebas de la API administrativa (`Task/012`).

Mismo criterio que `datos.py` y `datos_de_autenticacion.py`: **funciones
normales, no fixtures**. El harness de integracion exige que toda fixture derive
del resolutor verificado (`CERT-AUD-002`), y estas funciones no resuelven ningun
destino: reciben el cliente y la sesion que la prueba ya obtuvo por el camino
comprobado.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.models import AuditEvent
from app.modules.authentication.domain.sesion import generar_credencial, huella_de_credencial
from app.modules.authentication.infrastructure.models import (
    Administrator,
    AdministratorSession,
)
from app.modules.authentication.presentation.cookies import NOMBRE_DE_LA_COOKIE
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


def administrador_con_sesion_sin_auditar(
    cliente: TestClient, sesion: Session, *, duracion: timedelta = timedelta(hours=12)
) -> Administrator:
    """Igual que `administrador_con_sesion`, pero **sin pasar por el login**.

    Existe por un caso que el flujo real no puede preparar: comprobar el
    historial **vacio**. Iniciar sesion escribe `authentication.login_succeeded`
    —y debe hacerlo, USER_FLOWS.md B.1—, asi que despues de un login el
    historial nunca tiene cero filas.

    Se construye la sesion **como la construye el codigo real**, reutilizando sus
    funciones de dominio: `generar_credencial()` produce la credencial opaca de
    256 bits y `huella_de_credencial()` la huella SHA-256 que es lo unico que se
    persiste (decision **D-011-B**). La fila resultante es indistinguible de la
    que crea `IniciarSesion`, y por eso las dependencias administrativas la
    aceptan sin ninguna concesion.

    Lo que **no** se hace, y es lo que hace legitima esta preparacion:

    - no se anade ningun endpoint, bandera ni modo de prueba al codigo real;
    - no se desactiva la auditoria ni se toca `IniciarSesion`;
    - no se simula la consulta;
    - **no se borra ningun `AuditEvent`**: la invariante de historial inmutable
      no necesita relajarse para escribir esta prueba, porque el evento
      sencillamente no llega a existir.

    Es *setup* de integracion —persistir los datos tecnicos de una sesion—, no
    comportamiento productivo.
    """
    fila = administrador(sesion)
    credencial = generar_credencial()
    sesion.add(
        AdministratorSession(
            administrator_id=fila.id,
            token_hash=huella_de_credencial(credencial),
            expires_at=datetime.now(UTC) + duracion,
        )
    )
    sesion.flush()
    cliente.cookies[NOMBRE_DE_LA_COOKIE] = credencial
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
