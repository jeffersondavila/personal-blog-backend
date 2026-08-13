"""baseline del esquema

Revision: 0001
Revision anterior: None
Fecha de creacion: 2026-08-01

Migracion **fundacional**: establece el control de versiones del esquema y no
crea ningun objeto de negocio.

Por que esta vacia
------------------

`Task/005` es la fundacion del backend; el modelo de datos del blog —perfil,
articulos, reviews, videos, proyectos, etiquetas, medios, administrador y
auditoria— corresponde a `Task/008`. Crear aqui tablas que despues habria que
rehacer seria trabajo desechable, y anticipar el modelo contradiria el alcance
declarado de la tarea.

Lo que si deja establecido
--------------------------

- La tabla `alembic_version` existe en la base de datos y registra la revision
  aplicada: a partir de ahora todo cambio de esquema pasa por una migracion.
- La cadena de revisiones arranca en `0001`, con `down_revision = None`.
- El ciclo `upgrade` / `downgrade` / reaplicacion es verificable de extremo a
  extremo (requisito M-04), sin datos ni tablas de negocio de por medio.

`downgrade` vacio es correcto **solo** porque `upgrade` no crea nada. En
cualquier migracion posterior, un `downgrade` vacio seria un defecto.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Sin objetos que crear: esta revision solo fija el punto de partida."""


def downgrade() -> None:
    """Sin objetos que eliminar: `upgrade` no crea ninguno."""
