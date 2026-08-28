"""Capa de presentacion del modulo de medios.

Solo esquemas: `Task/009` no expone ningun endpoint publico de medios. La
biblioteca de medios es administrativa (`Task/010`, `Task/012`).
"""

from app.modules.media.presentation.schemas import MedioPublico

__all__ = ["MedioPublico"]
