"""Puertos del modulo de autenticacion (`Task/011`).

Los define el **dominio** y los implementa la **infraestructura**: es la regla de
dependencias de software-architecture.md seccion 3.2, y lo que permite que el
caso de uso de inicio de sesion se pruebe sin PostgreSQL, sin reloj real y sin
FastAPI.

Por que estos puertos y no mas
------------------------------

Hay exactamente cinco, y cada uno es un **limite** real —repositorio,
repositorio, contador compartido, historial y reloj—, que son justamente los
limites donde BACKEND_TESTING_STRATEGY.md seccion 10 admite un doble. No hay un
puerto por clase ni una interfaz por si acaso: crear abstracciones sin uso esta
prohibido (M-06, ADR-004).

Por que los DTO y no los modelos ORM
------------------------------------

`presentation` y `application` no deben ver SQLAlchemy (regla 9 de la seccion
3.5). `EstadoDeAcceso` y `AdministradorAutenticado` son dos vistas distintas del
mismo administrador **a proposito**:

- `EstadoDeAcceso` lleva el hash y el estado defensivo. Solo lo usa el inicio de
  sesion, y **nunca** sale de la capa de aplicacion.
- `AdministradorAutenticado` es la identidad publica: lo unico que puede llegar a
  una respuesta HTTP. No contiene hash, ni contador de fallos, ni bloqueo, asi
  que **no hay ninguna ruta por la que ese estado se filtre** a un cliente.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AdministradorAutenticado:
    """Identidad publica del administrador.

    Es lo unico que la presentacion puede serializar. Anadir aqui un campo es
    anadirlo al contrato `v1`, del que ya no podria retirarse (api-contracts.md
    seccion 10).
    """

    id: uuid.UUID
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class EstadoDeAcceso:
    """Lo que el inicio de sesion necesita saber del administrador.

    Incluye el hash y el estado defensivo, y por eso **no se serializa jamas**.
    `repr` esta desactivado en `password_hash` para que un volcado accidental
    —una traza, un `logger.debug(estado)`— no lo arrastre (requisito S-08).
    """

    id: uuid.UUID
    email: str
    display_name: str
    password_hash: str = field(repr=False)
    failed_login_attempts: int
    locked_until: datetime | None

    @property
    def identidad(self) -> AdministradorAutenticado:
        """Proyeccion publica, sin nada del estado defensivo."""
        return AdministradorAutenticado(
            id=self.id, email=self.email, display_name=self.display_name
        )


@dataclass(frozen=True, slots=True)
class ContextoDeAuditoria(Protocol):
    """Datos de correlacion que acompanan a cada evento.

    Es un protocolo y no una clase concreta para que la capa de aplicacion
    no tenga que importar nada de presentacion: lo que se le pasa es un
    objeto con estos dos atributos, y de donde salen no es asunto suyo.
    """

    origen: str
    request_id: str


@dataclass(frozen=True, slots=True)
class ResultadoDelLimite:
    """Veredicto del limitador para un intento concreto."""

    permitido: bool
    #: Segundos que faltan para que la ventana actual termine. Es lo que se
    #: devuelve como `Retry-After`, asi que se expresa en segundos enteros.
    reintentar_en_segundos: int


class Reloj(Protocol):
    """Fuente del instante actual.

    Existe para que la expiracion, el bloqueo y la ventana del limite se puedan
    probar con instantes fijos en lugar de con esperas reales. Es una
    abstraccion minima —un metodo— y no un framework de tiempo.
    """

    def ahora(self) -> datetime:
        """Instante actual, **siempre con zona horaria UTC**."""
        ...


class UnidadDeTrabajo(Protocol):
    """Limite transaccional, en manos de la capa de aplicacion.

    Existe por una razon concreta y comprobada (decision D-011-N): un intento de
    acceso **fallido** escribe estado defensivo —contador, bloqueo, limite de
    tasa y auditoria—, y si el fallo se senalara lanzando, la dependencia de
    sesion de FastAPI haria `rollback` y ese estado se perderia. El contador
    volveria a cero en cada intento y el bloqueo no llegaria a existir.

    Es un puerto y no una `Session` inyectada para que el caso de uso siga sin
    conocer SQLAlchemy.
    """

    def confirmar(self) -> None:
        """Hace duraderos los cambios acumulados."""
        ...


class RepositorioDeAdministradores(Protocol):
    """Acceso al administrador y a su estado defensivo."""

    def bloquear_por_correo(self, correo: str) -> EstadoDeAcceso | None:
        """Devuelve el administrador de ese correo **con su fila bloqueada**.

        El bloqueo de fila no es un detalle de implementacion que se pueda
        omitir: `failed_login_attempts` es estado de seguridad, y leerlo, sumar
        en Python y escribirlo pierde actualizaciones en cuanto dos intentos
        coinciden — que es exactamente cuando la proteccion tiene algo que hacer.
        """
        ...

    def registrar_intento_fallido(
        self, administrador_id: uuid.UUID, *, fallos: int, bloqueado_hasta: datetime | None
    ) -> None:
        """Persiste el estado defensivo que decidieron las reglas del dominio."""
        ...

    def registrar_acceso_correcto(
        self,
        administrador_id: uuid.UUID,
        *,
        instante: datetime,
        password_hash: str | None = None,
    ) -> None:
        """Limpia el estado defensivo y fecha el acceso.

        `password_hash` solo se pasa cuando el hash almacenado usaba parametros
        antiguos: es el rehash silencioso, que no pide nada al propietario.
        """
        ...


class RepositorioDeSesiones(Protocol):
    """Ciclo de vida de las sesiones administrativas."""

    def crear(self, *, administrador_id: uuid.UUID, huella: str, expira_en: datetime) -> None:
        """Persiste una sesion nueva a partir de la huella de su credencial.

        Recibe la **huella**, no la credencial: quien la genera es el caso de
        uso, y el secreto en claro no tiene por que cruzar este limite.
        """
        ...

    def buscar_vigente(self, huella: str, *, ahora: datetime) -> AdministradorAutenticado | None:
        """Resuelve la identidad de una sesion **viva**.

        Una sesion caducada o revocada no resuelve a nadie: la comprobacion no es
        del llamante, para que no pueda olvidarse en ninguna ruta.
        """
        ...

    def revocar(self, huella: str, *, instante: datetime) -> bool:
        """Revoca la sesion. Devuelve si habia una vigente que revocar."""
        ...


class LimitadorDeAccesos(Protocol):
    """Contador compartido del limite de tasa del inicio de sesion."""

    def registrar_intento(self, clave: str, *, ahora: datetime) -> ResultadoDelLimite:
        """Cuenta un intento para esa particion y dice si se admite.

        Cuenta **siempre**, incluso cuando el veredicto es negativo: lo que se
        protege es el endpoint frente a rafagas, y una rafaga rechazada sigue
        siendo una rafaga.
        """
        ...


class RegistroDeAuditoria(Protocol):
    """Escritura del historial administrativo.

    Solo **crea**: la auditoria no se modifica ni se borra, y las guardas que lo
    garantizan viven en el modelo desde `Task/008`.
    """

    def registrar(
        self,
        accion: str,
        *,
        actor_id: uuid.UUID | None,
        entidad_id: uuid.UUID | None,
        request_id: str | None,
        ip: str | None,
        metadatos: dict[str, Any] | None = None,
    ) -> None:
        """Anade un evento al historial.

        `actor_id` admite nulo porque hay eventos sin actor conocido: un intento
        de acceso contra un correo que no existe tambien se audita.
        """
        ...
