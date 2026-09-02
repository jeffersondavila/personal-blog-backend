"""Limite de tasa del inicio de sesion, con el contador en PostgreSQL.

`Task/011`, decision D-011-I. D-09 fija la restriccion que decide el diseno:
*"el backend es stateless; cualquier contador debe vivir fuera del proceso"*.

Por que PostgreSQL y no memoria del proceso
-------------------------------------------

Un contador en RAM se multiplica por el numero de instancias y se pierde en cada
arranque en frio: con `N` contenedores tibios de Lambda el limite efectivo seria
`N x limite`, y llamarlo "limite global" seria simplemente falso. PostgreSQL ya
esta en el camino de cada peticion administrativa, asi que el contador compartido
no anade ninguna dependencia nueva. Redis daria lo mismo a cambio de un servicio
con estado, su costo y su operacion, para **un** endpoint de un blog con **un**
usuario.

Por que una unica sentencia
---------------------------

`INSERT … ON CONFLICT DO UPDATE` es **atomico**: el motor toma el cerrojo de la
fila y resuelve la lectura, la decision y la escritura sin hueco entre medias. La
alternativa —leer, sumar en Python y escribir— pierde actualizaciones justo
cuando llegan muchas peticiones a la vez, que es exactamente cuando el limite
tiene algo que hacer.

Limites que se declaran, no que se disimulan
--------------------------------------------

- **Ventana fija, no deslizante.** En la frontera entre dos ventanas admite hasta
  el doble del limite. Aceptado: una ventana deslizante exigiria guardar una
  marca por intento a cambio de un beneficio que aqui no cambia nada.
- **No protege frente a un atacante distribuido** que rote direcciones. Esa
  dimension la cubre el bloqueo de cuenta, que no depende del origen.
- **Sin purga automatica** de filas caducadas: no hay procesos residentes
  (software-architecture.md seccion 6). Es una fila por direccion que haya
  intentado entrar, y su limpieza queda registrada como deuda.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.authentication.domain.puertos import ResultadoDelLimite
from app.modules.authentication.infrastructure.models import LoginRateLimit


class LimitadorSqlDeAccesos:
    """Contador de ventana fija, compartido por todas las instancias."""

    def __init__(self, sesion: Session, *, maximo: int, ventana: timedelta) -> None:
        self._sesion = sesion
        self._maximo = maximo
        self._ventana = ventana

    def registrar_intento(self, clave: str, *, ahora: datetime) -> ResultadoDelLimite:
        """Cuenta el intento y dice si se admite.

        Se cuentan **todos** los intentos, con exito o sin el: lo que se protege
        es el endpoint frente a rafagas, y una rafaga de intentos acertados
        tambien lo es.

        El `CASE` decide dentro de la misma sentencia si la ventana anterior ya
        quedo atras —y entonces reinicia contador y marca de inicio— o si sigue
        vigente y solo hay que sumar uno.
        """
        suelo = ahora - self._ventana

        nueva = insert(LoginRateLimit).values(client_key=clave, window_started_at=ahora, attempts=1)
        ventana_vencida = LoginRateLimit.window_started_at <= suelo
        sentencia = nueva.on_conflict_do_update(
            index_elements=[LoginRateLimit.client_key],
            set_={
                "window_started_at": case(
                    (ventana_vencida, nueva.excluded.window_started_at),
                    else_=LoginRateLimit.window_started_at,
                ),
                "attempts": case(
                    (ventana_vencida, nueva.excluded.attempts),
                    else_=LoginRateLimit.attempts + 1,
                ),
            },
        ).returning(LoginRateLimit.attempts, LoginRateLimit.window_started_at)

        intentos, inicio = self._sesion.execute(sentencia).one()

        return ResultadoDelLimite(
            permitido=intentos <= self._maximo,
            reintentar_en_segundos=self._segundos_hasta_el_fin(inicio, ahora=ahora),
        )

    def _segundos_hasta_el_fin(self, inicio: datetime, *, ahora: datetime) -> int:
        """Segundos que faltan para que la ventana termine.

        Se redondea **hacia arriba** y nunca baja de 1: un `Retry-After: 0`
        invitaria a reintentar de inmediato, que es justo lo contrario de lo que
        la cabecera significa.
        """
        restante = (inicio + self._ventana - ahora).total_seconds()
        return max(1, math.ceil(restante))
