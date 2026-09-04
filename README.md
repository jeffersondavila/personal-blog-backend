# personal-blog-backend

API del blog personal. **FastAPI + PostgreSQL.**

> **Estado: backend funcional del MVP.**
> `Task/005` establece la base técnica —configuración, log, errores, acceso a datos,
> migraciones, pruebas y `Dockerfile`—; `Task/008` el modelo de datos; `Task/009` la API
> pública; `Task/010` el almacenamiento de objetos; `Task/011` la autenticación
> administrativa; y `Task/012` la **API administrativa**.
>
> *Encabezado corregido en `Task/012`: seguía describiendo el estado de `Task/005`, que
> dejó de ser cierto con `Task/008`.*

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
| **Etapa** | ETAPA 03 — Dominio y Backend |
| **Tarea en curso** | `Task/010-Almacenamiento-Compatible-S3` |
| **Implementación** | Fundación (`Task/005`), modelo de datos (`Task/008`), API pública (`Task/009`) y almacenamiento de objetos (`Task/010`) |
| **Python** | 3.12 |
| **Endpoints** | `GET /health` y los **diez** recursos públicos de `/api/v1`, más `GET /openapi.json` y `GET /docs` |
| **Modelo de datos** | 14 tablas; migración `0002` es `head` |
| **Almacenamiento** | `ObjectStorage` con `MinIOStorage` y `S3Storage` |

> Esta tabla se había quedado en `Task/005`. Se corrigió en `Task/010`; la
> fuente de verdad del estado sigue siendo `STATUS.md`, enlazado abajo.

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
| `BLOG_STORAGE_BUCKET` | **Sí** | — | Bucket de los medios. Sin él el proceso no arranca. |
| `BLOG_STORAGE_PROVIDER` | No | `minio` | `minio` o `s3`. `minio` está **prohibido** en `production`. |
| `BLOG_STORAGE_REGION` | No | `us-east-1` | Región declarada al firmar. |
| `BLOG_STORAGE_ENDPOINT_URL` | Con `minio` | — | Endpoint **operativo**: el que usa el backend. Con `s3` se omite en producción. |
| `BLOG_STORAGE_ACCESS_ENDPOINT_URL` | No | el operativo | Endpoint **de acceso**: el anfitrión que aparece en el enlace temporal. Solo hace falta cuando el consumidor del enlace no ve el mismo anfitrión que el backend, que es el caso en Docker. |
| `BLOG_STORAGE_ACCESS_KEY` | Con `minio` | — | Clave de acceso. Con `s3` la aporta el rol de la Lambda. |
| `BLOG_STORAGE_SECRET_KEY` | Con `minio` | — | Secreto. **Nunca se imprime**: `SecretStr` y fuera de `repr`. |
| `BLOG_STORAGE_ACCESS_TTL_SECONDS` | No | `900` | Validez del enlace temporal de una imagen (60..604800). |

> **Por qué hay dos endpoints.** Dentro de Docker Compose el backend alcanza
> MinIO como `http://minio:9000`, pero el enlace que devuelve la API lo consume
> el **navegador del host**, que no resuelve ese nombre. Y no puede corregirse
> después: el anfitrión forma parte de la firma SigV4, así que reescribirlo
> produce `403 SignatureDoesNotMatch`. El enlace se firma contra
> `BLOG_STORAGE_ACCESS_ENDPOINT_URL` desde el principio. Ejecutando el backend
> directamente en el host los dos coinciden y la segunda variable se omite.

**`.env` está ignorado por Git y nunca se versiona.** En la nube, estas mismas variables
provienen de AWS SSM Parameter Store.

## 7. Estructura

```
app/
├── main.py                    create_app() y la instancia ASGI
├── api/
│   └── health.py              endpoints técnicos
├── modules/                   módulos de negocio
│   ├── models.py              registro único de los modelos ORM
│   ├── posts/                 domain + application + infrastructure + presentation
│   ├── book_reviews/          domain (con valoración) + application + infra + presentation
│   ├── videos/                igual, sin Markdown y sin despublicación
│   ├── projects/              igual, con el estado del trabajo aparte del de publicación
│   ├── profile/               application + infrastructure + presentation (singleton)
│   ├── tags/                  application + infrastructure + presentation
│   ├── media/                 domain + application + infrastructure + presentation
│   ├── authentication/        domain + application + infrastructure + presentation
│   └── audit/                 domain (puertos y catálogo) + infrastructure
└── shared/
    ├── configuration/         configuración tipada y validada
    ├── logging/               log estructurado en JSON
    ├── errors/                jerarquía de errores y su traducción a HTTP
    ├── pagination/            parámetros y envoltura de colección paginada
    ├── slug/                  formato y generación del slug (`app/shared/slug.py`)
    ├── reloj/                 fuente del instante actual (`app/shared/reloj.py`)
    ├── storage/               ObjectStorage, MinIOStorage y S3Storage
    └── database/              base declarativa, mixins, tipos, motor y sesiones
alembic/                       migraciones
tests/unit/                    dominio y aplicación: rápidas, sin infraestructura
tests/contract/                contratos HTTP y de ObjectStorage
tests/integration/             pruebas que requieren PostgreSQL real (y MinIO)
tests/                         resto de pruebas unitarias (fundación, Task/005)
```

La división primaria es **por dominio, no por capa técnica**, y las capas de cada módulo se
crean **solo cuando resuelven un problema real**: ver
[ADR-004](../personal-blog-infra/docs/adr/ADR-004-modular-monolith.md) y
[software-architecture.md](../personal-blog-infra/docs/architecture/software-architecture.md).

**El dominio es Python plano.** Ningún módulo `domain` importa FastAPI, SQLAlchemy ni
Alembic, y `tests/unit/test_independencia_del_dominio.py` lo comprueba importando cada uno
en un intérprete limpio.

### 7.1 Modelo de datos

El modelo físico del MVP —tablas, claves, restricciones, índices y el reparto de
invariantes entre dominio, PostgreSQL y tareas futuras— está documentado en
[data-model.md](../personal-blog-infra/docs/architecture/data-model.md). El modelo
**conceptual** sigue siendo
[CONTENT_MODEL.md](../personal-blog-infra/docs/product/CONTENT_MODEL.md).

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
del esquema. La migración `0002` (`Task/008`) crea el modelo de datos completo del MVP: 14
tablas, sus restricciones e índices. **No inserta ningún dato**: el perfil y el
administrador contienen datos personales reales, que no se versionan.

Toda migración debe aplicar **y** revertir. El ciclo `upgrade` → `downgrade` → `upgrade` se
verifica contra PostgreSQL real en `tests/integration/test_migrations.py`, y
`tests/integration/test_esquema_fisico.py` comprueba además que el esquema aplicado no se
desvía del modelo (`compare_metadata`).

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

### 10.1 Integración: base de datos **dedicada de pruebas**

Las pruebas de `tests/integration/` necesitan PostgreSQL y son **destructivas**: ejecutan
`alembic downgrade base`, que revierte el esquema entero.

> **Nunca apuntes esta variable a `personal_blog`**, la base cotidiana de desarrollo. Desde
> `Task/008` contendrá el contenido real del blog y un `downgrade base` lo destruiría.
> *(Corregido en `Task/005.6`: este README indicaba aquí `.../personal_blog`.)*

Se activan definiendo la variable hacia la base **de pruebas**:

```powershell
$env:PERSONAL_BLOG_TEST_DATABASE_URL = "postgresql://<usuario>:<clave>@127.0.0.1:55432/personal_blog_test"
```

Crear y **marcar** esa base es un paso previo, descrito en el
[runbook del entorno local §9](../personal-blog-infra/docs/runbooks/local-environment.md).
La marca no es opcional: la suite se niega a ejecutarse contra una base que no la lleve.

Comportamiento, sin ambigüedad posible:

| Situación | Resultado |
| --- | --- |
| Variable **no definida** | La integración se **omite** (`SKIP`). La suite sigue siendo ejecutable sin Docker. |
| Variable definida y todo correcto | La integración **se ejecuta**. |
| Variable definida pero PostgreSQL no responde, o las credenciales son incorrectas | **FALLA.** Nunca se degrada a `skip`: eso dejaría la suite verde justo cuando el acceso a datos está roto. |
| Destino sin sufijo `_test` o sin la marca de pruebas | **FALLA** antes de ejecutar nada. |

Regla completa:
[BACKEND_TESTING_STRATEGY §8.3](../personal-blog-infra/docs/project-management/BACKEND_TESTING_STRATEGY.md).

### 10.2 Integración: almacenamiento de objetos **de pruebas**

Desde `Task/010`, las pruebas de contrato de `ObjectStorage` y las de medios
necesitan el MinIO del entorno local. Se activan con tres variables:

```powershell
$env:PERSONAL_BLOG_TEST_STORAGE_ENDPOINT_URL = "http://127.0.0.1:9000"
$env:PERSONAL_BLOG_TEST_STORAGE_ACCESS_KEY   = "<MINIO_ROOT_USER del .env de infra>"
$env:PERSONAL_BLOG_TEST_STORAGE_SECRET_KEY   = "<MINIO_ROOT_PASSWORD del .env de infra>"
```

Mismas dos reglas que con PostgreSQL: **sin la variable del endpoint se omiten;
con ella, cualquier fallo es `FAIL`**, nunca `skip`.

> **Estas pruebas CREAN Y BORRAN un bucket entero.** No hace falta preparar
> nada: la suite crea el suyo, con el prefijo `personal-blog-test-`, y lo
> destruye al terminar. **`BLOG_STORAGE_BUCKET` nunca es alcanzable como
> destino**, así que el bucket de desarrollo no corre riesgo.

La guarda es *fail-closed* y comprueba tres cosas antes de tocar nada:

| Barrera | Regla |
| --- | --- |
| Anfitrión | Solo `localhost`, `127.0.0.1` y equivalentes. Un endpoint remoto —**Amazon S3 incluido**— es un fallo, no un aviso |
| Bucket | Lo crea la propia suite, con nombre único y prefijo inequívoco |
| Borrado | Vuelve a comprobar el prefijo justo antes de borrar |

El bucket de la **aplicación** (`personal-blog-media`) es otra cosa y se crea
una vez, a mano:
[runbook del entorno local §10](../personal-blog-infra/docs/runbooks/local-environment.md).

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
| `main` | Versión estable o liberable. **Única base permitida de las ramas Task.** |
| `dev` | **Solo integración** de tareas aprobadas. **Nunca base de una Task.** |
| `Task/<numero>-<nombre>` | Trabajo aislado de una tarea, creado **desde `main`**. |

> **Invariante crítico:** toda rama `Task/<...>` nace desde `main` actualizado y limpio.
> `dev` nunca es base de una Task. Motivo y validaciones:
> [WORKFLOW §2.1](../personal-blog-infra/docs/project-management/WORKFLOW.md).

Una tarea que afecta a varios repositorios usa **el mismo nombre de rama** en todos, y
**todas nacen de `main`**. No se hace merge automático hacia `main`.

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
