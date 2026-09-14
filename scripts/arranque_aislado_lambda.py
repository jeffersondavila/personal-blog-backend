"""Arranque aislado del artefacto de Lambda (`Task/024`).

Ejecuta el *handler* **desde el ZIP extraido** dentro del runtime oficial de
Lambda, en un proceso que no puede resolver un solo `import` fuera del propio
artefacto. Es la prueba que convierte al ZIP en *validable* y no solo en
*medido*.

Por que no basta con lo facil
-----------------------------

`unzip -l` demuestra que hay archivos. `import mangum` desde el repositorio
demuestra que el `.venv` del desarrollador funciona. Ninguna de las dos cosa
dice nada del artefacto: un ZIP al que le falte `pydantic_core` pasaria ambas.
Por eso aqui el proceso se aisla de verdad y ademas se comprueba la
**procedencia** de cada modulo critico.

Como se consigue el aislamiento
-------------------------------

El proceso se lanza con `-I -S`:

- `-I` ignora `PYTHONPATH`, el *site* del usuario y el directorio del script
  como fuente implicita de paquetes.
- `-S` no importa `site`, de modo que **`site-packages` del runtime nunca entra
  en `sys.path`**. Eso importa: la imagen oficial trae su propio `boto3`, y sin
  `-S` un artefacto al que le faltara el suyo pareceria correcto.

Sobre esa base, este modulo deja `sys.path` con **el directorio extraido y la
biblioteca estandar, nada mas**, y verifica que cada modulo critico se haya
resuelto realmente desde alli.

El modo `--permeable` hace lo contrario a proposito: conserva `sys.path` tal
como venga y no exige procedencia. Existe **solo** para los controles negativos
(`scripts/empaquetar_lambda.py control-negativo`), que primero demuestran que la
fuga es real y despues que el aislamiento la cierra. Un control negativo que
nunca pudiera pasar no demostraria nada.

Que se ejercita
---------------

1. El ZIP es seguro y valido: sin rutas absolutas, sin `..` y sin CRC roto.
2. Se extrae en un directorio limpio.
3. El *handler* responde a un evento real de **API Gateway HTTP API v2**.
4. Los modulos criticos resuelven **desde el artefacto**.
5. Las **capacidades nativas** se ejercitan de verdad —Argon2 cifra y verifica,
   Pillow codifica y decodifica, el driver binario de PostgreSQL informa de su
   `libpq`—, y **toda extension compilada del artefacto carga**.

No hay red, no hay credenciales, no hay `.env` y no se contacta con AWS ni con
PostgreSQL: la configuracion es ficticia y `GET /health` es una sonda de
vivacidad que, por diseno, no consulta dependencias.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib
import io
import json
import os
import platform
import shutil
import sys
import sysconfig
import types
import zipfile
from pathlib import Path
from typing import Any

#: Modulos que deben resolverse desde el artefacto. Si alguno viniera de fuera,
#: el artefacto estaria incompleto y el despliegue fallaria en produccion.
MODULOS_CRITICOS = (
    "app.lambda_handler",
    "app.main",
    "mangum",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",
    "sqlalchemy",
    "alembic",
    "boto3",
    "botocore",
    "psycopg",
    "argon2",
    "PIL",
)

#: Configuracion ficticia minima. El backend valida al arrancar (requisito
#: T-01), asi que sin estas variables el modulo no llega a importarse.
#: `s3` evita exigir endpoint y credenciales de MinIO; ninguna apunta a nada
#: real y ninguna es un secreto.
ENTORNO_FICTICIO = {
    "BLOG_APP_ENV": "local",
    "BLOG_DATABASE_URL": "postgresql://usuario:ficticia@127.0.0.1:5432/personal_blog",
    "BLOG_PUBLIC_SITE_BASE_URL": "http://sitio.invalid",
    "BLOG_STORAGE_PROVIDER": "s3",
    "BLOG_STORAGE_BUCKET": "bucket-ficticio",
    "BLOG_STORAGE_REGION": "us-east-1",
}

#: Variables que jamas deben estar presentes: si lo estuvieran, la ejecucion
#: dejaria de ser offline y sin credenciales.
PREFIJOS_PROHIBIDOS_EN_EL_ENTORNO = ("AWS_", "PERSONAL_BLOG_")


class ErrorDeArranque(RuntimeError):  # noqa: N818
    """El artefacto no supera la validacion de ejecucion aislada."""


# ---------------------------------------------------------------------------
# Preparacion
# ---------------------------------------------------------------------------


def extraer(artefacto: Path, destino: Path) -> None:
    """Extrae el ZIP en un directorio limpio, rechazando rutas peligrosas."""
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)

    with zipfile.ZipFile(artefacto) as archivo:
        corrupto = archivo.testzip()
        if corrupto is not None:
            raise ErrorDeArranque(f"entrada con CRC invalido: {corrupto}")
        for nombre in archivo.namelist():
            if nombre.startswith("/") or ".." in nombre.split("/") or "\\" in nombre:
                raise ErrorDeArranque(f"entrada con ruta insegura: {nombre}")
        # Las rutas quedaron validadas justo arriba: ni absolutas ni con `..`.
        archivo.extractall(destino)


def retirar(extraido: Path, nombre: str, externo: Path) -> list[str]:
    """Mueve una dependencia fuera del artefacto, dejandola accesible fuera.

    Es la mitad util del control negativo: la dependencia desaparece del
    artefacto pero **sigue existiendo** en un directorio que un *harness*
    permeable alcanzaria. Devuelve lo que movio.
    """
    externo.mkdir(parents=True, exist_ok=True)
    movidos: list[str] = []
    for hijo in sorted(extraido.iterdir()):
        raiz_del_nombre = hijo.name.split("-")[0].replace("_", "-").lower()
        if hijo.name == nombre or raiz_del_nombre == nombre.replace("_", "-").lower():
            shutil.move(str(hijo), str(externo / hijo.name))
            movidos.append(hijo.name)
    if not movidos:
        raise ErrorDeArranque(f"no habia nada que retirar con el nombre {nombre!r}")
    return movidos


def _directorios_de_la_biblioteca_estandar() -> list[str]:
    rutas = {sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["platstdlib"]}
    return [ruta for ruta in sys.path if any(ruta.startswith(base) for base in rutas)]


def preparar_ruta_de_busqueda(extraido: Path, *, permeable: bool) -> None:
    """Deja `sys.path` con el artefacto y la biblioteca estandar."""
    if permeable:
        sys.path.insert(0, str(extraido))
        return
    sys.path[:] = [str(extraido), *_directorios_de_la_biblioteca_estandar()]


def preparar_entorno(extraido: Path) -> None:
    """Instala la configuracion ficticia y comprueba que no hay credenciales."""
    for variable in list(os.environ):
        if variable.startswith(("BLOG_", *PREFIJOS_PROHIBIDOS_EN_EL_ENTORNO)):
            del os.environ[variable]
    os.environ.update(ENTORNO_FICTICIO)

    if list(extraido.rglob(".env")):
        raise ErrorDeArranque("el artefacto contiene un .env")
    if (Path.cwd() / ".env").exists():
        raise ErrorDeArranque(f"hay un .env en el directorio de trabajo {Path.cwd()}")


# ---------------------------------------------------------------------------
# Ejecucion del handler
# ---------------------------------------------------------------------------


def evento_de_health() -> dict[str, Any]:
    """Evento de API Gateway HTTP API, *payload format* 2.0, `GET /health`."""
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/health",
        "rawQueryString": "",
        "headers": {"host": "api.blog.invalid", "user-agent": "arranque-aislado"},
        "requestContext": {
            "accountId": "000000000000",
            "apiId": "api-de-prueba",
            "domainName": "api.blog.invalid",
            "http": {
                "method": "GET",
                "path": "/health",
                "protocol": "HTTP/1.1",
                "sourceIp": "203.0.113.42",
                "userAgent": "arranque-aislado",
            },
            "requestId": "id-de-peticion-de-prueba",
            "routeKey": "$default",
            "stage": "$default",
            "time": "01/Jan/1980:00:00:00 +0000",
            "timeEpoch": 315_532_800_000,
        },
        "isBase64Encoded": False,
    }


class _ContextoLambda:
    """Contexto de invocacion minimo, con la forma que entrega el runtime."""

    function_name = "personal-blog-backend"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:personal-blog-backend"
    aws_request_id = "id-de-invocacion-de-prueba"


def invocar_el_handler() -> dict[str, Any]:
    """Importa el *handler* del artefacto y lo invoca con el evento real."""
    modulo = importlib.import_module("app.lambda_handler")
    respuesta = modulo.handler(evento_de_health(), _ContextoLambda())
    if not isinstance(respuesta, dict):
        raise ErrorDeArranque(f"el handler no devolvio un diccionario: {type(respuesta)!r}")
    return respuesta


def comprobar_la_respuesta(respuesta: dict[str, Any]) -> dict[str, Any]:
    """Comprueba codigo, codificacion, cuerpo y cabeceras de la respuesta."""
    if respuesta.get("statusCode") != 200:
        raise ErrorDeArranque(f"statusCode inesperado: {respuesta.get('statusCode')!r}")
    if respuesta.get("isBase64Encoded") is not False:
        raise ErrorDeArranque(f"isBase64Encoded inesperado: {respuesta.get('isBase64Encoded')!r}")

    cabeceras = {str(k).lower(): str(v) for k, v in (respuesta.get("headers") or {}).items()}
    if not cabeceras.get("content-type", "").startswith("application/json"):
        raise ErrorDeArranque(f"content-type inesperado: {cabeceras.get('content-type')!r}")
    if "content-length" not in cabeceras:
        raise ErrorDeArranque("la respuesta no declara content-length")

    cuerpo = json.loads(respuesta.get("body") or "")
    if cuerpo.get("status") != "ok":
        raise ErrorDeArranque(f"cuerpo inesperado: {cuerpo!r}")
    if not cuerpo.get("service") or not cuerpo.get("version"):
        raise ErrorDeArranque(f"el cuerpo no identifica el servicio: {cuerpo!r}")
    return {"cabeceras": cabeceras, "cuerpo": cuerpo}


def comprobar_procedencia(extraido: Path) -> dict[str, str]:
    """Exige que cada modulo critico se haya resuelto desde el artefacto."""
    raiz = str(extraido.resolve())
    procedencia: dict[str, str] = {}
    for nombre in MODULOS_CRITICOS:
        modulo: types.ModuleType = importlib.import_module(nombre)
        archivo = getattr(modulo, "__file__", None)
        if archivo is None:
            raise ErrorDeArranque(f"{nombre} no declara __file__")
        resuelto = str(Path(archivo).resolve())
        if not resuelto.startswith(raiz):
            raise ErrorDeArranque(f"{nombre} se resolvio FUERA del artefacto: {resuelto}")
        procedencia[nombre] = resuelto[len(raiz) + 1 :]
    return procedencia


# ---------------------------------------------------------------------------
# Capacidades nativas
# ---------------------------------------------------------------------------


def ejercitar_argon2() -> str:
    """Cifra y verifica: prueba `_argon2_cffi_bindings` y `libargon2`."""
    from argon2 import PasswordHasher

    hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    resumen = hasher.hash("clave-ficticia-de-validacion")
    if not hasher.verify(resumen, "clave-ficticia-de-validacion"):
        raise ErrorDeArranque("Argon2 no verifico su propio hash")
    return resumen.split("$")[1]


def ejercitar_pillow() -> dict[str, Any]:
    """Codifica y decodifica: prueba `_imaging` y las libs de `pillow.libs`."""
    from PIL import Image, features

    original = Image.new("RGB", (9, 7), (10, 20, 30))
    resultados: dict[str, Any] = {}
    for formato in ("PNG", "JPEG"):
        memoria = io.BytesIO()
        original.save(memoria, formato)
        memoria.seek(0)
        recuperada = Image.open(memoria)
        recuperada.load()
        if recuperada.size != (9, 7) or recuperada.mode != "RGB":
            raise ErrorDeArranque(f"{formato}: {recuperada.size} {recuperada.mode}")
        resultados[formato] = memoria.getbuffer().nbytes
    for codec in ("jpg", "zlib", "webp"):
        if not features.check(codec):
            raise ErrorDeArranque(f"Pillow sin soporte de {codec}")
    return resultados


def ejercitar_psycopg() -> dict[str, Any]:
    """Carga `libpq` **sin conectar**: no hay PostgreSQL ni credenciales."""
    import psycopg

    if psycopg.pq.__impl__ != "binary":
        raise ErrorDeArranque(f"psycopg no usa el driver binario: {psycopg.pq.__impl__}")
    return {"implementacion": psycopg.pq.__impl__, "libpq": psycopg.pq.version()}


def cargar_todas_las_extensiones(extraido: Path) -> dict[str, Any]:
    """Carga toda extension compilada del artefacto.

    Una extension puede no ser importable por una razon legitima ajena al
    binario: `PIL._imagingtk` necesita el `_tkinter` de la biblioteca estandar,
    que el runtime de Lambda no trae, y `greenlet.tests` necesita `psutil`, que
    no es dependencia de este proyecto. En esos casos **no se da por buena la
    mera existencia del archivo**: se exige que el enlazador dinamico la cargue
    con `ctypes.CDLL`, que es lo que demuestra que el binario sirve.

    Las bibliotecas de `*.libs/` no son modulos de Python: las carga su propia
    extension por `RPATH`, y quedan ejercitadas a traves de ella.
    """
    importlib.import_module("psycopg")  # `psycopg_binary` exige este orden.

    importadas: list[str] = []
    por_el_enlazador: dict[str, str] = {}
    for objeto in sorted(extraido.rglob("*.so")):
        relativa = objeto.relative_to(extraido)
        if any(parte.endswith(".libs") for parte in relativa.parts):
            continue
        nombre = ".".join([*relativa.parts[:-1], relativa.name.split(".")[0]])
        try:
            importlib.import_module(nombre)
        except ModuleNotFoundError as ausente:
            ctypes.CDLL(str(objeto))
            por_el_enlazador[nombre] = f"falta {ausente.name}, cargada por el enlazador"
        else:
            importadas.append(nombre)
    return {"importadas": importadas, "por_el_enlazador": por_el_enlazador}


# ---------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--artefacto", required=True, type=Path)
    analizador.add_argument("--extraer", required=True, type=Path)
    analizador.add_argument("--externo", default=Path("/externo"), type=Path)
    analizador.add_argument("--retirar", default=None)
    analizador.add_argument("--permeable", action="store_true")
    return analizador.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Valida el artefacto y describe por escrito lo que ha comprobado."""
    argumentos = _argumentos(argv)
    informe: dict[str, Any] = {
        "artefacto": str(argumentos.artefacto),
        "aislado": not argumentos.permeable,
        "python": sys.version.split()[0],
        "plataforma": f"{platform.system().lower()}/{platform.machine()}",
    }

    extraer(argumentos.artefacto, argumentos.extraer)
    if argumentos.retirar:
        informe["retirado"] = retirar(argumentos.extraer, argumentos.retirar, argumentos.externo)

    # El arbol extraido —y, en un control negativo, tambien `/externo`— se crean
    # DESPUES de arrancar el interprete. Si un directorio ya estaba en `sys.path`
    # al arrancar y todavia no existia, el buscador de imports guarda ese hecho en
    # cache y no vuelve a mirarlo aunque despues se llene. Sin esta invalidacion,
    # el modo permeable fallaria y el control negativo no demostraria nada.
    importlib.invalidate_caches()

    preparar_ruta_de_busqueda(argumentos.extraer, permeable=argumentos.permeable)
    os.chdir(argumentos.extraer if not argumentos.permeable else argumentos.externo)
    preparar_entorno(argumentos.extraer)
    informe["sys_path"] = list(sys.path)

    informe["respuesta"] = comprobar_la_respuesta(invocar_el_handler())
    if not argumentos.permeable:
        informe["procedencia"] = comprobar_procedencia(argumentos.extraer)
    informe["argon2"] = ejercitar_argon2()
    informe["pillow"] = ejercitar_pillow()
    informe["psycopg"] = ejercitar_psycopg()
    informe["extensiones"] = cargar_todas_las_extensiones(argumentos.extraer)

    print(json.dumps(informe, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
