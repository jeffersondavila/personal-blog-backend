"""Backend del blog personal.

Monolito modular con Clean Architecture pragmatica
(ver `personal-blog-infra/docs/adr/ADR-004-modular-monolith.md`).

Organizacion:

- `app.api`: transporte HTTP transversal (endpoints tecnicos y router raiz).
- `app.shared`: capacidades tecnicas compartidas, nunca reglas de negocio.
- `app.modules`: modulos de negocio. Todavia vacio: se pueblan desde `Task/008`.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
