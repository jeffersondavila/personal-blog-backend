"""Construccion y validacion del artefacto ZIP de Lambda (`Task/024`).

Produce el paquete de despliegue del backend para **AWS Lambda / Python 3.12 /
Linux x86_64**, de forma **reproducible byte a byte**, y lo valida: *layout*,
inventario frente al lock, contenido prohibido, arquitectura de los binarios,
tamano frente a las cuotas de Lambda, *checksum* y manifiesto.

Por que existe
--------------

`Task/023` dejo el adaptador `app/lambda_handler.py`, no un artefacto. Y el
backend se desarrolla en **Windows**, mientras que **13 de las 41
distribuciones de ejecucion traen binarios nativos**: copiar un `.venv` de
Windows a un ZIP produce un paquete que no arranca, y el fallo aparece por
primera vez en la nube. Por eso las dependencias se instalan **siempre dentro
de Linux**, en la imagen oficial del runtime de Lambda fijada por digest.

Windows **orquesta** Docker; Windows **nunca** aporta bytes al artefacto.

Reglas de reproducibilidad
--------------------------

El ZIP se escribe **dentro del contenedor** (decision D-024-B): los bytes de
DEFLATE dependen de la version de `zlib`, y escribiendolo dentro quedan fijados
por el mismo digest que todo lo demas. Sobre esa base se controlan:

- mismas fuentes y mismos *wheels*, exigidos por hash desde `requirements.lock`;
- directorio de construccion nuevo y vacio en cada ejecucion —el contenedor es
  efimero, asi que `A` y `B` no comparten nada—;
- orden **lexicografico** de las entradas y rutas POSIX relativas;
- *timestamp* fijo `1980-01-01 00:00:00`, permisos `0644` y sistema de origen
  Unix, iguales para toda entrada;
- DEFLATE con nivel fijo; sin comentario de archivo; sin *bytecode*;
- `locale` y zona horaria explicitos durante el empaquetado.

**Alcance de la garantia** (decision D-024-F). La reproducibilidad demostrada
vale con las **mismas fuentes**, los **mismos locks**, los **mismos artefactos
de dependencias**, las **mismas herramientas fijadas** y el **mismo entorno de
construccion controlado**. No se promete que PyPI conserve los archivos
indefinidamente, ni reproducibilidad universal en cualquier maquina o con
cualquier herramienta.

Sobre las cuotas de Lambda
--------------------------

Verificadas en la documentacion oficial el 2026-09-13:

- **50 MB** comprimido *«when uploaded through the Lambda API or SDKs»*. Es el
  limite de **carga directa**: un paquete mayor se despliega desde Amazon S3.
  Este proyecto **no** afirma que Lambda prohiba todo ZIP mayor.
- **250 MB** descomprimido, *«including layers and custom runtimes»*.

La propia pagina advierte que usa **MB por 1 024 KB**, de donde salen los
valores exactos en bytes que fija este modulo.

Subcomandos
-----------

| Subcomando | Que hace |
| --- | --- |
| `construir` | Lanza la construccion dentro del runtime y deja ZIP, `.sha256` y manifiesto |
| `verificar` | Revalida un artefacto ya construido, leyendo **solo el ZIP** |
| `comparar` | Demuestra `A == B`: bytes, SHA-256 y manifiesto |
| `ejecutar-aislado` | Ejecuta el *handler* desde el ZIP en un proceso Linux aislado |
| `control-negativo` | Demuestra que el aislamiento del *harness* es real |
| `construir-en-linux` | Uso interno: es lo que corre **dentro** del contenedor |

No se introduce ninguna familia de *tooling* nueva (decision D-024-J): solo
biblioteca estandar de Python, con Docker como autoridad Linux. En particular
esta tarea **no anade ningun script de shell** en ningun repositorio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile
import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Constantes del artefacto
# ---------------------------------------------------------------------------

#: Imagen oficial del runtime de Lambda para Python 3.12. La **etiqueta sola no
#: es garantia de nada**: se mueve. Lo que fija la construccion es el digest.
#: Observado el 2026-09-13: base Amazon Linux 2023, glibc 2.34, Python 3.12.14,
#: pip 25.0.1, zlib 1.2.11. Con glibc 2.34 son compatibles `manylinux2014`,
#: `manylinux_2_26`, `manylinux_2_28` y `manylinux_2_34`, asi que **no** se
#: impone ninguna de ellas: la autoridad es la carga real en este runtime.
ETIQUETA_DEL_RUNTIME: Final = "public.ecr.aws/lambda/python:3.12"
DIGEST_DEL_RUNTIME: Final = (
    "sha256:a89893d9c93a9ffbf9e35ca32d7cadc635cbf3a9aec94480c75ed07150a05daa"
)
DIGEST_DEL_RUNTIME_AMD64: Final = (
    "sha256:e369e098d9db9eafa3238fe827e4756e2016159908b9426b78e2051c08f647e3"
)
REFERENCIA_DEL_RUNTIME: Final = f"{ETIQUETA_DEL_RUNTIME}@{DIGEST_DEL_RUNTIME}"

#: No existe ninguna decision que autorice ARM64 en este proyecto.
PLATAFORMA: Final = "linux/amd64"
ARQUITECTURA_ELF: Final = 62  # EM_X86_64

#: Fijado por `Task/023`. Lo consume `Task/025` al configurar la funcion.
NOMBRE_DEL_HANDLER: Final = "app.lambda_handler.handler"
NOMBRE_DEL_ARTEFACTO: Final = "personal-blog-backend-lambda.zip"
NOMBRE_DEL_MANIFIESTO: Final = "manifiesto.json"
NOMBRE_DE_LA_CONSTRUCCION: Final = "construccion.json"

#: Cuotas de empaquetado de Lambda, en bytes. Inclusivas: la cuota es el maximo
#: admitido, no el primer valor rechazado.
LIMITE_COMPRIMIDO: Final = 52_428_800
LIMITE_DESCOMPRIMIDO: Final = 262_144_000

#: `1980-01-01 00:00:00` es el **minimo representable** en el formato de fecha
#: MS-DOS que guarda el ZIP. El *epoch* de Unix no es expresable y `zipfile` lo
#: rechaza; comprobado antes de adoptarlo (decision D-024-C).
MARCA_DE_TIEMPO: Final = (1980, 1, 1, 0, 0, 0)
PERMISOS_NORMALIZADOS: Final = 0o644
SISTEMA_DE_ORIGEN_UNIX: Final = 3
NIVEL_DE_COMPRESION: Final = 9

#: Rutas dentro del contenedor. Son fijas a proposito: el manifiesto no puede
#: llevar la ruta local de quien construye, o `A == B` dejaria de cumplirse
#: entre dos maquinas.
FUENTE_EN_EL_CONTENEDOR: Final = "/src"
SALIDA_EN_EL_CONTENEDOR: Final = "/salida"
TRABAJO_EN_EL_CONTENEDOR: Final = "/build"
ARBOL_EN_EL_CONTENEDOR: Final = "/build/arbol"


class ErrorDeEmpaquetado(RuntimeError):  # noqa: N818
    """El artefacto no se puede construir o no supera una validacion."""


# ---------------------------------------------------------------------------
# Politica de contenido
# ---------------------------------------------------------------------------

#: Un segmento con cualquiera de estos nombres invalida el artefacto.
SEGMENTOS_PROHIBIDOS: Final = frozenset(
    {
        ".git",
        ".github",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".hypothesis",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "htmlcov",
        ".idea",
        ".vscode",
    }
)

#: Directorios de primer nivel del repositorio que **nunca** viajan: son
#: pruebas y utilidades de mantenimiento, no codigo de ejecucion.
PRIMER_NIVEL_PROHIBIDO: Final = frozenset({"tests", "scripts", "alembic.ini", ".github"})

#: Extensiones que no pueden aparecer. `.pyd` y `.dll` son de Windows; el
#: *bytecode* se excluye con `--no-compile` y ademas se veta; el resto es
#: material de clave.
EXTENSIONES_PROHIBIDAS: Final = frozenset(
    {".pyc", ".pyo", ".pyd", ".dll", ".exe", ".msi", ".p12", ".pfx", ".jks", ".keystore", ".key"}
)

#: Nombres que delatan una credencial con independencia de donde aparezcan.
NOMBRES_PROHIBIDOS: Final = frozenset(
    {
        "credentials",
        "credentials.json",
        ".netrc",
        ".pypirc",
        ".git-credentials",
        ".htpasswd",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        ".coverage",
    }
)

#: `.pem` esta prohibido **salvo** este conjunto exacto. `botocore` empaqueta su
#: propio almacen de CA, que es un archivo publico y necesario para verificar
#: TLS; sin esta excepcion el gate rechazaria una dependencia legitima del lock.
#: La excepcion es por ruta exacta, de modo que cualquier otro `.pem` sigue
#: rompiendo la construccion.
PEM_PERMITIDOS: Final = frozenset({"botocore/cacert.pem"})

#: Prefijos que delatan un *layout* equivocado. `python/` es el prefijo de las
#: **layers** de Lambda, y esta tarea no crea layers.
PREFIJOS_DE_LAYOUT_PROHIBIDOS: Final = (
    "python/",
    "lambda_package/",
    "site-packages/",
    ".venv/",
    "venv/",
    "var/task/",
)

#: Sin estos tres archivos en la raiz el artefacto no es desplegable.
ARCHIVOS_REQUERIDOS: Final = ("app/__init__.py", "app/main.py", "app/lambda_handler.py")

#: Directorios de cache y *bytecode* que la normalizacion elimina antes de
#: recolectar entradas.
DIRECTORIOS_A_ELIMINAR: Final = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis", ".tox"}
)
EXTENSIONES_A_ELIMINAR: Final = frozenset({".pyc", ".pyo"})

_RUTA_DE_WINDOWS: Final = re.compile(r"^[A-Za-z]:[\\/]")


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Entrada:
    """Un archivo del artefacto: su ruta dentro del ZIP y su origen en disco."""

    ruta: str
    origen: Path


@dataclass(frozen=True)
class Medida:
    """Tamano del artefacto y reparto por distribucion."""

    archivos: int
    bytes_comprimidos: int
    bytes_descomprimidos: int
    por_distribucion: Mapping[str, int]

    def reemplazando(
        self,
        *,
        bytes_comprimidos: int | None = None,
        bytes_descomprimidos: int | None = None,
    ) -> Medida:
        """Devuelve una copia con los tamanos sustituidos.

        Existe para poder probar los gates en sus tres puntos —por debajo, justo
        en el umbral y por encima— sin fabricar un artefacto de 50 MB.
        """
        return Medida(
            archivos=self.archivos,
            bytes_comprimidos=(
                self.bytes_comprimidos if bytes_comprimidos is None else bytes_comprimidos
            ),
            bytes_descomprimidos=(
                self.bytes_descomprimidos if bytes_descomprimidos is None else bytes_descomprimidos
            ),
            por_distribucion=self.por_distribucion,
        )


# ---------------------------------------------------------------------------
# Lock e inventario
# ---------------------------------------------------------------------------


def normalizar_nombre(nombre: str) -> str:
    """Normaliza un nombre de distribucion segun PEP 503."""
    return re.sub(r"[-_.]+", "-", nombre).strip().lower()


def distribuciones_del_lock(texto: str) -> dict[str, str]:
    """Lee un lock generado con `--generate-hashes`.

    Exige que **toda** distribucion traiga al menos un `--hash`: un lock sin
    hashes no es *fail-closed* y no puede producir un artefacto reproducible,
    asi que se rechaza en lugar de degradarse en silencio.
    """
    encontradas: dict[str, str] = {}
    requisito: str | None = None
    con_hash = False

    def cerrar() -> None:
        if requisito is not None and not con_hash:
            raise ErrorDeEmpaquetado(
                f"el lock no fija hash para {requisito!r}: no es fail-closed y no se admite"
            )

    for linea in texto.splitlines():
        desnuda = linea.strip()
        if not desnuda or desnuda.startswith("#"):
            continue
        if linea[0].isspace():
            con_hash = con_hash or "--hash=" in desnuda
            continue
        cerrar()
        nombre, separador, resto = desnuda.partition("==")
        if not separador:
            requisito, con_hash = None, False
            continue
        requisito = nombre.strip()
        version = resto.split()[0].strip().rstrip("\\").strip()
        con_hash = "--hash=" in desnuda
        encontradas[normalizar_nombre(requisito)] = version
    cerrar()

    if not encontradas:
        raise ErrorDeEmpaquetado("el lock no declara ninguna distribucion")
    return encontradas


def distribuciones_instaladas(raiz: Path) -> dict[str, str]:
    """Lee el inventario real del arbol a partir de sus `*.dist-info`."""
    encontradas: dict[str, str] = {}
    for hijo in sorted(raiz.iterdir()):
        if hijo.is_dir() and hijo.name.endswith(".dist-info"):
            nombre, _, version = hijo.name[: -len(".dist-info")].rpartition("-")
            encontradas[normalizar_nombre(nombre)] = version
    return encontradas


def verificar_inventario(*, esperadas: Mapping[str, str], instaladas: Mapping[str, str]) -> None:
    """Exige que el arbol traiga **exactamente** lo que fija el lock."""
    faltan = sorted(set(esperadas) - set(instaladas))
    if faltan:
        raise ErrorDeEmpaquetado(f"faltan distribuciones del lock: {', '.join(faltan)}")

    sobran = sorted(set(instaladas) - set(esperadas))
    if sobran:
        raise ErrorDeEmpaquetado(f"distribuciones ajenas al lock de ejecucion: {', '.join(sobran)}")

    for nombre in sorted(esperadas):
        if instaladas[nombre] != esperadas[nombre]:
            raise ErrorDeEmpaquetado(
                f"{nombre}: el lock fija {esperadas[nombre]} y el arbol trae {instaladas[nombre]}"
            )


# ---------------------------------------------------------------------------
# Normalizacion y recoleccion
# ---------------------------------------------------------------------------


def normalizar_arbol(raiz: Path) -> list[str]:
    """Elimina *bytecode* y cachés. Devuelve lo eliminado, en orden estable."""
    eliminados: list[str] = []
    for carpeta, subcarpetas, archivos in os.walk(raiz, topdown=True):
        actual = Path(carpeta)
        for nombre in sorted(subcarpetas):
            if nombre in DIRECTORIOS_A_ELIMINAR:
                objetivo = actual / nombre
                shutil.rmtree(objetivo)
                eliminados.append(objetivo.relative_to(raiz).as_posix() + "/")
        subcarpetas[:] = [s for s in subcarpetas if s not in DIRECTORIOS_A_ELIMINAR]
        for nombre in sorted(archivos):
            if Path(nombre).suffix in EXTENSIONES_A_ELIMINAR:
                objetivo = actual / nombre
                objetivo.unlink()
                eliminados.append(objetivo.relative_to(raiz).as_posix())
    return sorted(eliminados)


def recolectar_entradas(raiz: Path) -> list[Entrada]:
    """Recoge los archivos del arbol en orden lexicografico y sin enlaces.

    Los enlaces simbolicos estan **prohibidos**: dentro de un ZIP son una
    entrada ambigua —unos extractores la siguen y otros la materializan— y
    ninguna distribucion del lock los usa, asi que rechazarlos no cuesta nada y
    elimina una superficie entera.
    """
    entradas: list[Entrada] = []
    for carpeta, subcarpetas, archivos in os.walk(raiz):
        actual = Path(carpeta)
        for nombre in sorted(subcarpetas):
            if (actual / nombre).is_symlink():
                relativa = (actual / nombre).relative_to(raiz).as_posix()
                raise ErrorDeEmpaquetado(f"enlace simbolico prohibido: {relativa}/")
        for nombre in sorted(archivos):
            origen = actual / nombre
            relativa = origen.relative_to(raiz).as_posix()
            if origen.is_symlink():
                raise ErrorDeEmpaquetado(f"enlace simbolico prohibido: {relativa}")
            entradas.append(Entrada(relativa, origen))
    return sorted(entradas, key=lambda entrada: entrada.ruta)


# ---------------------------------------------------------------------------
# Politicas de validacion
# ---------------------------------------------------------------------------


def verificar_layout(rutas: Iterable[str]) -> None:
    """Exige `app/` **en la raiz** del ZIP, con el *handler* presente."""
    materializadas = list(rutas)
    for ruta in materializadas:
        for prefijo in PREFIJOS_DE_LAYOUT_PROHIBIDOS:
            if ruta.startswith(prefijo):
                raise ErrorDeEmpaquetado(
                    f"layout invalido: {ruta!r} cuelga de {prefijo!r}. `app/` debe estar "
                    "directamente en la raiz del ZIP"
                )

    presentes = set(materializadas)
    faltan = [requerido for requerido in ARCHIVOS_REQUERIDOS if requerido not in presentes]
    if faltan:
        raise ErrorDeEmpaquetado(f"el artefacto no trae {', '.join(faltan)}")


def verificar_rutas(rutas: Sequence[str]) -> None:
    """Rechaza rutas absolutas, *path traversal* y entradas duplicadas."""
    vistas: set[str] = set()
    for ruta in rutas:
        if not ruta:
            raise ErrorDeEmpaquetado("entrada con ruta vacia")
        if ruta.startswith("/") or _RUTA_DE_WINDOWS.match(ruta) or "\\" in ruta:
            raise ErrorDeEmpaquetado(f"ruta absoluta o no POSIX: {ruta!r}")
        partes = ruta.split("/")
        if ".." in partes or "." in partes:
            raise ErrorDeEmpaquetado(f"ruta con '..' o '.': {ruta!r}")
        if ruta in vistas:
            raise ErrorDeEmpaquetado(f"entrada duplicada: {ruta!r}")
        vistas.add(ruta)


def verificar_contenido(rutas: Iterable[str]) -> None:
    """Aplica la politica de contenido prohibido del artefacto."""
    for ruta in rutas:
        partes = ruta.split("/")
        nombre = partes[-1]
        sufijo = Path(nombre).suffix.lower()

        for parte in partes:
            if parte in SEGMENTOS_PROHIBIDOS:
                raise ErrorDeEmpaquetado(f"contenido prohibido ({parte}): {ruta!r}")
            if parte == ".env" or parte.startswith(".env."):
                raise ErrorDeEmpaquetado(f"contenido prohibido (configuracion local): {ruta!r}")

        if partes[0] in PRIMER_NIVEL_PROHIBIDO:
            raise ErrorDeEmpaquetado(f"contenido prohibido (del repositorio): {ruta!r}")
        if nombre in NOMBRES_PROHIBIDOS:
            raise ErrorDeEmpaquetado(f"contenido prohibido (credencial): {ruta!r}")
        if sufijo in EXTENSIONES_PROHIBIDAS:
            raise ErrorDeEmpaquetado(f"contenido prohibido (extension {sufijo}): {ruta!r}")
        if sufijo == ".pem" and ruta not in PEM_PERMITIDOS:
            raise ErrorDeEmpaquetado(f"contenido prohibido (material de clave): {ruta!r}")


def verificar_cabeceras(cabeceras: Iterable[tuple[str, bytes]]) -> None:
    """Rechaza binarios de Windows y objetos ELF de otra arquitectura.

    Es el gate que hace imposible el error que esta tarea existe para evitar:
    un `.venv` de Windows empaquetado tal cual, o una rueda `aarch64` colada en
    un artefacto `x86_64`.
    """
    for ruta, cabecera in cabeceras:
        if cabecera[:2] == b"MZ":
            raise ErrorDeEmpaquetado(f"binario de Windows (PE/COFF) prohibido: {ruta!r}")
        if cabecera[:4] != b"\x7fELF":
            continue
        if len(cabecera) < 20:
            raise ErrorDeEmpaquetado(f"ELF truncado: {ruta!r}")
        if cabecera[4] != 2:
            raise ErrorDeEmpaquetado(f"ELF que no es de 64 bits: {ruta!r}")
        maquina = int.from_bytes(cabecera[18:20], "little")
        if maquina != ARQUITECTURA_ELF:
            raise ErrorDeEmpaquetado(
                f"arquitectura incompatible en {ruta!r}: e_machine={maquina}, "
                f"se esperaba {ARQUITECTURA_ELF} (x86-64)"
            )


def verificar_binarios(entradas: Iterable[Entrada]) -> None:
    """Aplica `verificar_cabeceras` leyendo el arbol en disco."""

    def cabeceras() -> Iterable[tuple[str, bytes]]:
        for entrada in entradas:
            with entrada.origen.open("rb") as archivo:
                yield entrada.ruta, archivo.read(64)

    verificar_cabeceras(cabeceras())


def verificar_tamano(medida: Medida) -> None:
    """Aplica las cuotas de empaquetado de Lambda. Son inclusivas."""
    if medida.bytes_comprimidos > LIMITE_COMPRIMIDO:
        raise ErrorDeEmpaquetado(
            f"el ZIP comprimido ocupa {medida.bytes_comprimidos} bytes y la cuota de carga "
            f"directa es {LIMITE_COMPRIMIDO}"
        )
    if medida.bytes_descomprimidos > LIMITE_DESCOMPRIMIDO:
        raise ErrorDeEmpaquetado(
            f"el contenido descomprimido ocupa {medida.bytes_descomprimidos} bytes y la cuota "
            f"es {LIMITE_DESCOMPRIMIDO}"
        )


# ---------------------------------------------------------------------------
# Escritura determinista del ZIP
# ---------------------------------------------------------------------------


def escribir_zip(entradas: Iterable[Entrada], destino: Path) -> None:
    """Escribe el ZIP de forma determinista.

    Cada entrada se construye a mano en lugar de usar `ZipInfo.from_file`,
    porque ese constructor hereda `mtime`, permisos y sistema de origen del
    archivo real: tres fuentes de variacion que romperian `A == B`. Solo se
    emiten entradas de archivo (decision D-024-D): Lambda no exige entradas de
    directorio y cada una seria superficie no determinista de mas.
    """
    ordenadas = sorted(entradas, key=lambda entrada: entrada.ruta)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as archivo:
        for entrada in ordenadas:
            informacion = zipfile.ZipInfo(entrada.ruta, date_time=MARCA_DE_TIEMPO)
            informacion.compress_type = zipfile.ZIP_DEFLATED
            informacion.create_system = SISTEMA_DE_ORIGEN_UNIX
            informacion.external_attr = (stat.S_IFREG | PERMISOS_NORMALIZADOS) << 16
            archivo.writestr(
                informacion,
                entrada.origen.read_bytes(),
                compresslevel=NIVEL_DE_COMPRESION,
            )


def sha256_de(ruta: Path) -> str:
    """SHA-256 de un archivo, leido por bloques."""
    resumen = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def sha256_de_texto(texto: str) -> str:
    """SHA-256 de un texto, normalizado a LF para no depender del checkout."""
    return hashlib.sha256(texto.replace("\r\n", "\n").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Medida
# ---------------------------------------------------------------------------


def _propietarios(entradas: Sequence[Entrada]) -> dict[str, str]:
    """Mapea cada ruta a su distribucion leyendo los `RECORD` de los wheels."""
    propietarios: dict[str, str] = {}
    for entrada in entradas:
        if not entrada.ruta.endswith(".dist-info/RECORD"):
            continue
        distribucion = normalizar_nombre(
            entrada.ruta.split("/")[0][: -len(".dist-info")].rpartition("-")[0]
        )
        try:
            contenido = entrada.origen.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover - RECORD ilegible
            continue
        for linea in contenido.splitlines():
            ruta = linea.split(",")[0].strip()
            if ruta:
                propietarios[ruta] = distribucion
    return propietarios


def medir(entradas: Iterable[Entrada], artefacto: Path) -> Medida:
    """Mide el artefacto y reparte los bytes descomprimidos por distribucion.

    El reparto usa el `RECORD` de cada *wheel* cuando existe —que es la fuente
    autoritativa de que archivo pertenece a que distribucion— y cae al primer
    segmento de la ruta cuando no. Asi `app/` queda atribuida a `app`, que es
    exactamente lo que interesa para **P-07**.
    """
    materializadas = sorted(entradas, key=lambda entrada: entrada.ruta)
    propietarios = _propietarios(materializadas)

    por_distribucion: dict[str, int] = {}
    total = 0
    for entrada in materializadas:
        tamano = entrada.origen.stat().st_size
        total += tamano
        primer_segmento = entrada.ruta.split("/")[0]
        if primer_segmento.endswith((".dist-info", ".libs", ".data")):
            sin_sufijo = primer_segmento.rsplit(".", 1)[0]
            respaldo = normalizar_nombre(sin_sufijo.rpartition("-")[0] or primer_segmento)
        else:
            respaldo = primer_segmento
        distribucion = propietarios.get(entrada.ruta, respaldo)
        por_distribucion[distribucion] = por_distribucion.get(distribucion, 0) + tamano

    return Medida(
        archivos=len(materializadas),
        bytes_comprimidos=artefacto.stat().st_size,
        bytes_descomprimidos=total,
        por_distribucion=dict(sorted(por_distribucion.items())),
    )


# ---------------------------------------------------------------------------
# Manifiesto
# ---------------------------------------------------------------------------


def construir_manifiesto(
    *,
    entradas: Iterable[Entrada],
    artefacto: Path,
    medida: Medida,
    distribuciones: Mapping[str, str],
    lock: str,
    entorno: Mapping[str, str],
) -> dict[str, Any]:
    """Construye el manifiesto del artefacto.

    **Es deterministico a proposito**: no lleva reloj, ni nombre de maquina, ni
    la ruta local de quien construye. Si los llevara, `A == B` seria imposible
    de demostrar. Esa metadata variable existe, pero vive fuera, en
    `construccion.json` y en el reporte de la tarea.
    """
    materializadas = sorted(entradas, key=lambda entrada: entrada.ruta)
    return {
        "version_del_manifiesto": 1,
        "artefacto": artefacto.name,
        "handler": NOMBRE_DEL_HANDLER,
        "plataforma": PLATAFORMA,
        "sha256": sha256_de(artefacto),
        "imagen": {
            "referencia": REFERENCIA_DEL_RUNTIME,
            "etiqueta": ETIQUETA_DEL_RUNTIME,
            "digest": DIGEST_DEL_RUNTIME,
            "digest_amd64": DIGEST_DEL_RUNTIME_AMD64,
            "plataforma": PLATAFORMA,
        },
        "entorno": dict(sorted(entorno.items())),
        "lock": {
            "sha256": sha256_de_texto(lock),
            "distribuciones": len(distribuciones),
        },
        "zip": {
            "marca_de_tiempo": list(MARCA_DE_TIEMPO),
            "permisos": oct(PERMISOS_NORMALIZADOS),
            "sistema_de_origen": SISTEMA_DE_ORIGEN_UNIX,
            "compresion": "deflate",
            "nivel": NIVEL_DE_COMPRESION,
            "entradas_de_directorio": False,
        },
        "medida": {
            "archivos": medida.archivos,
            "bytes_comprimidos": medida.bytes_comprimidos,
            "bytes_descomprimidos": medida.bytes_descomprimidos,
            "limite_comprimido": LIMITE_COMPRIMIDO,
            "limite_descomprimido": LIMITE_DESCOMPRIMIDO,
            "margen_comprimido": LIMITE_COMPRIMIDO - medida.bytes_comprimidos,
            "margen_descomprimido": LIMITE_DESCOMPRIMIDO - medida.bytes_descomprimidos,
            "por_distribucion": dict(sorted(medida.por_distribucion.items())),
        },
        "distribuciones": dict(sorted(distribuciones.items())),
        "archivos": [
            {
                "ruta": entrada.ruta,
                "bytes": entrada.origen.stat().st_size,
                "sha256": sha256_de(entrada.origen),
            }
            for entrada in materializadas
        ],
    }


# ---------------------------------------------------------------------------
# Instalacion de dependencias
# ---------------------------------------------------------------------------


def comando_de_instalacion(*, lock: str, destino: str) -> list[str]:
    """Comando `pip` de instalacion del artefacto.

    Los tres interruptores que lo hacen *fail-closed*:

    - `--require-hashes`: pip rechaza cualquier distribucion cuyo digest no
      coincida **y** exige que todo requisito venga fijado con `==` y con hash.
    - `--only-binary=:all:`: prohibe construir desde *sdist*. Si una dependencia
      no tuviera rueda compatible con el runtime destino, la construccion
      **falla** en vez de compilar algo distinto en silencio. Eso seria un
      hallazgo real, no un problema que se resuelva actualizando dependencias.
    - `--no-compile`: no se genera `.pyc`. El *bytecode* depende de rutas y
      marcas de tiempo, asi que arruinaria la reproducibilidad.
    """
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--no-input",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-compile",
        "--target",
        destino,
        "--requirement",
        lock,
    ]


# ---------------------------------------------------------------------------
# Construccion dentro del runtime de Lambda
# ---------------------------------------------------------------------------


def _entorno_de_construccion() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "pip": _version_de_pip(),
        "zlib": zlib.ZLIB_VERSION,
        "zlib_en_ejecucion": zlib.ZLIB_RUNTIME_VERSION,
        "libc": "-".join(platform.libc_ver()),
        "maquina": platform.machine(),
        "sistema": platform.system().lower(),
    }


def _version_de_pip() -> str:
    salida = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    return salida.stdout.split()[1]


def construir_en_linux(fuente: Path, salida: Path, trabajo: Path) -> dict[str, Any]:
    """Construye el artefacto. **Solo se ejecuta dentro del contenedor.**"""
    if platform.system().lower() != "linux" or platform.machine() != "x86_64":
        raise ErrorDeEmpaquetado(
            f"la construccion exige Linux x86_64 y esto es {platform.system()} {platform.machine()}"
        )

    if trabajo.exists():
        shutil.rmtree(trabajo)
    arbol = trabajo / "arbol"
    arbol.mkdir(parents=True)

    lock = fuente / "requirements.lock"
    texto_del_lock = lock.read_text(encoding="utf-8")
    distribuciones = distribuciones_del_lock(texto_del_lock)

    subprocess.run(  # noqa: S603 - argumentos fijos, sin shell y sin entrada externa
        comando_de_instalacion(lock=str(lock), destino=str(arbol)),
        check=True,
    )

    shutil.copytree(
        fuente / "app",
        arbol / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".env*"),
    )

    eliminados = normalizar_arbol(arbol)
    entradas = recolectar_entradas(arbol)
    rutas = [entrada.ruta for entrada in entradas]

    verificar_rutas(rutas)
    verificar_layout(rutas)
    verificar_contenido(rutas)
    verificar_binarios(entradas)
    verificar_inventario(esperadas=distribuciones, instaladas=distribuciones_instaladas(arbol))

    salida.mkdir(parents=True, exist_ok=True)
    artefacto = salida / NOMBRE_DEL_ARTEFACTO
    escribir_zip(entradas, artefacto)

    medida = medir(entradas, artefacto)
    verificar_tamano(medida)

    entorno = _entorno_de_construccion()
    manifiesto = construir_manifiesto(
        entradas=entradas,
        artefacto=artefacto,
        medida=medida,
        distribuciones=distribuciones,
        lock=texto_del_lock,
        entorno=entorno,
    )
    _escribir_json(salida / NOMBRE_DEL_MANIFIESTO, manifiesto)
    (salida / f"{NOMBRE_DEL_ARTEFACTO}.sha256").write_text(
        f"{manifiesto['sha256']}  {NOMBRE_DEL_ARTEFACTO}\n", encoding="utf-8", newline="\n"
    )
    _escribir_json(
        salida / NOMBRE_DE_LA_CONSTRUCCION,
        {
            "nota": "metadata VARIABLE del build; queda fuera del manifiesto y del ZIP",
            "eliminados_en_la_normalizacion": eliminados,
            "entorno": entorno,
            "trabajo": str(trabajo),
        },
    )
    return manifiesto


def _escribir_json(destino: Path, datos: Mapping[str, Any]) -> None:
    destino.write_text(
        json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


# ---------------------------------------------------------------------------
# Orquestacion de Docker desde el anfitrion
# ---------------------------------------------------------------------------


def raiz_del_repositorio() -> Path:
    """Raiz de `personal-blog-backend`, deducida de la ubicacion del modulo."""
    return Path(__file__).resolve().parent.parent


def _para_docker(ruta: Path) -> str:
    """Ruta del anfitrion tal como la acepta Docker, tambien en Windows."""
    return ruta.resolve().as_posix()


def _docker(
    argumentos: Sequence[str], *, capturar: bool = False
) -> subprocess.CompletedProcess[str]:
    """Ejecuta `docker`. Se invoca directamente, sin shell intermedia.

    Llamarlo sin shell evita de paso la conversion de rutas de MSYS: en Git Bash
    para Windows, `/var/lang/bin/python3` acabaria convertido en una ruta del
    anfitrion antes de llegar al demonio.
    """
    return subprocess.run(  # noqa: S603 - argumentos fijos, sin shell y sin entrada externa
        ["docker", *argumentos],  # noqa: S607 - `docker` se resuelve por PATH a proposito
        check=False,
        text=True,
        capture_output=capturar,
    )


def _base_de_docker(*, escritura: Sequence[tuple[Path, str]] = ()) -> list[str]:
    raiz = raiz_del_repositorio()
    argumentos = [
        "run",
        "--rm",
        "--platform",
        PLATAFORMA,
        "--entrypoint",
        "/var/lang/bin/python3",
        "--env",
        "LC_ALL=C",
        "--env",
        "LANG=C",
        "--env",
        "TZ=UTC",
        "--env",
        "PYTHONHASHSEED=0",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--volume",
        f"{_para_docker(raiz)}:{FUENTE_EN_EL_CONTENEDOR}:ro",
    ]
    for ruta, destino in escritura:
        argumentos += ["--volume", f"{_para_docker(ruta)}:{destino}"]
    return argumentos


def construir(destino: Path) -> int:
    """Construye el artefacto dentro del runtime oficial de Lambda."""
    destino = destino.resolve()
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)

    print(f"Construyendo en {REFERENCIA_DEL_RUNTIME} ({PLATAFORMA})")
    resultado = _docker(
        [
            *_base_de_docker(escritura=[(destino, SALIDA_EN_EL_CONTENEDOR)]),
            REFERENCIA_DEL_RUNTIME,
            f"{FUENTE_EN_EL_CONTENEDOR}/scripts/empaquetar_lambda.py",
            "construir-en-linux",
            "--fuente",
            FUENTE_EN_EL_CONTENEDOR,
            "--salida",
            SALIDA_EN_EL_CONTENEDOR,
            "--trabajo",
            TRABAJO_EN_EL_CONTENEDOR,
        ]
    )
    if resultado.returncode != 0:
        return resultado.returncode
    return resumir(destino)


def _leer_manifiesto(destino: Path) -> dict[str, Any]:
    datos: dict[str, Any] = json.loads((destino / NOMBRE_DEL_MANIFIESTO).read_text("utf-8"))
    return datos


def resumir(destino: Path) -> int:
    """Imprime el resumen legible de un artefacto ya construido."""
    manifiesto = _leer_manifiesto(destino)
    medida = manifiesto["medida"]
    print(f"  artefacto      {manifiesto['artefacto']}")
    print(f"  sha256         {manifiesto['sha256']}")
    print(f"  handler        {manifiesto['handler']}")
    print(f"  archivos       {medida['archivos']}")
    print(
        f"  comprimido     {medida['bytes_comprimidos']:>12} bytes "
        f"({medida['bytes_comprimidos'] / 1048576:.2f} MiB) "
        f"margen {medida['margen_comprimido']} bytes"
    )
    print(
        f"  descomprimido  {medida['bytes_descomprimidos']:>12} bytes "
        f"({medida['bytes_descomprimidos'] / 1048576:.2f} MiB) "
        f"margen {medida['margen_descomprimido']} bytes"
    )
    print(f"  distribuciones {len(manifiesto['distribuciones'])}")
    print("  mayores contribuciones (bytes descomprimidos):")
    mayores = sorted(medida["por_distribucion"].items(), key=lambda par: -par[1])[:12]
    for nombre, bytes_ in mayores:
        print(f"    {nombre:<24} {bytes_:>12}")
    return 0


# ---------------------------------------------------------------------------
# Verificacion desde el propio ZIP
# ---------------------------------------------------------------------------


def verificar(destino: Path) -> int:
    """Revalida un artefacto leyendo **solo el ZIP** y su `.sha256`.

    Es deliberadamente independiente del arbol de construccion: comprueba lo que
    se desplegaria, no lo que se quiso desplegar.
    """
    destino = destino.resolve()
    artefacto = destino / NOMBRE_DEL_ARTEFACTO
    manifiesto = _leer_manifiesto(destino)

    resumen = sha256_de(artefacto)
    declarado = (destino / f"{NOMBRE_DEL_ARTEFACTO}.sha256").read_text("utf-8").split()[0]
    if resumen != declarado:
        raise ErrorDeEmpaquetado(f"el .sha256 declara {declarado} y el ZIP vale {resumen}")
    if resumen != manifiesto["sha256"]:
        raise ErrorDeEmpaquetado("el manifiesto no coincide con el ZIP")

    with zipfile.ZipFile(artefacto) as archivo:
        if archivo.comment:
            raise ErrorDeEmpaquetado("el ZIP lleva comentario, que es metadata variable")
        corrupto = archivo.testzip()
        if corrupto is not None:
            raise ErrorDeEmpaquetado(f"entrada con CRC invalido: {corrupto}")

        informaciones = archivo.infolist()
        rutas = [informacion.filename for informacion in informaciones]
        verificar_rutas(rutas)
        verificar_layout(rutas)
        verificar_contenido(rutas)

        if rutas != sorted(rutas):
            raise ErrorDeEmpaquetado("las entradas del ZIP no van en orden lexicografico")
        for informacion in informaciones:
            if informacion.is_dir():
                raise ErrorDeEmpaquetado(f"entrada de directorio: {informacion.filename}")
            if informacion.date_time != MARCA_DE_TIEMPO:
                raise ErrorDeEmpaquetado(
                    f"marca de tiempo variable en {informacion.filename}: {informacion.date_time}"
                )
            if informacion.create_system != SISTEMA_DE_ORIGEN_UNIX:
                raise ErrorDeEmpaquetado(f"sistema de origen inesperado: {informacion.filename}")
            if stat.S_IMODE(informacion.external_attr >> 16) != PERMISOS_NORMALIZADOS:
                raise ErrorDeEmpaquetado(f"permisos sin normalizar: {informacion.filename}")

        verificar_cabeceras(
            (informacion.filename, archivo.read(informacion)[:64]) for informacion in informaciones
        )

        instaladas: dict[str, str] = {}
        for ruta in rutas:
            primero = ruta.split("/")[0]
            if primero.endswith(".dist-info"):
                nombre, _, version = primero[: -len(".dist-info")].rpartition("-")
                instaladas[normalizar_nombre(nombre)] = version
        esperadas = distribuciones_del_lock(
            (raiz_del_repositorio() / "requirements.lock").read_text("utf-8")
        )
        verificar_inventario(esperadas=esperadas, instaladas=instaladas)

        medida = Medida(
            archivos=len(informaciones),
            bytes_comprimidos=artefacto.stat().st_size,
            bytes_descomprimidos=sum(informacion.file_size for informacion in informaciones),
            por_distribucion=manifiesto["medida"]["por_distribucion"],
        )
        verificar_tamano(medida)

        if medida.bytes_descomprimidos != manifiesto["medida"]["bytes_descomprimidos"]:
            raise ErrorDeEmpaquetado("el tamano descomprimido no coincide con el manifiesto")
        if NOMBRE_DEL_MANIFIESTO in rutas or any(".sha256" in ruta for ruta in rutas):
            raise ErrorDeEmpaquetado("el manifiesto o el checksum viajan DENTRO del ZIP")

    print(f"Artefacto valido: {artefacto.name}")
    print(f"  sha256                 {resumen}")
    print(f"  entradas               {len(rutas)}")
    print(f"  distribuciones         {len(instaladas)} (las {len(esperadas)} del lock)")
    print(f"  comprimido             {medida.bytes_comprimidos} bytes")
    print(f"  descomprimido          {medida.bytes_descomprimidos} bytes")
    print("  layout, rutas, contenido, binarios, orden, fechas y permisos: correctos")
    return 0


def comparar(primero: Path, segundo: Path) -> int:
    """Demuestra la reproducibilidad comparando bytes, SHA-256 y manifiesto."""
    zip_a = (primero / NOMBRE_DEL_ARTEFACTO).resolve()
    zip_b = (segundo / NOMBRE_DEL_ARTEFACTO).resolve()
    sha_a, sha_b = sha256_de(zip_a), sha256_de(zip_b)
    iguales_en_bytes = zip_a.read_bytes() == zip_b.read_bytes()
    manifiesto_a = _leer_manifiesto(primero.resolve())
    manifiesto_b = _leer_manifiesto(segundo.resolve())

    print(f"  A  {zip_a}")
    print(f"     sha256 {sha_a}  {zip_a.stat().st_size} bytes")
    print(f"  B  {zip_b}")
    print(f"     sha256 {sha_b}  {zip_b.stat().st_size} bytes")
    print(f"  bytes identicos      {iguales_en_bytes}")
    print(f"  sha256 identico      {sha_a == sha_b}")
    print(f"  manifiesto identico  {manifiesto_a == manifiesto_b}")

    if not (iguales_en_bytes and sha_a == sha_b and manifiesto_a == manifiesto_b):
        raise ErrorDeEmpaquetado("las dos construcciones NO son identicas")
    print("Reproducibilidad demostrada: A == B byte a byte.")
    return 0


# ---------------------------------------------------------------------------
# Ejecucion aislada y controles negativos
# ---------------------------------------------------------------------------


def _invocar_el_harness(
    destino: Path,
    *,
    permeable: bool,
    retirar: str | None,
    pythonpath: str | None,
    capturar: bool,
) -> subprocess.CompletedProcess[str]:
    raiz = raiz_del_repositorio()
    harness = raiz / "scripts" / "arranque_aislado_lambda.py"
    argumentos = _base_de_docker()
    argumentos += [
        "--volume",
        f"{_para_docker(destino / NOMBRE_DEL_ARTEFACTO)}:/artefacto/{NOMBRE_DEL_ARTEFACTO}:ro",
        "--volume",
        f"{_para_docker(harness)}:/harness/arranque_aislado_lambda.py:ro",
    ]
    if pythonpath:
        argumentos += ["--env", f"PYTHONPATH={pythonpath}"]
    argumentos.append(REFERENCIA_DEL_RUNTIME)
    argumentos += ["-W", "error"] if permeable else ["-I", "-S", "-W", "error"]
    argumentos += [
        "/harness/arranque_aislado_lambda.py",
        "--artefacto",
        f"/artefacto/{NOMBRE_DEL_ARTEFACTO}",
        "--extraer",
        "/extraido",
    ]
    if retirar:
        argumentos += ["--retirar", retirar]
    if permeable:
        argumentos.append("--permeable")
    return _docker(argumentos, capturar=capturar)


def ejecutar_aislado(destino: Path) -> int:
    """Ejecuta el *handler* desde el ZIP en un proceso Linux aislado."""
    print(f"Ejecutando el handler desde {destino / NOMBRE_DEL_ARTEFACTO} (aislado, -I -S -W error)")
    return _invocar_el_harness(
        destino.resolve(), permeable=False, retirar=None, pythonpath=None, capturar=False
    ).returncode


#: Los tres vectores de fuga que el control negativo cierra. Cada uno retira una
#: dependencia **real** del artefacto dejando una copia accesible fuera: si el
#: *harness* la encontrara, estaria validando un artefacto incompleto.
CONTROLES_NEGATIVOS: Final = (
    ("mangum", "PYTHONPATH externo", "/externo"),
    ("boto3", "site-packages del propio runtime de Lambda", None),
    ("app", "arbol de fuentes accesible por PYTHONPATH", "/externo"),
)


def control_negativo(destino: Path) -> int:
    """Demuestra que el aislamiento del *harness* es real, no declarado.

    Para cada dependencia retirada se ejecuta **dos veces**:

    1. en modo **permeable**, que debe **funcionar** —la fuga existe de verdad,
       asi que el control no es un espantapajaros—;
    2. en modo **aislado**, que debe **fallar**.

    Si la ejecucion permeable fallara, el vector no estaria demostrado; si la
    aislada pasara, el *harness* estaria tomando prestada la dependencia y
    cualquier validacion anterior seria papel mojado.
    """
    destino = destino.resolve()
    fallos: list[str] = []
    for dependencia, vector, pythonpath in CONTROLES_NEGATIVOS:
        print(f"\n== control negativo: sin {dependencia!r} — vector: {vector} ==")

        permeable = _invocar_el_harness(
            destino, permeable=True, retirar=dependencia, pythonpath=pythonpath, capturar=True
        )
        aislado = _invocar_el_harness(
            destino, permeable=False, retirar=dependencia, pythonpath=pythonpath, capturar=True
        )

        print(f"  permeable  codigo {permeable.returncode} (se espera 0: la fuga es real)")
        print(f"  aislado    codigo {aislado.returncode} (se espera != 0: la fuga esta cerrada)")
        if aislado.returncode != 0:
            ultima = [linea for linea in aislado.stderr.strip().splitlines() if linea.strip()]
            print(f"  error aislado: {ultima[-1] if ultima else '(sin stderr)'}")

        if permeable.returncode != 0:
            fallos.append(
                f"{dependencia}: el modo permeable fallo, asi que el vector {vector!r} no "
                f"queda demostrado. stderr: {permeable.stderr.strip()[-400:]}"
            )
        if aislado.returncode == 0:
            fallos.append(
                f"{dependencia}: el modo aislado PASO sin la dependencia. El harness la esta "
                f"tomando de {vector!r} y no valida el artefacto"
            )

    if fallos:
        raise ErrorDeEmpaquetado("controles negativos no superados:\n  - " + "\n  - ".join(fallos))
    print("\nLos tres controles negativos se comportan como deben.")
    return 0


# ---------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------


def _analizador() -> argparse.ArgumentParser:
    analizador = argparse.ArgumentParser(
        prog="empaquetar_lambda",
        description="Construye y valida el artefacto ZIP de Lambda (Task/024).",
    )
    subcomandos = analizador.add_subparsers(dest="subcomando", required=True)

    construir_ = subcomandos.add_parser("construir", help="construye el artefacto")
    construir_.add_argument("--destino", required=True, type=Path)

    for nombre, ayuda in (
        ("verificar", "revalida un artefacto leyendo solo el ZIP"),
        ("resumir", "imprime el resumen de un artefacto"),
        ("ejecutar-aislado", "ejecuta el handler desde el ZIP, aislado"),
        ("control-negativo", "demuestra que el aislamiento es real"),
    ):
        parser = subcomandos.add_parser(nombre, help=ayuda)
        parser.add_argument("destino", type=Path)

    comparar_ = subcomandos.add_parser("comparar", help="demuestra que A == B")
    comparar_.add_argument("primero", type=Path)
    comparar_.add_argument("segundo", type=Path)

    interno = subcomandos.add_parser("construir-en-linux", help="uso interno: corre en Docker")
    interno.add_argument("--fuente", required=True, type=Path)
    interno.add_argument("--salida", required=True, type=Path)
    interno.add_argument("--trabajo", required=True, type=Path)
    return analizador


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de la herramienta."""
    argumentos = _analizador().parse_args(argv)
    try:
        if argumentos.subcomando == "construir":
            return construir(argumentos.destino)
        if argumentos.subcomando == "construir-en-linux":
            construir_en_linux(argumentos.fuente, argumentos.salida, argumentos.trabajo)
            return resumir(argumentos.salida)
        if argumentos.subcomando == "verificar":
            return verificar(argumentos.destino)
        if argumentos.subcomando == "resumir":
            return resumir(argumentos.destino.resolve())
        if argumentos.subcomando == "comparar":
            return comparar(argumentos.primero, argumentos.segundo)
        if argumentos.subcomando == "ejecutar-aislado":
            return ejecutar_aislado(argumentos.destino)
        if argumentos.subcomando == "control-negativo":
            return control_negativo(argumentos.destino)
    except ErrorDeEmpaquetado as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    raise AssertionError(f"subcomando no contemplado: {argumentos.subcomando!r}")


if __name__ == "__main__":
    raise SystemExit(main())
