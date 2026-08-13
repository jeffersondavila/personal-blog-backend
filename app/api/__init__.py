"""Capa de transporte HTTP transversal.

Aqui viven unicamente los endpoints **tecnicos**, los que no pertenecen a
ningun modulo de negocio. Los routers de contenido (`posts`, `profile`, ...)
viviran dentro de su modulo, en su propia capa de presentacion
(software-architecture.md, seccion 3.2).
"""

from app.api.health import router as health_router

__all__ = ["health_router"]
