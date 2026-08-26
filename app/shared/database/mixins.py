"""Columnas tecnicas comunes a los modelos ORM.

Son **capacidades tecnicas transversales**, no reglas de negocio: identidad y
marcas de tiempo. Por eso viven en `app/shared` y no en un modulo
(software-architecture.md seccion 3.4).

Que NO hay aqui, deliberadamente
--------------------------------

No existe un *mixin* con las columnas de contenido —`slug`, `title`, `summary`,
`status`, SEO— aunque cuatro tablas las repitan. Esas columnas **son** el modelo
de negocio de cada tipo, y centralizarlas en `shared` metria reglas de dominio
en un paquete que las tiene prohibidas; convertirlas en una jerarquia ORM crearia
la superentidad `Content` que `Task/008` descarta por diseno. La repeticion de
unas cuantas columnas es mas barata que una jerarquia que despues hay que
deshacer (ADR-004: "sin abstracciones sin uso demostrado").
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class UuidPrimaryKeyMixin:
    """Clave primaria `UUID` generada por la aplicacion.

    Por que UUID y no un entero secuencial
    --------------------------------------

    1. **La referencia polimorfica de la auditoria.** `audit_events` guarda
       `entity_type` + `entity_id` sin clave foranea. Con enteros secuenciales el
       identificador `5` existe a la vez en articulos, videos y etiquetas: un
       `entity_type` equivocado apuntaria en silencio a una fila real de otra
       tabla. Con UUID, una referencia mal formada simplemente no encuentra nada.
    2. **Identificadores no enumerables** en la API administrativa, que opera
       sobre identificadores internos (api-contracts.md seccion 4).
    3. **Se generan antes de persistir**, asi que una entidad tiene identidad
       desde que se construye, sin ida y vuelta a la base de datos.

    El coste —16 bytes en lugar de 8, y un indice que se fragmenta mas por la
    aleatoriedad— es irrelevante en el volumen de un blog personal.

    `Uuid` es el tipo neutral de SQLAlchemy: en PostgreSQL usa el tipo nativo
    `uuid`, que es **del nucleo del motor y no una extension** (requisito T-02).
    La generacion ocurre en Python, no con `gen_random_uuid()`, para no depender
    de una funcion del servidor.
    """

    #: `sort_order` no cambia el comportamiento, solo el orden de las columnas en
    #: el DDL generado: la identidad primero y las marcas de tiempo al final, que
    #: es como se lee una tabla. Sin el, las columnas de los *mixins* quedan
    #: detras de las de negocio y cada `CREATE TABLE` empieza por el medio.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, sort_order=-100
    )


class CreationTimestampMixin:
    """Marca de creacion, en UTC y con zona horaria.

    `TIMESTAMP WITH TIME ZONE` y no `TIMESTAMP` a secas: CONTENT_MODEL.md
    (invariante 10) exige UTC, y una marca sin zona horaria no dice en que
    instante ocurrio nada.

    El valor lo pone **la base de datos** (`now()`), no la aplicacion: es un
    unico reloj para todos los procesos que escriban, inmune al desfase del
    servidor de aplicacion. `published_at`, en cambio, es un momento **de
    negocio** que decide el caso de uso, que recibe su reloj inyectado y puede
    probarse con instantes fijos.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=100
    )


class TimestampMixin(CreationTimestampMixin):
    """Marcas de creacion y de ultima modificacion.

    `onupdate` hace que SQLAlchemy incluya `now()` en cada `UPDATE` que emita.
    **Alcance exacto de la garantia:** cubre las escrituras que pasan por el ORM,
    que son todas las de la aplicacion. Un `UPDATE` ejecutado a mano contra la
    base no actualiza la columna; para eso haria falta un *trigger*, y un
    *trigger* en PL/pgSQL es codigo de servidor que el proyecto evita mientras no
    resuelva un problema real (T-02).
    """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        sort_order=101,
    )
