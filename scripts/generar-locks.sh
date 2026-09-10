#!/bin/sh
# ---------------------------------------------------------------------------
# personal-blog-backend — generacion de los locks de dependencias (Task/020)
#
# Fuente unica de los argumentos de `uv pip compile`. La CI y el desarrollador
# ejecutan ESTE archivo, nunca los comandos sueltos: `uv` escribe el comando
# recibido en la cabecera de cada lock, asi que dos invocaciones con banderas
# distintas producirian cabeceras distintas y la comprobacion de desfase del
# workflow fallaria sin que hubiera cambiado ninguna dependencia.
#
# Entrada:  pyproject.toml  (unica fuente manual de dependencias)
# Salida:   requirements.lock       — ejecucion
#           requirements-dev.lock   — ejecucion + desarrollo
#
# Uso:
#   uv --version        # debe ser la version fijada en el workflow
#   sh scripts/generar-locks.sh
#
# `--exclude-newer` fija la foto del indice: la resolucion es una funcion pura
# de (pyproject.toml, version de uv, esa fecha), y por eso la CI puede
# regenerar y comparar con `git diff --exit-code`. Sin esa bandera, publicar
# una version nueva de cualquier transitiva romperia la comparacion sin que
# nadie hubiera tocado el proyecto.
#
# Actualizar dependencias es, por tanto, un acto DELIBERADO: se mueve la fecha,
# se regeneran los locks, se ejecutan los gates y se revisa el diff.
# ---------------------------------------------------------------------------
set -eu

cd "$(dirname "$0")/.."

FECHA_DEL_INDICE='2026-09-10T00:00:00Z'
PLATAFORMA='x86_64-unknown-linux-gnu'
PYTHON='3.12'

# `--quiet` solo evita que uv repita el lock entero por la salida estandar. No
# aparece en la cabecera que uv escribe dentro del archivo, asi que el contenido
# generado es identico con la bandera y sin ella.
uv pip compile pyproject.toml --quiet \
  --generate-hashes \
  --python-version "$PYTHON" \
  --python-platform "$PLATAFORMA" \
  --exclude-newer "$FECHA_DEL_INDICE" \
  --output-file requirements.lock

uv pip compile pyproject.toml --extra dev --quiet \
  --generate-hashes \
  --python-version "$PYTHON" \
  --python-platform "$PLATAFORMA" \
  --exclude-newer "$FECHA_DEL_INDICE" \
  --output-file requirements-dev.lock
