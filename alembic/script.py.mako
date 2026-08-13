"""${message}

Revision: ${up_revision}
Revision anterior: ${down_revision | comma,n}
Fecha de creacion: ${create_date}

Toda migracion debe aplicar **y** revertir (requisito M-04): `downgrade` no
puede quedar vacio si `upgrade` crea algo.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
