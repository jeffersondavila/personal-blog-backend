"""Reloj del sistema (`Task/011`).

**Reexportacion.** La implementacion vive en `app/shared/reloj.py` desde
`Task/012`: un reloj no conoce ninguna regla de negocio, y sus consumidores
pasaron de uno —la autenticacion— a cinco, con los cuatro tipos de contenido que
fijan `published_at`. Mantener aqui el nombre evita tocar las firmas y los
imports de `Task/011`: es un refactor, no un cambio de contrato.
"""

from __future__ import annotations

from app.shared.reloj import RelojDelSistema

__all__ = ["RelojDelSistema"]
