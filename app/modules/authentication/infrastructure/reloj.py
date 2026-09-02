"""Reloj del sistema (`Task/011`).

Implementa el puerto `Reloj`. Vive en `infrastructure` porque leer la hora del
sistema es, exactamente, hablar con algo externo al dominio: es lo que permite
que los casos de uso se prueben con instantes fijos en lugar de con esperas
reales.

Siempre **UTC con zona horaria**. `datetime.now()` sin zona produce un instante
que no significa lo mismo en Windows —donde se desarrolla—, en el contenedor
Linux del entorno local y en Lambda, y comparar uno de esos con un instante de
PostgreSQL es un `TypeError` en el mejor caso y un desfase silencioso en el peor.
"""

from __future__ import annotations

from datetime import UTC, datetime


class RelojDelSistema:
    """Instante actual del proceso, en UTC."""

    def ahora(self) -> datetime:
        return datetime.now(UTC)
