"""Hash de contrasenas con Argon2id (matriz H de `Task/011`).

La contrasena en claro **no existe** en ningun almacenamiento del proyecto: lo
unico que se guarda es el resultado de `hash_de_contrasena`. Estas pruebas fijan
las propiedades de las que depende esa afirmacion.

Las contrasenas de este modulo son ficticias y locales a la prueba.
"""

from __future__ import annotations

import logging

import pytest

from app.shared.security import (
    PARAMETROS_DE_ARGON2,
    contrasena_valida,
    hash_de_contrasena,
    necesita_rehash,
    verificacion_senuelo,
)

CONTRASENA = "una-contrasena-de-prueba-larga"
OTRA = "otra-contrasena-de-prueba-distinta"


# --- H-01 ------------------------------------------------------------------
def test_el_hash_es_argon2id_y_no_contiene_la_contrasena() -> None:
    """Un hash reversible o que transporte la contrasena no protege nada."""
    resultado = hash_de_contrasena(CONTRASENA)

    assert resultado.startswith("$argon2id$")
    assert CONTRASENA not in resultado


def test_el_hash_cabe_en_la_columna_del_esquema() -> None:
    """`administrators.password_hash` es `VARCHAR(255)` desde `Task/008`.

    Si el algoritmo elegido produjera un hash mas largo, la primera escritura
    real fallaria en produccion y no aqui.
    """
    from app.modules.authentication.infrastructure.models import LONGITUD_DE_HASH

    assert len(hash_de_contrasena(CONTRASENA)) <= LONGITUD_DE_HASH


# --- H-02 ------------------------------------------------------------------
def test_la_contrasena_correcta_verifica() -> None:
    assert contrasena_valida(hash_de_contrasena(CONTRASENA), CONTRASENA) is True


# --- H-03 ------------------------------------------------------------------
def test_la_contrasena_incorrecta_no_verifica_y_no_lanza() -> None:
    """Devuelve `False`: una excepcion obligaria a cada llamante a capturarla."""
    assert contrasena_valida(hash_de_contrasena(CONTRASENA), OTRA) is False


def test_la_contrasena_vacia_no_verifica() -> None:
    assert contrasena_valida(hash_de_contrasena(CONTRASENA), "") is False


# --- H-04 ------------------------------------------------------------------
def test_dos_hashes_de_la_misma_contrasena_son_distintos() -> None:
    """Sal aleatoria por hash: sin ella, dos cuentas con la misma contrasena
    tendrian el mismo hash y una tabla precalculada las abriria a la vez.
    """
    primero = hash_de_contrasena(CONTRASENA)
    segundo = hash_de_contrasena(CONTRASENA)

    assert primero != segundo
    assert contrasena_valida(primero, CONTRASENA)
    assert contrasena_valida(segundo, CONTRASENA)


# --- H-05 ------------------------------------------------------------------
def test_un_hash_con_los_parametros_vigentes_no_necesita_rehash() -> None:
    assert necesita_rehash(hash_de_contrasena(CONTRASENA)) is False


def test_un_hash_con_parametros_debiles_necesita_rehash() -> None:
    """Control positivo de la comprobacion anterior.

    Sin este caso, una implementacion que devolviera siempre `False` pasaria la
    prueba de arriba sin comprobar nada.
    """
    from argon2 import PasswordHasher

    debil = PasswordHasher(
        time_cost=1,
        memory_cost=8,
        parallelism=1,
        hash_len=16,
        salt_len=8,
    ).hash(CONTRASENA)

    assert necesita_rehash(debil) is True


@pytest.mark.parametrize("hash_invalido", ["", "   ", "no-es-un-hash", "$argon2id$", "$2b$12$x"])
def test_un_hash_ilegible_no_se_marca_para_rehash(hash_invalido: str) -> None:
    """Un hash corrupto tampoco puede tumbar la comprobacion de rehash.

    Es el caso hermano de H-07, y faltaba: `contrasena_valida` ya tenia cubierta
    su rama de hash malformado y `necesita_rehash` no. Devolver `False` es lo
    correcto y no un atajo — no hay ninguna contrasena verificada con la que
    recalcular nada, y ese caso ya lo resuelve `contrasena_valida` rechazando las
    credenciales.
    """
    assert necesita_rehash(hash_invalido) is False


# --- H-06 ------------------------------------------------------------------
def test_la_contrasena_no_aparece_en_los_registros_del_modulo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Requisito S-08: ninguna contrasena llega al log, en ninguna rama."""
    with caplog.at_level(logging.DEBUG):
        hash_valido = hash_de_contrasena(CONTRASENA)
        contrasena_valida(hash_valido, CONTRASENA)
        contrasena_valida(hash_valido, OTRA)
        contrasena_valida("no-es-un-hash", CONTRASENA)
        necesita_rehash(hash_valido)
        verificacion_senuelo(CONTRASENA)

    registrado = "\n".join(registro.getMessage() for registro in caplog.records)
    assert CONTRASENA not in registrado
    assert OTRA not in registrado


def test_ningun_error_del_modulo_transporta_la_contrasena() -> None:
    """Un mensaje de error con la contrasena dentro acabaria en un log."""
    for entrada in ("", "no-es-un-hash", "$argon2id$roto"):
        try:
            resultado = contrasena_valida(entrada, CONTRASENA)
        except Exception as error:
            assert CONTRASENA not in str(error)
        else:
            assert resultado is False


# --- H-07 ------------------------------------------------------------------
@pytest.mark.parametrize("hash_invalido", ["", "   ", "no-es-un-hash", "$argon2id$", "$2b$12$x"])
def test_un_hash_malformado_devuelve_falso_en_lugar_de_estallar(hash_invalido: str) -> None:
    """Un hash corrupto en la base no debe convertirse en un `500`.

    Es la diferencia entre un inicio de sesion que falla y un servicio que se
    cae: el resultado correcto es "estas credenciales no valen".
    """
    assert contrasena_valida(hash_invalido, CONTRASENA) is False


# --- Parametros y senuelo --------------------------------------------------
def test_los_parametros_declarados_son_los_minimos_recomendados() -> None:
    """Los parametros son una decision de seguridad, no configuracion de entorno.

    Se fijan por prueba para que rebajarlos sea un cambio visible y discutido y
    no un ajuste silencioso (decision D-011-F).
    """
    assert PARAMETROS_DE_ARGON2 == {
        "time_cost": 2,
        "memory_cost": 19456,
        "parallelism": 1,
        "hash_len": 32,
        "salt_len": 16,
    }


def test_la_verificacion_senuelo_no_confirma_ninguna_contrasena() -> None:
    """Existe para gastar el mismo trabajo criptografico, no para autorizar.

    Se llama cuando el correo no existe (decision D-011-M). **No devuelve nada**,
    y eso es parte del contrato: si devolviera un booleano, alguien podria tomarlo
    por una verificacion valida y usarlo para decidir un acceso.

    Se comprueba sobre la firma y no sobre el valor: `assert f() is None` seria
    codigo que el analisis estatico rechaza —comparar el retorno de una funcion
    que no retorna— y ademas pasaria igual si algun dia devolviera algo por
    accidente en una sola rama.
    """
    import inspect

    firma = inspect.signature(verificacion_senuelo)

    assert firma.return_annotation in (None, "None")
    # Y se ejecuta, para comprobar que ninguna entrada la hace estallar.
    verificacion_senuelo(CONTRASENA)
    verificacion_senuelo("")
