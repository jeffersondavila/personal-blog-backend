# ---------------------------------------------------------------------------
# personal-blog-backend — imagen del servicio (Task/005)
#
# Imagen para la ejecucion LOCAL en Docker. El destino en produccion es AWS
# Lambda mediante un artefacto ZIP (`Task/024`), no esta imagen (ADR-003).
#
# Su incorporacion al Docker Compose del entorno corresponde a `Task/007`.
#
# Construccion (desde la raiz del repositorio):
#   docker build -t personal-blog-backend:local .
#
# Ejecucion contra el PostgreSQL del entorno local:
#   docker run --rm -p 8000:8000 \
#     --network personal-blog-local-data \
#     -e BLOG_DATABASE_URL="postgresql://<usuario>:<clave>@personal-blog-local-postgres:5432/personal_blog" \
#     personal-blog-backend:local
#
# La imagen NO contiene secretos: toda credencial se inyecta en tiempo de
# ejecucion por variables de entorno (requisito S-10).
# ---------------------------------------------------------------------------

# Version de parche explicita: `3.12-slim` es una etiqueta movil que cambiaria
# sin aviso (misma regla que en el Compose de personal-blog-infra).
FROM python:3.12.14-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Entorno virtual propio: se copia entero a la imagen final, sin arrastrar pip
# ni las herramientas de construccion.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Solo el archivo de dependencias: una capa que se reaprovecha mientras el lock
# no cambie.
#
# `requirements.lock` lleva las transitivas completas y un `--hash=sha256:...`
# por distribucion, resueltas para Linux x86_64 y CPython 3.12 (`Task/020`,
# cierre de R-14). `--require-hashes` es fail-closed por partida doble: pip
# rechaza cualquier archivo cuyo digest no coincida **y** exige que todo
# requisito que vaya a instalar este fijado con `==` y traiga hash.
#
# El modo NO desactiva la resolucion de dependencias —eso es `--no-deps`, otra
# opcion distinta—: pip sigue recorriendo el arbol y aborta en cuanto encuentra
# una dependencia sin fijar ni hashear. Lo que hace que aqui no quede nada por
# resolver es el propio lock, que enumera el cierre transitivo completo. Por
# eso la imagen no puede traer una transitiva distinta de la que validaron las
# pruebas, y un lock incompleto falla en lugar de instalarse en silencio.
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock \
    && python -m pip uninstall --yes pip

# ---------------------------------------------------------------------------
# Imagen final
# ---------------------------------------------------------------------------
FROM python:3.12.14-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime

# El digest del `FROM` fija el punto de partida, pero no las correcciones que
# Debian publica despues. Esta capa aplica las actualizaciones de seguridad
# disponibles en el momento de la construccion sobre los paquetes que ya trae
# la base: con `--no-install-recommends` no incorpora ninguno nuevo ni retira
# ninguno.
#
# Consecuencia aceptada para esta imagen local/CI (`Task/020.3`, B-020.3-C): el
# sistema de archivos final deja de estar determinado unicamente por el digest.
# Sin la capa, el gate S-09 falla en cuanto Debian publica una version corregida
# de un CVE que la base todavia arrastra, y la alternativa —esperar a que se
# reconstruya `python:3.12.14-slim` aguas arriba— no tiene fecha conocida. La
# decision no se extiende por si sola al resto de imagenes del proyecto.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# El runtime no incorpora paquetes adicionales: solo actualiza los que la base
# ya traia. Retira tambien el pip global de la base.
RUN /usr/local/bin/python -m pip uninstall --yes pip

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Usuario sin privilegios: el proceso no necesita root y no debe tenerlo.
RUN groupadd --system --gid 1001 blog \
    && useradd --system --uid 1001 --gid blog --home-dir /app --no-create-home blog

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=blog:blog app ./app
COPY --chown=blog:blog alembic ./alembic
COPY --chown=blog:blog alembic.ini ./alembic.ini

USER blog

EXPOSE 8000

# Sonda de vivacidad con la biblioteca estandar: la imagen no incluye `curl` ni
# `wget` y anadirlos solo para esto ampliaria la superficie de ataque.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

# Un solo worker: la concurrencia real la aporta el entorno de ejecucion
# (varias invocaciones en Lambda, varias replicas en local si hicieran falta).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
