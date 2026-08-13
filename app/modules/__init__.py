"""Modulos de negocio del blog.

Este paquete esta **intencionadamente vacio** en `Task/005`.

La division primaria del backend es **por dominio, no por capa tecnica**
(ADR-004). Cada modulo sera dueno de su dominio completo y podra contener
`domain`, `application`, `infrastructure` y `presentation` **cuando esas capas
resuelvan un problema real**: crear capas vacias esta explicitamente prohibido
(ADR-004, seccion 4; requisito M-06).

Modulos previstos y tarea que los introduce:

| Modulo           | Tarea      |
| ---------------- | ---------- |
| `posts`          | `Task/008` |
| `profile`        | `Task/008` |
| `book_reviews`   | `Task/008` |
| `videos`         | `Task/008` |
| `projects`       | `Task/008` |
| `tags`           | `Task/008` |
| `media`          | `Task/010` |
| `authentication` | `Task/011` |
| `audit`          | `Task/011` |

No se crea aqui ningun paquete anticipado: existir vacio no aporta estructura,
solo ruido.
"""
