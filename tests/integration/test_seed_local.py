"""Semilla del entorno local (`Task/022`, matriz C1-C12).

Que se prueba aqui
------------------

La carga de datos semilla que `data-model.md` seccion 5 asigna por nombre a
**`Task/022-Validacion-Local-Production-Like`**: crear el `Administrator` y el
`Profile` que el esquema promete "como maximo uno" pero que una base recien
migrada no tiene. `Task/012` es dueno de **editar** el perfil por API; crearlo la
primera vez no se hace por API (decision **D-012-U**) y por eso existe esta
semilla.

Por que PostgreSQL real y nunca SQLite (B-6)
---------------------------------------------

Todo lo que estas pruebas afirman descansa en garantias del motor: los cerrojos
`UNIQUE (is_singleton)` con `CHECK (is_singleton IS TRUE)` de `administrators` y
`profiles`, y el unico sobre `email`. Un sustituto en memoria no los tiene, asi
que verde en SQLite no diria nada sobre el comportamiento real.

Todo lo que se escribe aqui es ficticio
---------------------------------------

Correos de dominios reservados para ejemplos (RFC 2606) y contrasenas de prueba,
igual que en `datos_de_autenticacion.py`. **Ningun valor real se versiona**
(requisito S-10), y C12 comprueba que la contrasena no se filtra por ninguna
salida (requisito S-08).
"""

from __future__ import annotations

import io
from collections.abc import Mapping

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modules.authentication.infrastructure.models import Administrator
from app.modules.profile.infrastructure.models import Profile
from app.shared.security import contrasena_valida, necesita_rehash
from scripts.seed_local import (
    CODIGO_DE_ERROR,
    CODIGO_DE_EXITO,
    VARIABLE_CONTRASENA,
    VARIABLE_CORREO,
    VARIABLE_NOMBRE_COMPLETO,
    VARIABLE_NOMBRE_VISIBLE,
    VARIABLE_TITULAR,
    ejecutar,
)

pytestmark = pytest.mark.integration

#: Dominio reservado por la RFC 2606. No es direccionable y no pertenece a nadie.
CORREO = "propietaria@example.invalid"
CONTRASENA = "semilla-local-de-prueba-suficientemente-larga"
NOMBRE_VISIBLE = "Propietaria del blog"
NOMBRE_COMPLETO = "Nombre Completo De Prueba"
TITULAR = "Titular de prueba"


def _entorno(**cambios: str | None) -> dict[str, str]:
    """Entorno valido, con las claves que se pidan sobrescritas o suprimidas."""
    base: dict[str, str] = {
        VARIABLE_CORREO: CORREO,
        VARIABLE_CONTRASENA: CONTRASENA,
        VARIABLE_NOMBRE_VISIBLE: NOMBRE_VISIBLE,
        VARIABLE_NOMBRE_COMPLETO: NOMBRE_COMPLETO,
        VARIABLE_TITULAR: TITULAR,
    }
    for clave, valor in cambios.items():
        if valor is None:
            base.pop(clave, None)
        else:
            base[clave] = valor
    return base


def _correr(sesion: Session, entorno: Mapping[str, str]) -> tuple[int, str, str]:
    """Ejecuta la semilla capturando ambas salidas."""
    salida, error = io.StringIO(), io.StringIO()
    codigo = ejecutar(entorno=entorno, sesion=sesion, salida=salida, error=error)
    return codigo, salida.getvalue(), error.getvalue()


def _cuantos(sesion: Session, modelo: type[Administrator] | type[Profile]) -> int:
    return sesion.execute(select(func.count()).select_from(modelo)).scalar_one()


# --- C1 ---------------------------------------------------------------------


def test_siembra_administrador_y_perfil_en_base_vacia(sesion_de_pruebas: Session) -> None:
    """Sobre una base migrada y vacia deja exactamente un administrador y un perfil."""
    codigo, _, error = _correr(sesion_de_pruebas, _entorno())

    assert codigo == CODIGO_DE_EXITO, error
    assert _cuantos(sesion_de_pruebas, Administrator) == 1
    assert _cuantos(sesion_de_pruebas, Profile) == 1

    administrador = sesion_de_pruebas.execute(select(Administrator)).scalar_one()
    assert administrador.email == CORREO
    assert administrador.display_name == NOMBRE_VISIBLE

    perfil = sesion_de_pruebas.execute(select(Profile)).scalar_one()
    assert perfil.full_name == NOMBRE_COMPLETO
    assert perfil.headline == TITULAR


# --- C2 ---------------------------------------------------------------------


def test_el_hash_sembrado_verifica_con_la_primitiva_del_login(
    sesion_de_pruebas: Session,
) -> None:
    """El hash es Argon2id vigente: lo acepta la misma primitiva que usa `Task/011`.

    Es la prueba que impide que la semilla y el login se separen. Si la semilla
    escribiera un hash con otro algoritmo u otros parametros, el administrador
    sembrado no podria entrar al panel y el recorrido de `Task/022` no
    arrancaria.
    """
    _correr(sesion_de_pruebas, _entorno())

    administrador = sesion_de_pruebas.execute(select(Administrator)).scalar_one()

    assert administrador.password_hash != CONTRASENA
    assert administrador.password_hash.startswith("$argon2id$")
    assert contrasena_valida(administrador.password_hash, CONTRASENA) is True
    assert contrasena_valida(administrador.password_hash, "otra-cosa-distinta") is False
    assert necesita_rehash(administrador.password_hash) is False


# --- C3 ---------------------------------------------------------------------


def test_segunda_ejecucion_no_duplica_filas(sesion_de_pruebas: Session) -> None:
    """Idempotencia: ejecutarla dos veces deja el mismo estado que ejecutarla una."""
    primero, _, _ = _correr(sesion_de_pruebas, _entorno())
    segundo, _, error = _correr(sesion_de_pruebas, _entorno())

    assert primero == CODIGO_DE_EXITO
    assert segundo == CODIGO_DE_EXITO, error
    assert _cuantos(sesion_de_pruebas, Administrator) == 1
    assert _cuantos(sesion_de_pruebas, Profile) == 1


# --- C4 ---------------------------------------------------------------------


def test_segunda_ejecucion_conserva_el_hash(sesion_de_pruebas: Session) -> None:
    """No rota la credencial ya establecida.

    Argon2id genera una sal nueva en cada llamada, asi que un hash distinto
    demuestra que se volvio a hashear. Rotar la contrasena en cada ejecucion
    invalidaria la sesion del panel sin que nadie lo pidiera.
    """
    _correr(sesion_de_pruebas, _entorno())
    hash_inicial = sesion_de_pruebas.execute(select(Administrator)).scalar_one().password_hash

    _correr(sesion_de_pruebas, _entorno())
    hash_final = sesion_de_pruebas.execute(select(Administrator)).scalar_one().password_hash

    assert hash_final == hash_inicial


# --- C5 ---------------------------------------------------------------------


def test_no_sobrescribe_campos_editados(sesion_de_pruebas: Session) -> None:
    """Lo editado despues por el panel sobrevive a una nueva ejecucion.

    El criterio 5 de STAGE-07 exige que los datos sobrevivan; una semilla que
    reescribe el perfil en cada arranque destruiria justo lo que se valida.
    """
    _correr(sesion_de_pruebas, _entorno())

    perfil = sesion_de_pruebas.execute(select(Profile)).scalar_one()
    perfil.full_name = "Nombre Editado Desde El Panel"
    perfil.headline = "Titular editado desde el panel"
    sesion_de_pruebas.flush()

    codigo, _, error = _correr(sesion_de_pruebas, _entorno())

    assert codigo == CODIGO_DE_EXITO, error
    perfil_final = sesion_de_pruebas.execute(select(Profile)).scalar_one()
    assert perfil_final.full_name == "Nombre Editado Desde El Panel"
    assert perfil_final.headline == "Titular editado desde el panel"


# --- C6 y C7 ----------------------------------------------------------------


@pytest.mark.parametrize(
    "variable_ausente",
    [VARIABLE_CONTRASENA, VARIABLE_CORREO, VARIABLE_NOMBRE_VISIBLE, VARIABLE_NOMBRE_COMPLETO],
)
def test_falla_sin_una_variable_obligatoria(
    sesion_de_pruebas: Session, variable_ausente: str
) -> None:
    """Sin una variable obligatoria falla y no deja estado parcial.

    No hay valores por defecto a proposito (decision D-022-C): un valor por
    defecto para la contrasena seria una credencial conocida.
    """
    entorno = _entorno(**{variable_ausente: None})

    codigo, _, error = _correr(sesion_de_pruebas, entorno)

    assert codigo == CODIGO_DE_ERROR
    assert variable_ausente in error
    assert _cuantos(sesion_de_pruebas, Administrator) == 0
    assert _cuantos(sesion_de_pruebas, Profile) == 0


# --- C8 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "correo_invalido",
    [
        "no-es-un-correo",
        "sin@dominio@doble.invalid",
        "@sin-parte-local.invalid",
        "espacio @x.invalid",
    ],
)
def test_rechaza_correo_malformado(sesion_de_pruebas: Session, correo_invalido: str) -> None:
    """Un correo que no puede ser identificador de acceso se rechaza antes de escribir."""
    codigo, _, error = _correr(sesion_de_pruebas, _entorno(**{VARIABLE_CORREO: correo_invalido}))

    assert codigo == CODIGO_DE_ERROR
    assert VARIABLE_CORREO in error
    assert _cuantos(sesion_de_pruebas, Administrator) == 0
    assert _cuantos(sesion_de_pruebas, Profile) == 0


# --- C9 ---------------------------------------------------------------------


def test_rechaza_contrasena_corta(sesion_de_pruebas: Session) -> None:
    """Una contrasena por debajo del minimo se rechaza y no deja estado parcial."""
    codigo, _, error = _correr(sesion_de_pruebas, _entorno(**{VARIABLE_CONTRASENA: "corta"}))

    assert codigo == CODIGO_DE_ERROR
    assert VARIABLE_CONTRASENA in error
    assert "corta" not in error, "el mensaje no debe repetir la contrasena rechazada"
    assert _cuantos(sesion_de_pruebas, Administrator) == 0
    assert _cuantos(sesion_de_pruebas, Profile) == 0


# --- C10 --------------------------------------------------------------------


def test_no_crea_segundo_administrador(sesion_de_pruebas: Session) -> None:
    """Con un administrador de otro correo, aborta sin tocar nada.

    El cerrojo `administrador_unico` rechazaria la segunda fila de todos modos;
    lo que se comprueba aqui es que la semilla lo detecta y lo explica en lugar
    de estrellarse contra la restriccion, y que no crea el perfil a medias.
    """
    _correr(sesion_de_pruebas, _entorno())

    codigo, _, error = _correr(
        sesion_de_pruebas, _entorno(**{VARIABLE_CORREO: "otra.persona@example.invalid"})
    )

    assert codigo == CODIGO_DE_ERROR
    assert _cuantos(sesion_de_pruebas, Administrator) == 1
    administrador = sesion_de_pruebas.execute(select(Administrator)).scalar_one()
    assert administrador.email == CORREO
    assert error.strip() != ""


# --- C11 --------------------------------------------------------------------


def test_falla_sobre_base_sin_migrar(sesion_de_pruebas: Session) -> None:
    """Sin esquema, falla de forma explicita y no crea tablas.

    Se simula con un `search_path` que apunta a un esquema vacio: las tablas
    dejan de resolverse sin tocar el esquema real, y la transaccion de la fixture
    revierte tambien el esquema temporal.
    """
    sesion_de_pruebas.execute(text("CREATE SCHEMA esquema_sin_migrar"))
    sesion_de_pruebas.execute(text("SET LOCAL search_path TO esquema_sin_migrar"))

    codigo, _, error = _correr(sesion_de_pruebas, _entorno())

    assert codigo == CODIGO_DE_ERROR
    assert error.strip() != ""

    sesion_de_pruebas.rollback()
    tablas = sesion_de_pruebas.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'esquema_sin_migrar'"
        )
    ).scalar_one()
    assert tablas == 0


# --- C12 --------------------------------------------------------------------


def test_no_emite_la_contrasena(sesion_de_pruebas: Session) -> None:
    """Ni la salida estandar ni la de error contienen la contrasena (S-08).

    Prueba de senuelo: se siembra un valor reconocible y se busca literalmente.
    """
    senuelo = "SENUELO-de-contrasena-que-no-debe-aparecer-jamas"

    codigo, salida, error = _correr(sesion_de_pruebas, _entorno(**{VARIABLE_CONTRASENA: senuelo}))

    assert codigo == CODIGO_DE_EXITO, error
    assert senuelo not in salida
    assert senuelo not in error
