"""Modelo ORM del administrador.

`Task/008` define **solo el esquema**. No hay login, ni sesion, ni token, ni
*rate limiting*, ni algoritmo de *hashing*: todo eso es `Task/011`.

`password_hash` es una **columna del esquema**, no una credencial. Esta tarea no
crea ningun administrador, no elige el algoritmo de hash y no siembra ninguna
contrasena. La API nunca expone esta columna (CONTENT_MODEL.md seccion 3.8).

`failed_login_attempts` y `locked_until` existen porque la proteccion contra
fuerza bruta necesitara persistirlos. Su **uso** —cuando se incrementan, cuando
bloquean, cuando se limpian— es de `Task/011`.

Identificador de acceso: `email`
--------------------------------

CONTENT_MODEL.md admitia "`username` o `email`". Se elige **correo**: es el
identificador que el propietario ya usa, sirve tambien como via de recuperacion
y evita mantener dos identidades para una sola persona. El unico sobre `email`
no es redundante con el cerrojo del *singleton*: uno acota **cuantas** filas hay
y el otro garantiza que el identificador de acceso es **unico**, que es lo que
seguira haciendo falta si algun dia hay mas de un administrador.

*Singleton*: igual que el perfil, el esquema garantiza **como maximo uno**. Que
exista **exactamente uno** exige crear una fila con un correo real y un hash de
contrasena real, y eso no se versiona. El ROADMAP ya asigna ese trabajo:
**`Task/036-Publicar-Primer-Contenido`** en produccion —enumera explicitamente
"migraciones, **administrador**, **perfil**"— y
**`Task/022-Validacion-Local-Production-Like`** para los datos semilla del
entorno local.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UuidPrimaryKeyMixin

LONGITUD_DE_CORREO = 254
#: Holgura para cualquier formato moderno con sal y parametros incluidos.
LONGITUD_DE_HASH = 255
LONGITUD_DE_NOMBRE_VISIBLE = 120


class Administrator(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Unico usuario con acceso al panel administrativo."""

    __tablename__ = "administrators"

    #: Cerrojo del *singleton*: ver `Profile` para la explicacion completa.
    is_singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true(), unique=True
    )

    email: Mapped[str] = mapped_column(String(LONGITUD_DE_CORREO), nullable=False, unique=True)
    #: **Hash** de la contrasena. Nunca la contrasena, nunca expuesto por la API.
    #: El algoritmo lo elige `Task/011`; aqui solo existe el hueco.
    password_hash: Mapped[str] = mapped_column(String(LONGITUD_DE_HASH), nullable=False)
    display_name: Mapped[str] = mapped_column(String(LONGITUD_DE_NOMBRE_VISIBLE), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("is_singleton IS TRUE", name="administrador_unico"),
        CheckConstraint("failed_login_attempts >= 0", name="intentos_no_negativos"),
    )
