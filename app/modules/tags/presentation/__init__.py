"""Presentacion publica de etiquetas."""

from app.modules.tags.presentation.router import router
from app.modules.tags.presentation.schemas import EtiquetaPublica

__all__ = ["EtiquetaPublica", "router"]
