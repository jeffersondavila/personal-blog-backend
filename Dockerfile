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
FROM python:3.12.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Entorno virtual propio: se copia entero a la imagen final, sin arrastrar pip
# ni las herramientas de construccion.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Solo el archivo de dependencias: una capa que se reaprovecha mientras las
# versiones no cambien.
#
# Las dependencias directas estan fijadas con `==`. El bloqueo completo con
# hashes exige resolver en Linux, lo que corresponde a la CI (`Task/020`).
COPY requirements.txt ./
RUN pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Imagen final
# ---------------------------------------------------------------------------
FROM python:3.12.13-slim AS runtime

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
