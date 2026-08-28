"""DTO de un resultado de busqueda."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.engine import RowMapping

from app.modules.search.tipos import TipoDeContenido


class ResultadoDeBusqueda(BaseModel):
    type: TipoDeContenido
    slug: str
    title: str
    summary: str | None = None
    published_at: datetime | None = None

    @classmethod
    def de_fila(cls, fila: RowMapping) -> ResultadoDeBusqueda:
        return cls(
            type=TipoDeContenido(fila["type"]),
            slug=fila["slug"],
            title=fila["title"],
            summary=fila["summary"],
            published_at=fila["published_at"],
        )
