"""sesiones administrativas y limite de acceso

Revision: 0003
Revision anterior: 0002
Fecha de creacion: 2026-08-31 (UTC; `alembic.ini` fija `timezone = UTC`)

Migracion de `Task/011-Autenticacion-Administrativa`. Anade la persistencia que
la autenticacion necesita y **no toca nada de lo existente**: `0001` y `0002`
estan aprobadas y fusionadas, y reescribir una migracion ya aplicada dejaria las
bases existentes en un estado que ninguna revision describe.

Que crea
--------

Dos tablas, y ninguna es opcional para el alcance de la tarea:

    administrator_sessions   login_rate_limits

**`administrator_sessions`** es lo que hace que cerrar sesion signifique algo en
el servidor. USER_FLOWS.md B.12 exige que la sesion se invalide **en el
servidor**, no solo en el navegador; un token autocontenido no puede hacerlo por
construccion, asi que la revocacion necesita un estado compartido. Guarda la
**huella SHA-256** de la credencial, nunca la credencial: quien lea la tabla no
puede suplantar a nadie.

**`login_rate_limits`** es lo que hace que el limite de tasa sea **compartido
entre instancias**, que es la restriccion escrita en D-09: *"el backend es
stateless; cualquier contador debe vivir fuera del proceso"*. Su clave primaria
**es** la particion, lo que permite resolver el contador con un unico
`INSERT … ON CONFLICT DO UPDATE` atomico en lugar de con una lectura seguida de
una escritura, que es la forma con la que dos peticiones simultaneas pierden
actualizaciones.

Que NO crea, y por que
----------------------

**Ningun dato.** Sigue sin haber `INSERT` en ninguna migracion del proyecto, por
la misma razon que en `0002`: crear un administrador exige un correo real y un
hash de contrasena real, y eso no se versiona (requisito S-10). El *bootstrap*
del entorno local es de `Task/022` y el de produccion, de `Task/036`.

**Ningun indice sobre `administrator_id` ni sobre `expires_at`.** Ninguna
consulta del alcance vigente los recorre: la sesion se resuelve **siempre** por
la huella, que ya tiene indice unico. Un indice sin consulta es coste de
escritura a cambio de nada (requisito M-06). El dia que exista "cerrar todas mis
sesiones" o una purga programada, tendran una consulta que los justifique.

Reversibilidad
--------------

`downgrade` suelta las dos tablas en orden inverso al de creacion y deja `0002`
exactamente como estaba. El requisito M-04 se comprueba de verdad en
`tests/integration/test_migrations.py`, que ejecuta el ciclo
`upgrade` -> `downgrade` -> `upgrade` contra PostgreSQL real y compara el esquema
antes y despues.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'login_rate_limits',
        sa.Column('client_key', sa.String(length=45), nullable=False),
        sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.CheckConstraint(
            'attempts >= 0', name=op.f('ck_login_rate_limits_intentos_no_negativos')
        ),
        sa.PrimaryKeyConstraint('client_key', name=op.f('pk_login_rate_limits')),
    )
    op.create_table(
        'administrator_sessions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('administrator_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['administrator_id'],
            ['administrators.id'],
            name=op.f('fk_administrator_sessions_administrator_id_administrators'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_administrator_sessions')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_administrator_sessions_token_hash')),
    )


def downgrade() -> None:
    op.drop_table('administrator_sessions')
    op.drop_table('login_rate_limits')
