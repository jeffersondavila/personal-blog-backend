"""Caso de uso: cerrar sesion administrativa (`Task/011`).

USER_FLOWS.md B.12 lo dice sin margen: la sesion **se invalida en el servidor**,
no solo en el navegador. Eso es exactamente lo que hace este caso de uso, y es la
razon de que la sesion se persista en lugar de emitir un token autocontenido.

Que **no** cuenta como cerrar sesion, dicho para que no vuelva a discutirse:
borrar la cookie del navegador. Una credencial copiada antes del borrado seguiria
autenticando, asi que "el cliente ya no la tiene" no es una invalidacion — es una
esperanza. La regresion que lo fija presenta la misma credencial despues del
cierre y exige `401`.
"""

from __future__ import annotations

import uuid

from app.modules.audit.domain.acciones import AccionAuditada
from app.modules.authentication.domain.puertos import (
    ContextoDeAuditoria,
    RegistroDeAuditoria,
    Reloj,
    RepositorioDeSesiones,
    UnidadDeTrabajo,
)
from app.modules.authentication.domain.sesion import huella_de_credencial


class CerrarSesion:
    """Revoca la sesion en curso en el servidor."""

    def __init__(
        self,
        *,
        sesiones: RepositorioDeSesiones,
        auditoria: RegistroDeAuditoria,
        unidad_de_trabajo: UnidadDeTrabajo,
        reloj: Reloj,
    ) -> None:
        self._sesiones = sesiones
        self._auditoria = auditoria
        self._unidad_de_trabajo = unidad_de_trabajo
        self._reloj = reloj

    def __call__(
        self,
        *,
        credencial: str,
        administrador_id: uuid.UUID,
        contexto: ContextoDeAuditoria,
    ) -> bool:
        """Revoca la sesion de esa credencial. Devuelve si habia una vigente.

        Revoca **solo la sesion presentada**, no todas las del administrador
        (decision D-011-E): cerrar sesion en el movil no debe expulsar al
        propietario del portatil. "Cerrar todas las sesiones" no lo pide ninguna
        fuente canonica y no se inventa aqui.
        """
        revocada = self._sesiones.revocar(
            huella_de_credencial(credencial), instante=self._reloj.ahora()
        )
        self._auditoria.registrar(
            AccionAuditada.CIERRE_DE_SESION.value,
            actor_id=administrador_id,
            entidad_id=administrador_id,
            request_id=contexto.request_id,
            ip=contexto.origen,
        )
        self._unidad_de_trabajo.confirmar()
        return revocada
