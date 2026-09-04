"""Consultas de la biblioteca de medios (`Task/012`).

Solo lectura, asi que no pasan por la capa `application`: mismo criterio
**D-009-Q** que `Task/009` aplico a las consultas publicas.

Orden: **`created_at` descendente, desempate por `object_key`**. La biblioteca
existe para elegir una imagen (USER_FLOWS.md B.5) y lo que se busca casi siempre
es lo que se acaba de subir. El desempate no es cosmetico: `created_at` es la
hora de **inicio de la transaccion** (decision D-H), asi que dos cargas de la
misma transaccion la comparten, y un `LIMIT`/`OFFSET` sobre un orden no total
puede repetir u omitir filas entre paginas. `object_key` es `UNIQUE NOT NULL`,
que es justo lo que hace falta — el mismo criterio de D-009-F.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.media.infrastructure.models import MediaAsset
from app.shared.pagination import ParametrosDePagina


def contar_medios(sesion: Session) -> int:
    """Total de imagenes de la biblioteca."""
    return sesion.execute(select(func.count()).select_from(MediaAsset)).scalar_one()


def listar_medios(sesion: Session, *, parametros: ParametrosDePagina) -> Sequence[MediaAsset]:
    """Pagina de la biblioteca, de la mas reciente a la mas antigua."""
    consulta = (
        select(MediaAsset)
        .order_by(MediaAsset.created_at.desc(), MediaAsset.object_key.asc())
        .limit(parametros.limit)
        .offset(parametros.offset)
    )
    return sesion.execute(consulta).scalars().all()


def obtener_medio(sesion: Session, identificador: uuid.UUID) -> MediaAsset | None:
    """Imagen por identificador interno, o `None`."""
    return sesion.execute(
        select(MediaAsset).where(MediaAsset.id == identificador)
    ).scalar_one_or_none()
