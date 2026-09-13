"""Semilla del entorno local: crea el `Administrator` y el `Profile` iniciales.

Por que existe
--------------

El esquema garantiza **como maximo un** administrador y **como maximo un**
perfil, pero no puede garantizar "exactamente uno": una base recien migrada esta
vacia y sembrar esa fila exigiria versionar un correo real y un hash de
contrasena real, que es justo lo que el requisito **S-10** prohibe.

`data-model.md` seccion 5 asigna los dos propietarios por nombre:
**`Task/036-Publicar-Primer-Contenido`** para produccion y
**`Task/022-Validacion-Local-Production-Like`** —esta semilla— para el entorno
local. `Task/012` es dueno de **editar** el perfil por API; crearlo la primera
vez no se hace por API (decision **D-012-U**: `PUT /admin/profile` sobre una base
sin perfil responde `404` y no deja fila).

De donde salen los datos
------------------------

De **variables de entorno, sin ningun valor por defecto** (decision D-022-C). Un
valor por defecto para la contrasena seria una credencial conocida por cualquiera
que lea el repositorio. Falta una variable, la semilla falla y explica cual.

| Variable | Obligatoria | Destino |
| --- | --- | --- |
| `PERSONAL_BLOG_SEED_ADMIN_EMAIL` | si | `administrators.email` |
| `PERSONAL_BLOG_SEED_ADMIN_PASSWORD` | si | `administrators.password_hash`, via Argon2id |
| `PERSONAL_BLOG_SEED_ADMIN_DISPLAY_NAME` | si | `administrators.display_name` |
| `PERSONAL_BLOG_SEED_PROFILE_FULL_NAME` | si | `profiles.full_name` |
| `PERSONAL_BLOG_SEED_PROFILE_HEADLINE` | no | `profiles.headline` |

Que significa aqui "idempotente" (decision D-022-B)
----------------------------------------------------

Ejecutarla N veces deja el mismo estado observable que ejecutarla una vez:

1. **No duplica filas.** Con administrador y perfil ya presentes, no crea otros.
2. **No rota la credencial.** Si el administrador ya existe, su `password_hash`
   se deja intacto. Rehashear en cada ejecucion invalidaria la sesion abierta del
   panel sin que nadie lo pidiera.
3. **No pisa lo editado.** Un perfil ya modificado desde el panel conserva sus
   valores. El criterio 5 de STAGE-07 exige que los datos sobrevivan; una semilla
   que reescribe destruiria justo lo que se valida.

Lo que este modulo no hace
--------------------------

- **No confirma la transaccion.** `sembrar` y `ejecutar` reciben la sesion y solo
  hacen `flush`; confirmar es de `main`. Asi las pruebas trabajan dentro de la
  transaccion que la fixture revierte, y el comportamiento probado es el mismo
  que corre en produccion local.
- **No crea contenido de ejemplo** (decision D-022-D). Los articulos, reviews,
  videos, proyectos e imagenes de `Task/022` los crea el **recorrido
  administrativo real**, que es lo que los criterios 3 y 4 de STAGE-07 deben
  demostrar. Sembrarlos lo sustituiria por un atajo.
- **No registra la contrasena** en ninguna salida (requisito S-08).
- **No elige el algoritmo de hash.** Reutiliza la primitiva de `Task/011`, que es
  la misma que verifica el login. Cualquier otra cosa produciria un administrador
  incapaz de entrar al panel.

Con que identidad se ejecuta
----------------------------

Con el **plano de administracion**, el mismo de las migraciones — nunca con el
plano runtime del backend. No es una preferencia: desde `Task/018`, `blog_runtime`
tiene **solo `SELECT` y `UPDATE`** sobre `administrators` y **no puede crear
administradores** (requisito S-01, runbook seccion 2.2). Sembrar es provision,
no operacion de la aplicacion.

Por eso la semilla **no se ejecuta dentro del contenedor `backend`**: se ejecuta
desde el host, con el venv del backend y `BLOG_DATABASE_URL` apuntando a la
identidad administrativa, igual que `runtime_privileges.py`.

Uso
---

    python scripts/seed_local.py          # o: python -m scripts.seed_local

Las pruebas viven en `tests/integration/test_seed_local.py` y se ejecutan contra
PostgreSQL real: los cerrojos que esta semilla respeta son del motor. La
invocabilidad desde la linea de comandos la fija
`tests/test_seed_local_invocacion.py`.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

# Al invocar un archivo por su ruta, Python coloca en `sys.path` el directorio
# del **archivo** —`scripts/`— y no la raiz del repositorio, de modo que `app`
# no se resuelve. Con `python -m scripts.seed_local` no haria falta, pero el
# runbook documenta la forma directa y las dos deben funcionar.
# Regresion permanente: `tests/test_seed_local_invocacion.py`.
_RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DEL_REPOSITORIO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DEL_REPOSITORIO))

from sqlalchemy import select  # noqa: E402 - despues de ajustar `sys.path`
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.modules.authentication.infrastructure.models import (  # noqa: E402
    LONGITUD_DE_CORREO,
    LONGITUD_DE_NOMBRE_VISIBLE,
    Administrator,
)
from app.modules.authentication.presentation.schemas import (  # noqa: E402
    LONGITUD_MAXIMA_DE_CONTRASENA,
)
from app.modules.profile.infrastructure.models import (  # noqa: E402
    LONGITUD_DE_NOMBRE,
    LONGITUD_DE_TITULAR,
    Profile,
)
from app.shared.security import hash_de_contrasena  # noqa: E402

VARIABLE_CORREO: Final = "PERSONAL_BLOG_SEED_ADMIN_EMAIL"
VARIABLE_CONTRASENA: Final = "PERSONAL_BLOG_SEED_ADMIN_PASSWORD"
VARIABLE_NOMBRE_VISIBLE: Final = "PERSONAL_BLOG_SEED_ADMIN_DISPLAY_NAME"
VARIABLE_NOMBRE_COMPLETO: Final = "PERSONAL_BLOG_SEED_PROFILE_FULL_NAME"
VARIABLE_TITULAR: Final = "PERSONAL_BLOG_SEED_PROFILE_HEADLINE"

#: Minimo de la semilla (decision D-022-E). El login no impone minimo —no le
#: corresponde juzgar una credencial ya establecida—, pero **crear** una si:
#: es la unica oportunidad de no fabricar una credencial debil. El maximo se
#: reutiliza del contrato de acceso para que semilla y login no se separen.
LONGITUD_MINIMA_DE_CONTRASENA: Final = 12

CODIGO_DE_EXITO: Final = 0
CODIGO_DE_ERROR: Final = 1


class SemillaInvalidaError(Exception):
    """Precondicion incumplida. Su mensaje **nunca** incluye la contrasena."""


@dataclass(frozen=True)
class EntradaDeSemilla:
    """Datos validados con los que se siembra. La contrasena se hashea y se suelta."""

    correo: str
    contrasena: str
    nombre_visible: str
    nombre_completo: str
    titular: str | None


@dataclass(frozen=True)
class ResultadoDeSemilla:
    """Que se creo de verdad. Ambos `False` significa que ya estaba todo."""

    administrador_creado: bool
    perfil_creado: bool


def _obligatoria(entorno: Mapping[str, str], variable: str, maximo: int) -> str:
    valor = entorno.get(variable, "").strip()
    if not valor:
        raise SemillaInvalidaError(f"falta la variable obligatoria {variable}")
    if len(valor) > maximo:
        raise SemillaInvalidaError(f"{variable} excede el maximo de {maximo} caracteres")
    return valor


def _correo_bien_formado(valor: str) -> bool:
    """Comprobacion deliberadamente modesta.

    No pretende implementar la RFC 5322: valida que el valor pueda funcionar como
    identificador de acceso —una parte local, un dominio con punto y ningun
    espacio—. Quien escribe la semilla conoce su propio correo; lo que esta
    comprobacion evita es el error de tecleo que dejaria un administrador
    inaccesible.
    """
    if " " in valor or valor.count("@") != 1:
        return False
    local, _, dominio = valor.partition("@")
    if not local or not dominio:
        return False
    return "." in dominio and not dominio.startswith(".") and not dominio.endswith(".")


def leer_entrada(entorno: Mapping[str, str]) -> EntradaDeSemilla:
    """Lee y valida las variables. Lanza `SemillaInvalidaError` en cuanto algo no cuadra."""
    correo = _obligatoria(entorno, VARIABLE_CORREO, LONGITUD_DE_CORREO)
    if not _correo_bien_formado(correo):
        raise SemillaInvalidaError(f"{VARIABLE_CORREO} no tiene forma de correo electronico")

    contrasena = entorno.get(VARIABLE_CONTRASENA, "")
    if not contrasena:
        raise SemillaInvalidaError(f"falta la variable obligatoria {VARIABLE_CONTRASENA}")
    # El mensaje no repite el valor rechazado: seria filtrar la credencial (S-08).
    if len(contrasena) < LONGITUD_MINIMA_DE_CONTRASENA:
        raise SemillaInvalidaError(
            f"{VARIABLE_CONTRASENA} debe tener al menos {LONGITUD_MINIMA_DE_CONTRASENA} caracteres"
        )
    if len(contrasena) > LONGITUD_MAXIMA_DE_CONTRASENA:
        raise SemillaInvalidaError(
            f"{VARIABLE_CONTRASENA} excede el maximo de {LONGITUD_MAXIMA_DE_CONTRASENA} caracteres"
        )

    titular = entorno.get(VARIABLE_TITULAR, "").strip() or None
    if titular is not None and len(titular) > LONGITUD_DE_TITULAR:
        raise SemillaInvalidaError(f"{VARIABLE_TITULAR} excede el maximo de {LONGITUD_DE_TITULAR}")

    return EntradaDeSemilla(
        correo=correo,
        contrasena=contrasena,
        nombre_visible=_obligatoria(entorno, VARIABLE_NOMBRE_VISIBLE, LONGITUD_DE_NOMBRE_VISIBLE),
        nombre_completo=_obligatoria(entorno, VARIABLE_NOMBRE_COMPLETO, LONGITUD_DE_NOMBRE),
        titular=titular,
    )


def sembrar(sesion: Session, entrada: EntradaDeSemilla) -> ResultadoDeSemilla:
    """Deja exactamente un administrador y un perfil, sin tocar lo que ya exista.

    El administrador se resuelve **primero**: si el que hay es otro, se aborta
    antes de escribir el perfil, para no dejar la base a medias.
    """
    administrador = sesion.execute(select(Administrator)).scalars().first()
    if administrador is None:
        sesion.add(
            Administrator(
                email=entrada.correo,
                password_hash=hash_de_contrasena(entrada.contrasena),
                display_name=entrada.nombre_visible,
            )
        )
        administrador_creado = True
    elif administrador.email != entrada.correo:
        raise SemillaInvalidaError(
            "ya existe un administrador con otro correo. El esquema admite como "
            f"maximo uno, y {VARIABLE_CORREO} no coincide con el registrado. "
            "Cambia la variable o parte de una base limpia."
        )
    else:
        administrador_creado = False

    perfil = sesion.execute(select(Profile)).scalars().first()
    if perfil is None:
        sesion.add(Profile(full_name=entrada.nombre_completo, headline=entrada.titular))
        perfil_creado = True
    else:
        perfil_creado = False

    sesion.flush()
    return ResultadoDeSemilla(
        administrador_creado=administrador_creado, perfil_creado=perfil_creado
    )


def ejecutar(*, entorno: Mapping[str, str], sesion: Session, salida: TextIO, error: TextIO) -> int:
    """Lee el entorno, siembra y explica el resultado. Devuelve el codigo de salida.

    No confirma la transaccion: eso es de `main`. Tampoco revierte, para que el
    llamante decida — dentro de una prueba, la fixture ya lo hace.
    """
    try:
        entrada = leer_entrada(entorno)
        resultado = sembrar(sesion, entrada)
    except SemillaInvalidaError as fallo:
        print(f"ERROR: {fallo}", file=error)
        return CODIGO_DE_ERROR
    except SQLAlchemyError as fallo:
        print(
            f"ERROR: la base de datos rechazo la semilla ({type(fallo).__name__}). "
            "Comprueba que las migraciones estan aplicadas.",
            file=error,
        )
        return CODIGO_DE_ERROR

    print(
        "Administrador "
        + ("creado" if resultado.administrador_creado else "ya presente, sin cambios")
        + f": {entrada.correo}",
        file=salida,
    )
    print(
        "Perfil " + ("creado" if resultado.perfil_creado else "ya presente, sin cambios"),
        file=salida,
    )
    return CODIGO_DE_EXITO


def main() -> int:
    """Punto de entrada: abre la sesion real y confirma si todo fue bien."""
    # Import local: `main` es lo unico que necesita la conexion real, y las
    # pruebas no deben arrastrar la configuracion del proceso al importarlas.
    from app.shared.database.session import session_scope

    with session_scope() as sesion:
        codigo = ejecutar(entorno=os.environ, sesion=sesion, salida=sys.stdout, error=sys.stderr)
        if codigo != CODIGO_DE_EXITO:
            sesion.rollback()
        return codigo


if __name__ == "__main__":
    raise SystemExit(main())
