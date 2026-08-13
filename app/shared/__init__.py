"""Capacidades tecnicas transversales.

`shared` contiene infraestructura tecnica reutilizable por todos los modulos y
**nunca** reglas de negocio (software-architecture.md, seccion 3.4).

Paquetes presentes en `Task/005`:

- `configuration`: carga y validacion de la configuracion del proceso.
- `logging`: configuracion del log estructurado.
- `errors`: jerarquia de errores y su traduccion a HTTP.
- `database`: motor, sesiones y base declarativa de SQLAlchemy.

Paquetes previstos y todavia inexistentes: `storage` (`Task/010`), `security`
(`Task/011`) y `pagination` (`Task/009`).
"""
