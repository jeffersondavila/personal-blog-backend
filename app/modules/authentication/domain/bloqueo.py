"""Reglas del bloqueo de cuenta por intentos fallidos (`Task/011`, D-011-G).

`Task/008` creo `failed_login_attempts` y `locked_until` **sin comportamiento**:
dijo que la proteccion contra fuerza bruta necesitaria persistirlos y dejo su uso
para esta tarea. Aqui esta ese uso, en Python plano.

Que protege esto, y que no
--------------------------

Protege **una cuenta concreta** frente a la adivinacion de su contrasena. **No**
protege el endpoint frente a rafagas: eso es el limite de tasa, que particiona por
origen y vive en otro sitio. Son dos alcances distintos y ninguno sustituye al
otro — un atacante con muchas IP burla el limite de tasa pero no el bloqueo, y
uno que pruebe muchas cuentas burlaria el bloqueo si hubiera mas de una cuenta.

Las tres decisiones que no son obvias
-------------------------------------

1. **El bloqueo no se alarga mientras esta vigente.** Si cada intento desplazara
   `locked_until`, cualquiera podria mantener al **unico** administrador fuera de
   su propio panel indefinidamente: se cambiaria un problema por otro peor. El
   bloqueo acota la adivinacion durante una ventana fija y despues cede.
2. **Los fallos durante el bloqueo no se cuentan.** Mientras la cuenta esta
   bloqueada no se evalua ninguna credencial, asi que no hay ningun intento real
   que contar.
3. **Al vencer el bloqueo, el contador vuelve a empezar.** Sin esto el contador
   se quedaria en el umbral y **el primer fallo posterior volveria a bloquear al
   instante**: un bloqueo anunciado como temporal se comportaria como permanente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class EstadoDelBloqueo:
    """Estado defensivo que debe quedar persistido tras un intento fallido."""

    fallos: int
    bloqueado_hasta: datetime | None


def cuenta_bloqueada(bloqueado_hasta: datetime | None, *, ahora: datetime) -> bool:
    """Indica si la cuenta esta bloqueada en este instante.

    `bloqueado_hasta` es **exclusivo**: en el instante exacto de vencimiento la
    cuenta ya vuelve a admitir intentos.
    """
    _exigir_utc(bloqueado_hasta=bloqueado_hasta, ahora=ahora)
    return bloqueado_hasta is not None and ahora < bloqueado_hasta


def estado_tras_un_fallo(
    *,
    fallos: int,
    bloqueado_hasta: datetime | None,
    ahora: datetime,
    umbral: int,
    duracion: timedelta,
) -> EstadoDelBloqueo:
    """Calcula el estado defensivo que deja un intento fallido.

    Tres caminos, y cada uno responde a una de las decisiones del modulo:

    - **La cuenta ya esta bloqueada** -> nada cambia. Ni se cuenta el intento, ni
      se alarga el bloqueo.
    - **Habia un bloqueo ya vencido** -> el contador **empieza de nuevo** en 1 y
      la marca vencida se limpia, en lugar de quedarse como residuo que cada
      lector posterior tendria que recordar comparar con el reloj.
    - **Sin bloqueo** -> se incrementa, y si alcanza el umbral se bloquea.
    """
    _exigir_utc(bloqueado_hasta=bloqueado_hasta, ahora=ahora)

    if cuenta_bloqueada(bloqueado_hasta, ahora=ahora):
        return EstadoDelBloqueo(fallos=fallos, bloqueado_hasta=bloqueado_hasta)

    acumulados = 1 if bloqueado_hasta is not None else fallos + 1
    if acumulados >= umbral:
        return EstadoDelBloqueo(fallos=acumulados, bloqueado_hasta=ahora + duracion)
    return EstadoDelBloqueo(fallos=acumulados, bloqueado_hasta=None)


def _exigir_utc(**instantes: datetime | None) -> None:
    """Rechaza cualquier instante sin zona horaria (CONTENT_MODEL.md, invariante 10)."""
    for nombre, valor in instantes.items():
        if valor is not None and valor.tzinfo is None:
            raise ValueError(f"'{nombre}' debe ser un instante con zona horaria (UTC)")
