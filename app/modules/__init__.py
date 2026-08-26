"""Modulos de negocio del blog.

La division primaria del backend es **por dominio, no por capa tecnica**
(ADR-004). Cada modulo es dueno de su dominio completo y contiene `domain`,
`application`, `infrastructure` y `presentation` **solo cuando esas capas
resuelven un problema real**: crear capas vacias esta explicitamente prohibido
(ADR-004 seccion 4; requisito M-06).

Estado tras `Task/008`
----------------------

| Modulo | `domain` | `infra` | Que trae `Task/008` | Que falta, y de quien es |
| ---------------- | :---: | :---: | --- | --- |
| `posts`          | si    | si    | ciclo de vida, modelo | consultas: `Task/009` |
| `book_reviews`   | si    | si    | ciclo de vida, valoracion, modelo | consultas: `Task/009` |
| `videos`         | si    | si    | ciclo de vida, modelo | proveedores: `Task/014` |
| `projects`       | si    | si    | ciclo de vida, estado de obra, modelo | consultas: `Task/009` |
| `profile`        | no    | si    | modelo | edicion: `Task/012` |
| `tags`           | no    | si    | modelo y asociaciones | gestion: `Task/012` |
| `media`          | no    | si    | **solo el modelo** | `ObjectStorage`: `Task/010` |
| `authentication` | no    | si    | **solo el modelo** | login y hashing: `Task/011` |
| `audit`          | no    | si    | **persistencia e inmutabilidad** | el servicio: `Task/011` |

Cuatro modulos tienen `domain` porque tienen **reglas propias** —transiciones de
publicacion, escala de valoracion—. Los otros cinco no lo tienen porque hoy no
las tienen: `profile` y `tags` son datos, y las reglas de `media`,
`authentication` y `audit` llegan con sus tareas. Ninguno tiene `application` ni
`presentation`: no hay todavia casos de uso ni endpoints que alojar.

> **Este paquete no importa los modelos ORM.** Importar un submodulo ejecuta el
> `__init__` de su paquete, asi que hacerlo aqui haria que un
> `import app.modules.posts.domain` cargase SQLAlchemy y el dominio dejaria de
> ser Python plano. El registro vive en `app/modules/models.py`, y la regresion
> en `tests/unit/test_independencia_del_dominio.py`.
"""
