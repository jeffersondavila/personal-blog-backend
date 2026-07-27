# personal-blog-backend

API del blog personal. **FastAPI + PostgreSQL.**

> **La implementación todavía no ha comenzado.**
> Este repositorio contiene únicamente archivos base de configuración y documentación.
> No hay código FastAPI, ni modelos, ni migraciones, ni endpoints.

---

## 1. Responsabilidad del repositorio

- API pública del blog (contenido publicado, paginación, filtros, búsqueda).
- API administrativa (CRUD, borradores, publicación, archivado).
- Modelo de dominio y persistencia en PostgreSQL.
- Migraciones de base de datos (Alembic).
- Autenticación administrativa y auditoría.
- Interfaz `ObjectStorage` para imágenes y archivos (MinIO en local, Amazon S3 en la nube).
- `Dockerfile` del servicio backend.
- Pruebas del backend.

## 2. Qué NO pertenece a este repositorio

- Interfaz de usuario, componentes o estilos → `personal-blog-frontend`.
- Docker Compose del entorno, Terraform, runbooks → `personal-blog-infra`.
- Roadmap, estado del proyecto, ADR → `personal-blog-infra`.
- Secretos, credenciales o archivos `.env` reales.

## 3. Estado actual

| Campo | Valor |
| --- | --- |
| **Fase** | Etapa 00 — Fundación y Gobierno |
| **Implementación** | No iniciada |
| **Primera tarea de este repositorio** | `Task/005-Fundacion-Backend-FastAPI` (Etapa 02) |
| **Ramas** | `main`, `dev`, `Task/001-Inicializar-Workspace-y-Roadmap` |
| **Rama activa** | `main` |

Estado vigente del proyecto:
[`personal-blog-infra/docs/project-management/STATUS.md`](../personal-blog-infra/docs/project-management/STATUS.md)

## 4. Arquitectura general (resumen)

| Entorno | Cómo se ejecuta este backend |
| --- | --- |
| **Local** | Contenedor Docker con FastAPI, detrás de un reverse proxy, contra PostgreSQL y MinIO. Orquestado con Docker Compose y supervisado con Portainer CE. |
| **Nube** | AWS Lambda tras API Gateway HTTP API, contra PostgreSQL administrado y Amazon S3, con configuración en SSM Parameter Store y logs en CloudWatch. |

El mismo código sirve para ambos entornos: cambia la configuración y un adaptador Lambda
delgado (`Task/023`). Detalle completo en
[`personal-blog-infra/docs/architecture/local-to-cloud-mapping.md`](../personal-blog-infra/docs/architecture/local-to-cloud-mapping.md).

Restricciones de diseño derivadas del destino serverless:

- Sin estado en memoria entre peticiones.
- Sin procesos residentes ni trabajos de larga duración.
- Conexiones a base de datos efímeras (estrategia de pooling definida en `Task/029`).

## 5. Estrategia de ramas

| Rama | Propósito |
| --- | --- |
| `main` | Versión estable o liberable. |
| `dev` | Integración de tareas aprobadas. |
| `Task/<numero>-<nombre>` | Trabajo aislado de una tarea, creado desde `dev`. |

Una tarea que afecta a varios repositorios usa **el mismo nombre de rama** en todos.
No se hace merge automático hacia `main`.

> `main` contiene únicamente el commit inicial vacío. El trabajo de `Task/001` está
> integrado en `dev` y llegará a `main` mediante pull request.

## 6. Fuente de verdad de la planificación

Toda la planificación vive en **`personal-blog-infra`**. Este README no la duplica.

| Qué buscas | Dónde está |
| --- | --- |
| Roadmap completo | [`docs/project-management/ROADMAP.md`](../personal-blog-infra/docs/project-management/ROADMAP.md) |
| Estado actual y tareas pendientes | [`docs/project-management/STATUS.md`](../personal-blog-infra/docs/project-management/STATUS.md) |
| Proceso de trabajo | [`docs/project-management/WORKFLOW.md`](../personal-blog-infra/docs/project-management/WORKFLOW.md) |
| Definición de terminado | [`docs/project-management/DEFINITION_OF_DONE.md`](../personal-blog-infra/docs/project-management/DEFINITION_OF_DONE.md) |
| Decisiones arquitectónicas | [`docs/adr/`](../personal-blog-infra/docs/adr/) |

*(Los enlaces relativos asumen que los tres repositorios están clonados como carpetas
hermanas dentro del mismo directorio de trabajo.)*

## 7. Tareas previstas para este repositorio

`Task/005`, `Task/008`, `Task/009`, `Task/010`, `Task/011`, `Task/012`, `Task/023`,
`Task/024`, `Task/038`, y participación en `Task/007`, `Task/016`, `Task/017`,
`Task/018`, `Task/022`, `Task/036`, `Task/040`.

## 8. Contribución

Ver [CONTRIBUTING.md](CONTRIBUTING.md).
