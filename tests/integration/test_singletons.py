"""Estrategia *singleton* de `Profile` y `Administrator` (matriz F).

Lo que se comprueba aqui es exactamente lo que el **esquema** promete: **como
maximo una fila**. "Exactamente una" no puede garantizarlo una base recien
migrada, porque `Task/008` tiene prohibido sembrar datos reales; esa mitad
pertenece a **`Task/036-Publicar-Primer-Contenido`** en produccion y a
**`Task/022-Validacion-Local-Production-Like`** para los datos semilla locales:
los dos propietarios estan asignados en el ROADMAP.

La distincion se refleja en los nombres de estas pruebas: **ninguna afirma que el
perfil o el administrador existan**, solo que no puede haber dos.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.authentication.infrastructure.models import Administrator
from app.modules.profile.infrastructure.models import Profile, ProfileSocialLink

pytestmark = pytest.mark.integration

#: Relleno explicito: no es un hash real y no lo produce ningun algoritmo.
#: `Task/008` no elige el algoritmo de hashing ni crea administradores.
HASH_DE_RELLENO = "no-es-un-hash-real-task-008"


def _perfil(**campos: object) -> Profile:
    valores: dict[str, object] = {"full_name": "Nombre De Prueba"}
    valores.update(campos)
    return Profile(**valores)


def _administrador(correo: str = "persona@ejemplo.invalid") -> Administrator:
    return Administrator(
        email=correo,
        password_hash=HASH_DE_RELLENO,
        display_name="Administradora de prueba",
    )


# --- F-02 ------------------------------------------------------------------
def test_el_primer_perfil_se_acepta(sesion_de_pruebas: Session) -> None:
    sesion_de_pruebas.add(_perfil())

    sesion_de_pruebas.flush()  # no debe lanzar


# --- F-01 ------------------------------------------------------------------
def test_un_segundo_perfil_se_rechaza(sesion_de_pruebas: Session) -> None:
    sesion_de_pruebas.add(_perfil())
    sesion_de_pruebas.flush()

    sesion_de_pruebas.add(_perfil(full_name="Otra Persona"))

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- F-03 ------------------------------------------------------------------
def test_un_segundo_administrador_se_rechaza(sesion_de_pruebas: Session) -> None:
    sesion_de_pruebas.add(_administrador())
    sesion_de_pruebas.flush()

    sesion_de_pruebas.add(_administrador("otra@ejemplo.invalid"))

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- F-04 ------------------------------------------------------------------
def test_el_correo_del_administrador_es_unico(sesion_de_pruebas: Session) -> None:
    """Restriccion distinta de la del *singleton*: acota la **identidad**, no el conteo.

    Se comprueba saltandose el cerrojo para que el fallo sea inequivocamente el
    unico de `email` y no el del *singleton*.
    """
    sesion_de_pruebas.add(_administrador())
    sesion_de_pruebas.flush()

    duplicado = _administrador()
    sesion_de_pruebas.add(duplicado)

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


def test_un_administrador_nace_sin_intentos_fallidos_ni_bloqueo(
    sesion_de_pruebas: Session,
) -> None:
    """Los campos de proteccion contra fuerza bruta existen; usarlos es `Task/011`."""
    administrador = _administrador()
    sesion_de_pruebas.add(administrador)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.refresh(administrador)

    assert administrador.failed_login_attempts == 0
    assert administrador.locked_until is None
    assert administrador.last_login_at is None


# --- F-05 ------------------------------------------------------------------
def test_los_enlaces_sociales_se_devuelven_en_su_orden(sesion_de_pruebas: Session) -> None:
    perfil = _perfil()
    perfil.social_links = [
        ProfileSocialLink(label="LinkedIn", url="https://ejemplo.invalid/in", display_order=1),
        ProfileSocialLink(label="GitHub", url="https://ejemplo.invalid/gh", display_order=0),
    ]
    sesion_de_pruebas.add(perfil)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.expire(perfil)

    assert [enlace.label for enlace in perfil.social_links] == ["GitHub", "LinkedIn"]


# --- F-06 ------------------------------------------------------------------
def test_dos_enlaces_del_mismo_perfil_no_pueden_compartir_orden(
    sesion_de_pruebas: Session,
) -> None:
    perfil = _perfil()
    perfil.social_links = [
        ProfileSocialLink(label="GitHub", url="https://ejemplo.invalid/gh", display_order=0),
        ProfileSocialLink(label="LinkedIn", url="https://ejemplo.invalid/in", display_order=0),
    ]
    sesion_de_pruebas.add(perfil)

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- F-07 ------------------------------------------------------------------
def test_eliminar_el_perfil_arrastra_sus_enlaces(sesion_de_pruebas: Session) -> None:
    """Composicion real: un enlace social no existe fuera de su perfil.

    Es el unico borrado en cascada del modelo que arrastra **entidades**, y lo
    hace porque el enlace carece de sentido por si mismo. El resto de cascadas
    solo retira filas de asociacion.
    """
    perfil = _perfil()
    perfil.social_links = [
        ProfileSocialLink(label="GitHub", url="https://ejemplo.invalid/gh", display_order=0),
    ]
    sesion_de_pruebas.add(perfil)
    sesion_de_pruebas.flush()

    sesion_de_pruebas.delete(perfil)
    sesion_de_pruebas.flush()

    enlaces = sesion_de_pruebas.execute(select(ProfileSocialLink)).scalars().all()
    assert enlaces == []


def test_un_enlace_social_exige_etiqueta_y_url(sesion_de_pruebas: Session) -> None:
    perfil = _perfil()
    sesion_de_pruebas.add(perfil)
    sesion_de_pruebas.flush()

    sesion_de_pruebas.add(
        ProfileSocialLink(profile_id=perfil.id, label=None, url=None, display_order=0)
    )

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()
