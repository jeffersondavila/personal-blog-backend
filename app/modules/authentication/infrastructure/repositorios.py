"""Implementacion SQLAlchemy de los puertos de autenticacion (`Task/011`).

Aqui vive **todo** lo que sabe que hay una base de datos detras. El caso de uso
recibe los puertos del dominio y no importa nada de este modulo, que es lo que
permite probarlo sin PostgreSQL (software-architecture.md seccion 3.2).

Ninguna de estas operaciones confirma la transaccion: el limite transaccional lo
decide la capa de aplicacion, que es la unica que sabe cuando una operacion esta
completa.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.authentication.domain.puertos import (
    AdministradorAutenticado,
    EstadoDeAcceso,
)
from app.modules.authentication.infrastructure.models import (
    Administrator,
    AdministratorSession,
)


def normalizar_correo(correo: str) -> str:
    """Deja el correo en la forma con la que se compara y se almacena.

    Minusculas y sin espacios alrededor. Sin esta normalizacion, `Admin@…` y
    `admin@…` serian cuentas distintas para el inicio de sesion y la misma para
    el `UNIQUE` de la base: dos verdades incompatibles sobre la misma fila.

    La parte local de una direccion de correo es, segun la norma, sensible a
    mayusculas; en la practica ningun proveedor lo aplica, y aqui hay **un solo
    administrador** que escribe su propio correo. Tratar el correo entero como
    insensible a mayusculas es lo que hace que el propietario entre a la primera.
    """
    return correo.strip().lower()


class RepositorioSqlDeAdministradores:
    """Acceso al administrador con bloqueo de fila."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def bloquear_por_correo(self, correo: str) -> EstadoDeAcceso | None:
        """Lee el administrador **bloqueando su fila** hasta el fin de la transaccion.

        `with_for_update()` es la pieza que hace segura la cuenta de intentos
        fallidos. Dos peticiones simultaneas con el mismo correo se serializan
        aqui: la segunda espera a que la primera confirme, y por tanto lee el
        contador **ya incrementado**. Sin el, ambas leerian el mismo valor y una
        de las dos escrituras se perderia — que es como un umbral de cinco
        intentos se convierte en la practica en uno de diez.

        Ese bloqueo lo da el motor, no el proceso: funciona con varios workers y
        con varias instancias de Lambda, que es lo que exige P-06.
        """
        fila = self._sesion.execute(
            select(Administrator)
            .where(Administrator.email == normalizar_correo(correo))
            .with_for_update()
        ).scalar_one_or_none()
        if fila is None:
            return None
        return EstadoDeAcceso(
            id=fila.id,
            email=fila.email,
            display_name=fila.display_name,
            password_hash=fila.password_hash,
            failed_login_attempts=fila.failed_login_attempts,
            locked_until=fila.locked_until,
        )

    def registrar_intento_fallido(
        self, administrador_id: uuid.UUID, *, fallos: int, bloqueado_hasta: datetime | None
    ) -> None:
        self._sesion.execute(
            update(Administrator)
            .where(Administrator.id == administrador_id)
            .values(failed_login_attempts=fallos, locked_until=bloqueado_hasta)
        )

    def registrar_acceso_correcto(
        self,
        administrador_id: uuid.UUID,
        *,
        instante: datetime,
        password_hash: str | None = None,
    ) -> None:
        """Limpia el estado defensivo y fecha el acceso.

        El contador y el bloqueo se limpian **juntos**: dejar `locked_until` con
        un valor pasado tras un acceso correcto haria que el siguiente fallo
        volviera a bloquear de inmediato.
        """
        valores: dict[str, object] = {
            "failed_login_attempts": 0,
            "locked_until": None,
            "last_login_at": instante,
        }
        if password_hash is not None:
            valores["password_hash"] = password_hash
        self._sesion.execute(
            update(Administrator).where(Administrator.id == administrador_id).values(**valores)
        )


class RepositorioSqlDeSesiones:
    """Ciclo de vida de las sesiones administrativas."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def crear(self, *, administrador_id: uuid.UUID, huella: str, expira_en: datetime) -> None:
        """Persiste la sesion y **emite el `INSERT` en el acto**.

        El `flush` no es opcional, por la misma razon que en el repositorio de
        medios de `Task/010`: sin el, una violacion de la clave unica o de la
        clave foranea no aparece hasta el `commit`, lejos del punto que la
        provoco, y ninguna consulta posterior de la misma unidad de trabajo veria
        la fila recien creada — el harness tiene `autoflush=False`.
        """
        self._sesion.add(
            AdministratorSession(
                administrator_id=administrador_id,
                token_hash=huella,
                expires_at=expira_en,
            )
        )
        self._sesion.flush()

    def buscar_vigente(self, huella: str, *, ahora: datetime) -> AdministradorAutenticado | None:
        """Resuelve la identidad de una sesion viva, o `None`.

        Las tres condiciones —existe, no revocada, no caducada— van **dentro de
        la consulta**. Es la misma postura que `Task/009` tomo con el contenido
        publicado: una regla que vive en la consulta no puede saltarsela ningun
        llamante que se olvide de comprobarla.
        """
        fila = self._sesion.execute(
            select(Administrator)
            .join(AdministratorSession, AdministratorSession.administrator_id == Administrator.id)
            .where(
                AdministratorSession.token_hash == huella,
                AdministratorSession.revoked_at.is_(None),
                AdministratorSession.expires_at > ahora,
            )
        ).scalar_one_or_none()
        if fila is None:
            return None
        return AdministradorAutenticado(
            id=fila.id, email=fila.email, display_name=fila.display_name
        )

    def revocar(self, huella: str, *, instante: datetime) -> bool:
        """Marca la sesion como revocada. Devuelve si habia una vigente.

        La condicion `revoked_at IS NULL` evita que un segundo cierre desplace la
        fecha del primero: el instante en que la sesion dejo de valer es un dato
        del historial, no un contador que se reescriba.
        """
        revocada = self._sesion.execute(
            update(AdministratorSession)
            .where(
                AdministratorSession.token_hash == huella,
                AdministratorSession.revoked_at.is_(None),
            )
            .values(revoked_at=instante)
            .returning(AdministratorSession.id)
        ).scalar_one_or_none()
        return revocada is not None


class UnidadDeTrabajoSql:
    """Limite transaccional sobre la sesion de SQLAlchemy.

    Es deliberadamente diminuta: su unica razon de existir es que el caso de uso
    pueda hacer duraderos los cambios **sin importar SQLAlchemy**.
    """

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def confirmar(self) -> None:
        self._sesion.commit()
