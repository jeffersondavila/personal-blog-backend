# personal-blog-backend

API del blog personal. **FastAPI + PostgreSQL.**

> **Estado: fundación implementada, sin funcionalidad de negocio.**
> `Task/005` establece la base técnica —configuración, log, errores, acceso a datos,
> migraciones, pruebas y `Dockerfile`—. **No hay todavía modelo de datos, endpoints de
> contenido ni autenticación**: llegan a partir de `Task/008`.

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
| **Etapa** | ETAPA 02 — Fundaciones de las Aplicaciones |
| **Tarea en curso** | `Task/005-Fundacion-Backend-FastAPI` |
| **Implementación** | Fundación: aplicación, configuración, log, errores, base de datos y migraciones |
| **Python** | 3.12 |
| **Endpoints** | `GET /health`, `GET /openapi.json`, `GET /docs` |
| **Modelo de datos** | No existe todavía (`Task/008`) |

Estado vigente del proyecto:
[`personal-blog-infra/docs/project-management/STATUS.md`](../personal-blog-infra/docs/project-management/STATUS.md)

---

## 4. Requisitos

- **Python 3.12**.
- **Docker Desktop**, para el entorno local de `personal-blog-infra` (PostgreSQL, MinIO,
  Portainer) y para construir la imagen del backend.
- El entorno local **levantado**: ver
  [runbook de entorno local](../personal-blog-infra/docs/runbooks/local-environment.md).

## 5. Puesta en marcha

```powershell
# 1. Entorno virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Dependencias de desarrollo (incluye las de ejecución)
pip install -r requirements-dev.txt

# 3. Configuración local
Copy-Item .env.example .env
# Edita .env y pon la contraseña real de PostgreSQL (la del .env de personal-blog-infra)

# 4. Migraciones
alembic upgrade head

# 5. Servidor de desarrollo
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Comprobación rápida:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing | Select-Object -ExpandProperty Content
# {"status":"ok","service":"personal-blog-backend","version":"0.1.0"}
```

Documentación interactiva: <http://127.0.0.1:8000/docs>

> El puerto 8000 es una convención de desarrollo, no una decisión de infraestructura: si
> está ocupado, usa otro. El puerto definitivo del backend dentro del entorno local se fija
> en `Task/007`.

## 6. Configuración

Toda la configuración se lee de **variables de entorno** con el prefijo `BLOG_`, se valida
al arrancar y **falla rápido** si falta algo obligatorio. La referencia completa, con
valores ficticios, está en [`.env.example`](.env.example).

| Variable | Obligatoria | Por defecto | Propósito |
| --- | :---: | --- | --- |
| `BLOG_DATABASE_URL` | **Sí** | — | Conexión a PostgreSQL. |
| `BLOG_APP_NAME` | No | `personal-blog-backend` | Nombre del servicio. |
| `BLOG_APP_ENV` | No | `local` | `local`, `test` o `production`. |
| `BLOG_APP_DEBUG` | No | `false` | Modo depuración. Prohibido en `production`. |
| `BLOG_API_V1_PREFIX` | No | `/api/v1` | Prefijo de la API versionada. |
| `BLOG_LOG_LEVEL` | No | `INFO` | Nivel de log. |
| `BLOG_LOG_FORMAT` | No | `json` | `json` o `text`. |
| `BLOG_DATABASE_POOL_SIZE` | No | `5` | Tamaño del pool. |
| `BLOG_DATABASE_POOL_MAX_OVERFLOW` | No | `5` | Conexiones adicionales. |
| `BLOG_DATABASE_POOL_RECYCLE_SECONDS` | No | `1800` | Reciclado de conexiones. |
| `BLOG_DATABASE_CONNECT_TIMEOUT_SECONDS` | No | `10` | Tiempo máximo de conexión. |
| `BLOG_DATABASE_ECHO` | No | `false` | Registro de SQL. Prohibido en `production`. |

**`.env` está ignorado por Git y nunca se versiona.** En la nube, estas mismas variables
provienen de AWS SSM Parameter Store.

## 7. Estructura

```
app/
├── main.py                    create_app() y la instancia ASGI
├── api/
│   └── health.py              endpoints técnicos
├── modules/                   módulos de negocio (vacío hasta Task/008)
└── shared/
    ├── configuration/         configuración tipada y validada
    ├── logging/               log estructurado en JSON
    ├── errors/                jerarquía de errores y su traducción a HTTP
    └── database/              base declarativa, motor y sesiones
alembic/                       migraciones
tests/                         pruebas unitarias
tests/integration/             pruebas que requieren PostgreSQL
```

La división primaria es **por dominio, no por capa técnica**, y las capas de cada módulo se
crean **solo cuando resuelven un problema real**: ver
[ADR-004](../personal-blog-infra/docs/adr/ADR-004-modular-monolith.md) y
[software-architecture.md](../personal-blog-infra/docs/architecture/software-architecture.md).

## 8. Endpoints

| Método | Ruta | Propósito |
| --- | --- | --- |
| `GET` | `/health` | Vivacidad del proceso. No comprueba dependencias. |
| `GET` | `/openapi.json` | Especificación OpenAPI generada. |
| `GET` | `/docs` | Documentación interactiva. |

`/health` queda **fuera** de `/api/v1` a propósito: el prefijo versiona el contrato de datos
con el frontend, mientras que la sonda de vivacidad la consume la plataforma y no debe
cambiar de ruta cuando el contrato pase a `v2`.

`GET /ready` —la comprobación real de PostgreSQL y del almacenamiento— corresponde a
`Task/017`. Los recursos de contenido llegan en `Task/009`.

## 9. Migraciones

```powershell
alembic current            # revisión aplicada
alembic history --verbose  # historial
alembic upgrade head       # aplicar
alembic downgrade -1       # revertir la última
```

La URL de conexión **no** está en `alembic.ini`: `alembic/env.py` la obtiene de la
configuración de la aplicación, que la lee del entorno.

La migración `0001` es **fundacional y no crea objetos**: establece el control de versiones
del esquema. El modelo de datos del blog es `Task/008`. Toda migración posterior debe
aplicar **y** revertir.

## 10. Pruebas y calidad

```powershell
pytest                      # suite completa (la integración se omite sin PostgreSQL)
pytest --cov                # con cobertura
pytest -m integration       # solo integración
pytest -W error             # ninguna advertencia puede pasar inadvertida
ruff check .                # lint
ruff format --check .       # formato
mypy                        # tipado estático (modo strict)
```

Las pruebas de `tests/integration/` necesitan PostgreSQL. Se activan definiendo:

```powershell
$env:PERSONAL_BLOG_TEST_DATABASE_URL = "postgresql://<usuario>:<clave>@127.0.0.1:55432/personal_blog"
```

Sin esa variable **se omiten**, no fallan: la suite sigue siendo ejecutable sin Docker.

El proyecto **no silencia advertencias**: no hay `filterwarnings` en `pyproject.toml`, y
`pytest -W error` termina con **0 warnings**. El cliente de pruebas es **`httpx2`**, que es
el que `starlette.testclient` exige desde Starlette 1.3; con el `httpx` clásico el import
emite `StarletteDeprecationWarning` y `-W error` falla. Si eso ocurre, el entorno tiene
dependencias antiguas: reinstala con `pip install -r requirements-dev.txt`.

### Marcas de tiempo

Los logs se emiten **siempre en UTC**, con la forma `2026-08-11T20:15:30.123Z`, en Windows y
dentro del contenedor por igual: la conversión es explícita y no depende de la zona horaria
del sistema ni de la variable `TZ`. En una máquina de desarrollo en UTC−6, la marca del log
**no** coincide con el reloj de la pantalla, y es lo correcto.
`tests/test_logging_utc.py` lo verifica con instantes conocidos.

## 11. Docker

```powershell
docker build -t personal-blog-backend:local .

docker run --rm -p 127.0.0.1:8000:8000 `
  --network personal-blog-local-data `
  -e "BLOG_DATABASE_URL=postgresql://<usuario>:<clave>@personal-blog-local-postgres:5432/personal_blog" `
  personal-blog-backend:local
```

La imagen usa una versión de parche fija de Python, ejecuta como **usuario sin
privilegios** y trae un `HEALTHCHECK` contra `/health`. **No contiene secretos**: las
credenciales se inyectan en tiempo de ejecución.

La incorporación del backend al Docker Compose del entorno corresponde a `Task/007`.

---

## 12. Estrategia de ramas

| Rama | Propósito |
| --- | --- |
| `main` | Versión estable o liberable. |
| `dev` | Integración de tareas aprobadas. |
| `Task/<numero>-<nombre>` | Trabajo aislado de una tarea, creado desde `dev`. |

Una tarea que afecta a varios repositorios usa **el mismo nombre de rama** en todos.
No se hace merge automático hacia `main`.

## 13. Fuente de verdad de la planificación

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

## 14. Tareas previstas para este repositorio

`Task/005`, `Task/008`, `Task/009`, `Task/010`, `Task/011`, `Task/012`, `Task/023`,
`Task/024`, `Task/038`, y participación en `Task/007`, `Task/016`, `Task/017`,
`Task/018`, `Task/022`, `Task/036`, `Task/040`.

## 15. Contribución

Ver [CONTRIBUTING.md](CONTRIBUTING.md).
