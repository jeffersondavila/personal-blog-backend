"""Modelo ORM del perfil del autor y de sus enlaces sociales.

Traduce a PostgreSQL el tipo `Profile` de CONTENT_MODEL.md seccion 3.1.

El perfil **no tiene estado de publicacion ni fecha de publicacion**: siempre
existe y siempre esta visible. Su biografia es Markdown fuente (ADR-005).

Estrategia *singleton*: que garantiza el esquema y que no
--------------------------------------------------------

El esquema garantiza **como maximo un perfil**, con un cerrojo: una columna
booleana que solo admite `TRUE` y que ademas es unica. Dos filas serian dos
`TRUE`, y el indice unico lo rechaza. Es SQL corriente, sin *trigger* ni funcion
de servidor.

Lo que el esquema **no** puede garantizar es "exactamente uno": una base recien
migrada esta vacia, y `Task/008` tiene prohibido sembrar datos —el perfil
contiene el nombre real y el correo del autor, que no se versionan—. La
diferencia importa y se registra tal cual:

| Afirmacion | Quien la garantiza |
| --- | --- |
| Como maximo un perfil | **PostgreSQL**, con el cerrojo unico |
| Exactamente un perfil en produccion | **`Task/036-Publicar-Primer-Contenido`** |
| Datos semilla en el entorno local | **`Task/022-Validacion-Local-Production-Like`** |
| El perfil no se crea ni se elimina por API | `Task/012` (solo lectura y edicion) |

Los dos propietarios salen del ROADMAP, no de una suposicion: `Task/036` enumera
"migraciones, **administrador**, **perfil**, articulo, review, video, imagenes" y
`Task/022` incluye la "carga de datos semilla". `Task/012` es dueno de **editar**
el perfil por API, que no es lo mismo que crearlo la primera vez.

Enlaces sociales: por que tabla dependiente y no `JSONB`
--------------------------------------------------------

Cada enlace es un **registro con forma fija** —etiqueta, URL y orden— y no un
documento libre. Con tabla dependiente, `NOT NULL` obliga a que ningun enlace se
quede sin etiqueta o sin URL, y un unico compuesto `(perfil, orden)` impide dos
enlaces en la misma posicion. Un `JSONB` no puede prometer nada de eso: habria
que validarlo en la aplicacion y confiar en que nadie escriba por otro camino.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.media.infrastructure.models import MediaAsset
from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UuidPrimaryKeyMixin

LONGITUD_DE_NOMBRE = 120
LONGITUD_DE_TITULAR = 200
#: Longitud maxima practica de una direccion de correo (RFC 5321).
LONGITUD_DE_CORREO = 254
LONGITUD_DE_ETIQUETA = 60
LONGITUD_DE_URL = 2048
LONGITUD_DE_TITULO_SEO = 70
LONGITUD_DE_DESCRIPCION_SEO = 160


class Profile(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Identidad del autor. Singleton conceptual."""

    __tablename__ = "profiles"

    #: Cerrojo del *singleton*. No es un dato del perfil: es la restriccion
    #: expresada como columna, porque SQL no sabe decir "esta tabla tiene como
    #: maximo una fila" de ninguna otra forma portable.
    is_singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true(), unique=True
    )

    full_name: Mapped[str] = mapped_column(String(LONGITUD_DE_NOMBRE), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(LONGITUD_DE_TITULAR))
    #: Biografia extensa en Markdown fuente (ADR-005, decision 1).
    biography: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    contact_email: Mapped[str | None] = mapped_column(String(LONGITUD_DE_CORREO))

    #: Foto del autor. `ON DELETE RESTRICT`, como el resto de referencias a
    #: medios: un medio en uso no se borra (invariante 5 de CONTENT_MODEL.md).
    #: Indexada por la misma razon que las portadas: la comprobacion de uso
    #: previa al borrado consulta por esta columna (USER_FLOWS.md B.5).
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="RESTRICT"), index=True
    )
    photo: Mapped[MediaAsset | None] = relationship()

    seo_title: Mapped[str | None] = mapped_column(String(LONGITUD_DE_TITULO_SEO))
    seo_description: Mapped[str | None] = mapped_column(String(LONGITUD_DE_DESCRIPCION_SEO))

    social_links: Mapped[list[ProfileSocialLink]] = relationship(
        back_populates="profile",
        # Composicion real: un enlace social no existe fuera de su perfil.
        cascade="all, delete-orphan",
        order_by="ProfileSocialLink.display_order",
    )

    __table_args__ = (CheckConstraint("is_singleton IS TRUE", name="perfil_unico"),)


class ProfileSocialLink(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Enlace a una red social o sitio externo del autor."""

    __tablename__ = "profile_social_links"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(LONGITUD_DE_ETIQUETA), nullable=False)
    url: Mapped[str] = mapped_column(String(LONGITUD_DE_URL), nullable=False)
    #: Orden de presentacion. `display_order` y no `position`: `position` es
    #: tambien una funcion de SQL y obliga a citar la columna en cada consulta
    #: escrita a mano.
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    profile: Mapped[Profile] = relationship(back_populates="social_links")

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "display_order",
            name="uq_profile_social_links_profile_id_display_order",
        ),
        CheckConstraint("display_order >= 0", name="orden_no_negativo"),
    )
