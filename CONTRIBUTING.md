# Guía de contribución — personal-blog-backend

> La implementación comenzó con `Task/005-Fundacion-Backend-FastAPI`, **aprobada** el
> 2026-08-12. Estas reglas están **vigentes**.

---

## 1. Alcance del repositorio

Se acepta aquí: API pública y administrativa, modelo de dominio, persistencia,
migraciones, autenticación, auditoría, interfaz `ObjectStorage`, `Dockerfile` y pruebas.

**No** se acepta: código de interfaz de usuario, Docker Compose del entorno, Terraform,
runbooks ni documentación de planificación (van en `personal-blog-infra`).

---

## 2. Flujo de trabajo

El proceso completo está en
[`personal-blog-infra/docs/project-management/WORKFLOW.md`](../personal-blog-infra/docs/project-management/WORKFLOW.md).
Resumen:

1. Selecciona una tarea `Pendiente` en `STATUS.md`.
2. Verifica que sus dependencias estén `Aprobada`.
3. Crea la rama `Task/<numero>-<nombre>` **desde `main`** actualizado y limpio.
   **Nunca desde `dev`**
   ([WORKFLOW §2.1](../personal-blog-infra/docs/project-management/WORKFLOW.md)).
4. Implementa **solo** el alcance de la tarea.
5. Ejecuta las validaciones.
6. Marca la tarea `Lista para validación` y espera al usuario.

La aprobación es exclusiva del usuario mediante `approved: Task/<nombre-de-rama>`.
Sin ella no se hace commit, merge, push ni pull request.

---

## 3. Estrategia de ramas

| Rama | Propósito |
| --- | --- |
| `main` | Versión estable o liberable. **Única base permitida de las ramas Task.** |
| `dev` | **Solo integración** de tareas aprobadas. **Nunca base de una Task.** |
| `Task/<numero>-<nombre>` | Trabajo aislado de una tarea, creado **desde `main`**. |

> **Invariante crítico:** toda rama `Task/<...>` nace desde `main` actualizado y limpio.
> `dev` nunca es base de una Task. Motivo y validaciones:
> [WORKFLOW §2.1](../personal-blog-infra/docs/project-management/WORKFLOW.md).

Si la tarea también toca frontend o infraestructura, se usa **el mismo nombre de rama**
en esos repositorios, y **todas nacen de `main`**.

---

## 4. Convención de commits

```
<tipo>(<ámbito>): <descripción en imperativo>

Task/<numero>-<nombre>
```

Tipos: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `build`, `perf`.

---

## 5. Estándares de código (a partir de `Task/005`)

| Aspecto | Herramienta / regla |
| --- | --- |
| Formato y lint | `ruff` |
| Tipado estático | `mypy` |
| Pruebas | `pytest` |
| Migraciones | `alembic` — toda migración debe aplicar **y** revertir |
| Longitud de línea | 100 caracteres |
| Indentación | 4 espacios |
| Fin de línea | LF |
| Docstrings | En módulos y funciones públicas no triviales |

Antes de marcar una tarea como lista:

```bash
ruff check .
ruff format --check .
mypy .
pytest
```

---

## 6. Reglas de diseño

Derivadas del destino serverless
([ADR-003](../personal-blog-infra/docs/adr/ADR-003-serverless-low-cost-cloud.md)):

- **Sin estado en memoria** entre peticiones (nada de cachés locales de proceso).
- **Sin procesos residentes** ni tareas en segundo plano de larga duración.
- **Conexiones a base de datos efímeras**: nada que asuma una conexión persistente.
- **Configuración por variables de entorno**, nunca valores incrustados en el código.
- **Acceso a archivos solo por la interfaz `ObjectStorage`**, nunca contra MinIO o S3
  directamente.
- **La API pública jamás expone borradores** ni contenido archivado.

---

## 7. Reglas de seguridad

- Nunca se versionan secretos, credenciales, tokens ni archivos `.env` reales.
- Todo valor sensible se documenta en `.env.example` con un valor ficticio.
- En la nube, la configuración vive en AWS SSM Parameter Store.
- Los logs no registran contraseñas, tokens ni datos personales.
- Toda subida de archivo se valida por tipo y tamaño.

---

## 8. Antes de marcar una tarea como lista

Revisa
[`DEFINITION_OF_DONE.md`](../personal-blog-infra/docs/project-management/DEFINITION_OF_DONE.md),
sección *Tareas de backend*.
