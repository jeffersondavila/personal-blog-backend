"""Repositorios de autenticacion contra PostgreSQL real (matriz S de `Task/011`).

Estas pruebas ejercitan los adaptadores que implementan los puertos del dominio.
Van contra el motor de verdad y no contra un doble porque **lo que se comprueba
es precisamente lo que solo el motor hace**: la unicidad de la huella, el
`SELECT … FOR UPDATE` que serializa los intentos y la semantica de las fechas con
zona horaria.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.authentication.domain.sesion import (
    generar_credencial,
    huella_de_credencial,
)
from app.modules.authentication.infrastructure.models import AdministratorSession
from app.modules.authentication.infrastructure.repositorios import (
    RepositorioSqlDeAdministradores,
    RepositorioSqlDeSesiones,
)
from tests.integration.datos_de_autenticacion import CONTRASENA, CORREO, administrador

pytestmark = pytest.mark.integration

AHORA = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
UNA_HORA = timedelta(hours=1)


# --- Administradores -------------------------------------------------------
def test_se_encuentra_al_administrador_por_su_correo(sesion_de_pruebas: Session) -> None:
    fila = administrador(sesion_de_pruebas)

    estado = RepositorioSqlDeAdministradores(sesion_de_pruebas).bloquear_por_correo(CORREO)

    assert estado is not None
    assert estado.id == fila.id
    assert estado.email == CORREO
    assert estado.password_hash == fila.password_hash


def test_un_correo_inexistente_no_devuelve_nada(sesion_de_pruebas: Session) -> None:
    administrador(sesion_de_pruebas)

    repositorio = RepositorioSqlDeAdministradores(sesion_de_pruebas)

    assert repositorio.bloquear_por_correo("nadie@example.invalid") is None


def test_la_busqueda_por_correo_distingue_mayusculas_del_dominio_reservado(
    sesion_de_pruebas: Session,
) -> None:
    """El correo se normaliza a minusculas antes de consultar.

    Sin normalizar, `Admin@…` y `admin@…` serian cuentas distintas para el login
    y la misma para el `UNIQUE` de la base: dos verdades incompatibles.
    """
    administrador(sesion_de_pruebas)

    repositorio = RepositorioSqlDeAdministradores(sesion_de_pruebas)

    assert repositorio.bloquear_por_correo(CORREO.upper()) is not None


def test_el_fallo_registrado_persiste_el_contador_y_el_bloqueo(
    sesion_de_pruebas: Session,
) -> None:
    fila = administrador(sesion_de_pruebas)
    repositorio = RepositorioSqlDeAdministradores(sesion_de_pruebas)

    repositorio.registrar_intento_fallido(fila.id, fallos=3, bloqueado_hasta=AHORA + UNA_HORA)
    sesion_de_pruebas.expire_all()

    assert fila.failed_login_attempts == 3
    assert fila.locked_until == AHORA + UNA_HORA


def test_el_acceso_correcto_limpia_el_estado_defensivo(sesion_de_pruebas: Session) -> None:
    """Es la mitad que evita que un bloqueo sobreviva a un acceso legitimo."""
    fila = administrador(sesion_de_pruebas, intentos_fallidos=4, bloqueado_hasta=AHORA - UNA_HORA)
    repositorio = RepositorioSqlDeAdministradores(sesion_de_pruebas)

    repositorio.registrar_acceso_correcto(fila.id, instante=AHORA)
    sesion_de_pruebas.expire_all()

    assert fila.failed_login_attempts == 0
    assert fila.locked_until is None
    assert fila.last_login_at == AHORA


def test_el_acceso_correcto_puede_sustituir_un_hash_anticuado(
    sesion_de_pruebas: Session,
) -> None:
    """Rehash silencioso: el propietario no tiene que hacer nada."""
    fila = administrador(sesion_de_pruebas)
    anterior = fila.password_hash
    repositorio = RepositorioSqlDeAdministradores(sesion_de_pruebas)

    repositorio.registrar_acceso_correcto(fila.id, instante=AHORA, password_hash="$argon2id$nuevo")
    sesion_de_pruebas.expire_all()

    assert fila.password_hash == "$argon2id$nuevo"
    assert fila.password_hash != anterior


def test_sin_hash_nuevo_el_acceso_correcto_no_toca_la_contrasena(
    sesion_de_pruebas: Session,
) -> None:
    """Control negativo del caso anterior."""
    fila = administrador(sesion_de_pruebas)
    anterior = fila.password_hash

    RepositorioSqlDeAdministradores(sesion_de_pruebas).registrar_acceso_correcto(
        fila.id, instante=AHORA
    )
    sesion_de_pruebas.expire_all()

    assert fila.password_hash == anterior


# --- S-02: la credencial en claro no se guarda -----------------------------
def test_la_base_guarda_la_huella_y_nunca_la_credencial(sesion_de_pruebas: Session) -> None:
    """Es la propiedad de la que depende la decision D-011-C.

    Se busca la credencial en **todas** las columnas de texto de la fila, no solo
    en la que se espera: si alguien anadiera una columna de conveniencia con el
    valor en claro, esta prueba lo veria.
    """
    fila = administrador(sesion_de_pruebas)
    credencial = generar_credencial()

    RepositorioSqlDeSesiones(sesion_de_pruebas).crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(credencial),
        expira_en=AHORA + UNA_HORA,
    )

    sesion = sesion_de_pruebas.execute(select(AdministratorSession)).scalar_one()
    assert sesion.token_hash == huella_de_credencial(credencial)
    valores = " ".join(str(getattr(sesion, columna.name)) for columna in sesion.__table__.columns)
    assert credencial not in valores


# --- S-05, S-06 y S-07 -----------------------------------------------------
def test_una_sesion_vigente_resuelve_a_su_administrador(sesion_de_pruebas: Session) -> None:
    fila = administrador(sesion_de_pruebas)
    credencial = generar_credencial()
    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)
    repositorio.crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(credencial),
        expira_en=AHORA + UNA_HORA,
    )

    autenticado = repositorio.buscar_vigente(huella_de_credencial(credencial), ahora=AHORA)

    assert autenticado is not None
    assert autenticado.id == fila.id
    assert autenticado.email == CORREO


def test_una_credencial_desconocida_no_resuelve_a_nadie(sesion_de_pruebas: Session) -> None:
    administrador(sesion_de_pruebas)

    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)

    assert repositorio.buscar_vigente(huella_de_credencial("inventada"), ahora=AHORA) is None


def test_una_sesion_caducada_no_resuelve_a_nadie(sesion_de_pruebas: Session) -> None:
    fila = administrador(sesion_de_pruebas)
    credencial = generar_credencial()
    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)
    repositorio.crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(credencial),
        expira_en=AHORA - UNA_HORA,
    )

    assert repositorio.buscar_vigente(huella_de_credencial(credencial), ahora=AHORA) is None


def test_una_sesion_revocada_no_resuelve_a_nadie(sesion_de_pruebas: Session) -> None:
    fila = administrador(sesion_de_pruebas)
    credencial = generar_credencial()
    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)
    repositorio.crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(credencial),
        expira_en=AHORA + UNA_HORA,
    )
    repositorio.revocar(huella_de_credencial(credencial), instante=AHORA)

    assert repositorio.buscar_vigente(huella_de_credencial(credencial), ahora=AHORA) is None


def test_revocar_una_credencial_desconocida_no_afecta_a_nada(
    sesion_de_pruebas: Session,
) -> None:
    fila = administrador(sesion_de_pruebas)
    credencial = generar_credencial()
    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)
    repositorio.crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(credencial),
        expira_en=AHORA + UNA_HORA,
    )

    assert repositorio.revocar(huella_de_credencial("otra"), instante=AHORA) is False
    assert repositorio.buscar_vigente(huella_de_credencial(credencial), ahora=AHORA) is not None


def test_revocar_dos_veces_la_misma_sesion_no_es_un_error(sesion_de_pruebas: Session) -> None:
    """La segunda vez no encuentra nada vigente que revocar, y lo dice."""
    fila = administrador(sesion_de_pruebas)
    credencial = generar_credencial()
    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)
    repositorio.crear(
        administrador_id=fila.id,
        huella=huella_de_credencial(credencial),
        expira_en=AHORA + UNA_HORA,
    )

    assert repositorio.revocar(huella_de_credencial(credencial), instante=AHORA) is True
    assert repositorio.revocar(huella_de_credencial(credencial), instante=AHORA) is False


# --- S-08: sesiones simultaneas --------------------------------------------
def test_dos_sesiones_del_mismo_administrador_conviven(sesion_de_pruebas: Session) -> None:
    """Politica decidida en D-011-E: el propietario no se expulsa a si mismo.

    Revocar una **no** puede invalidar la otra: seria "cerrar todas las
    sesiones", que ninguna fuente canonica pide.
    """
    fila = administrador(sesion_de_pruebas)
    primera, segunda = generar_credencial(), generar_credencial()
    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)
    for credencial in (primera, segunda):
        repositorio.crear(
            administrador_id=fila.id,
            huella=huella_de_credencial(credencial),
            expira_en=AHORA + UNA_HORA,
        )

    repositorio.revocar(huella_de_credencial(primera), instante=AHORA)

    assert repositorio.buscar_vigente(huella_de_credencial(primera), ahora=AHORA) is None
    assert repositorio.buscar_vigente(huella_de_credencial(segunda), ahora=AHORA) is not None


def test_dos_sesiones_no_pueden_compartir_huella(sesion_de_pruebas: Session) -> None:
    """La unicidad la garantiza la base, no la aplicacion."""
    from sqlalchemy.exc import IntegrityError

    fila = administrador(sesion_de_pruebas)
    huella = huella_de_credencial(generar_credencial())
    repositorio = RepositorioSqlDeSesiones(sesion_de_pruebas)
    repositorio.crear(administrador_id=fila.id, huella=huella, expira_en=AHORA + UNA_HORA)

    with pytest.raises(IntegrityError):
        repositorio.crear(administrador_id=fila.id, huella=huella, expira_en=AHORA + UNA_HORA)


def test_una_sesion_de_un_administrador_inexistente_se_rechaza(
    sesion_de_pruebas: Session,
) -> None:
    """La clave foranea impide crear una credencial que no autoriza a nadie."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        RepositorioSqlDeSesiones(sesion_de_pruebas).crear(
            administrador_id=uuid.uuid4(),
            huella=huella_de_credencial(generar_credencial()),
            expira_en=AHORA + UNA_HORA,
        )


def test_la_contrasena_de_prueba_verifica_contra_el_hash_almacenado(
    sesion_de_pruebas: Session,
) -> None:
    """Control positivo del constructor de datos.

    Sin el, una prueba de "credenciales correctas" podria estar fallando porque
    el andamiaje guarda mal el hash, y se leeria como un defecto del login.
    """
    from app.shared.security import contrasena_valida

    fila = administrador(sesion_de_pruebas)

    assert contrasena_valida(fila.password_hash, CONTRASENA) is True
