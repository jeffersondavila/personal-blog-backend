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

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base
from app.shared.database.mixins import (
    CreationTimestampMixin,
    TimestampMixin,
    UuidPrimaryKeyMixin,
)

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


#: Longitud del hexadecimal de SHA-256. Coincide con `LONGITUD_DE_HUELLA` del
#: dominio, que es quien decide el algoritmo; aqui solo se dimensiona la columna.
LONGITUD_DE_HUELLA_DE_SESION = 64

#: La particion del limite de tasa es la direccion IP del cliente, o el literal
#: `unknown` cuando no puede determinarse. 45 caracteres cubren IPv6 y las
#: formas IPv4 mapeadas, igual que `AuditEvent.ip_address`.
LONGITUD_DE_PARTICION = 45


class AdministratorSession(UuidPrimaryKeyMixin, CreationTimestampMixin, Base):
    """Sesion administrativa opaca, persistida para poder revocarla.

    Por que existe esta tabla (`Task/011`, decision D-011-B)
    --------------------------------------------------------

    USER_FLOWS.md B.12 exige que cerrar sesion **invalide en el servidor**, no
    solo en el navegador. Un token autocontenido —un JWT— no puede satisfacerlo
    por construccion: es valido hasta que caduca, lo diga quien lo diga. La unica
    forma de revocar antes de tiempo es preguntar por un estado compartido, y ese
    estado es esta tabla.

    Que se guarda y que no
    ----------------------

    **La credencial en claro no esta aqui.** La columna es `token_hash`: la
    huella SHA-256 de lo que viaja en la cookie. Quien lea esta tabla no puede
    suplantar a nadie, porque de la huella no se vuelve a la credencial. El
    motivo de usar SHA-256 y no Argon2 —al reves que con las contrasenas— esta
    explicado en `app/modules/authentication/domain/sesion.py`: la credencial
    tiene 256 bits de azar y no admite diccionario.

    `unique=True` sobre la huella no es solo una garantia: es **el indice por el
    que se resuelve cada peticion administrativa**.

    Por que `CASCADE` aqui y `RESTRICT` en la auditoria
    ---------------------------------------------------

    `audit_events.actor_id` usa `RESTRICT` porque un evento **debe sobrevivir** a
    lo que describe: es historial. Una sesion es lo contrario —estado vivo—: si
    el administrador desapareciera, una sesion suya que siguiera en pie seria una
    credencial que autoriza en nombre de nadie. Se va con el.

    Que NO tiene, y por que
    -----------------------

    No hay `updated_at`: lo unico que cambia en una sesion es su revocacion, y
    eso ya lo fecha `revoked_at`. Tampoco hay indice sobre `administrator_id` ni
    sobre `expires_at`: **ninguna consulta del alcance vigente los recorre**, y
    un indice sin consulta es coste de escritura a cambio de nada (M-06). El dia
    que exista "cerrar todas mis sesiones" o una purga programada, ese indice
    tendra una consulta que lo justifique.
    """

    __tablename__ = "administrator_sessions"

    administrator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("administrators.id", ondelete="CASCADE"), nullable=False
    )
    #: **Huella** de la credencial, nunca la credencial.
    token_hash: Mapped[str] = mapped_column(
        String(LONGITUD_DE_HUELLA_DE_SESION), nullable=False, unique=True
    )
    #: Expiracion **absoluta**, decidida al crear la sesion. No se desplaza: el
    #: MVP no tiene renovacion deslizante (decision D-011-D).
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Marca de revocacion. Con valor, la sesion ya no autoriza, se compare o no
    #: con el reloj: es "esto ya no vale", no una revocacion programada.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginRateLimit(Base):
    """Contador del limite de tasa del inicio de sesion (decision D-011-I).

    Por que vive en PostgreSQL y no en memoria
    -------------------------------------------

    D-09 lo dice sin ambiguedad: *"el backend es stateless; cualquier contador
    debe vivir fuera del proceso"*. Un contador en RAM se multiplica por el
    numero de instancias de Lambda y se pierde en cada arranque en frio: con `N`
    contenedores tibios el limite efectivo seria `N x limite`, y llamarlo
    "limite global" seria falso. Redis resolveria lo mismo anadiendo un servicio
    con estado, su costo y su operacion, para **un** endpoint de un blog con
    **un** usuario.

    Por que la clave primaria es la particion
    ------------------------------------------

    Permite resolver el contador con un unico `INSERT … ON CONFLICT DO UPDATE`,
    que es atomico. La alternativa —leer, sumar en Python y escribir— pierde
    actualizaciones en cuanto dos peticiones coinciden, que es exactamente
    cuando el limite tiene algo que hacer.

    Que NO se guarda aqui
    ---------------------

    **Ninguna identidad.** Ni el correo intentado, ni el administrador, ni el
    agente de usuario. Quien intento entrar es asunto de la auditoria; esta tabla
    es un contador operativo, y convertirla en un almacen de datos personales
    seria recolectar lo que nadie ha pedido (requisito O-09).
    """

    __tablename__ = "login_rate_limits"

    #: Direccion IP del cliente, o el literal `unknown` cuando no puede
    #: determinarse. La politica de confianza en proxies vive en
    #: `app/shared/security/peticiones.py`.
    client_key: Mapped[str] = mapped_column(String(LONGITUD_DE_PARTICION), primary_key=True)
    #: Inicio de la ventana fija vigente. Cuando queda por detras del margen, la
    #: ventana se reinicia en la misma sentencia que incrementa.
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (CheckConstraint("attempts >= 0", name="intentos_no_negativos"),)
