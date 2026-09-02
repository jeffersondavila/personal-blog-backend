"""Configuracion que anade `Task/011` (matriz F).

Todo lo que aqui se comprueba es **fail-fast**: una configuracion insegura o mal
escrita debe impedir que el proceso arranque, no producir un fallo en la primera
peticion real (requisito T-01).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.shared.configuration import ConfigurationError, Settings


# --- F-01 ------------------------------------------------------------------
def test_la_configuracion_por_defecto_de_autenticacion_es_la_decidida(
    settings: Settings,
) -> None:
    """Los valores por defecto son la decision D-011-D, D-011-G y D-011-I.

    Se fijan por prueba para que cambiarlos sea visible: rebajar el umbral de
    bloqueo o alargar la sesion son decisiones de seguridad, no ajustes.
    """
    assert settings.auth_session_ttl_seconds == 43200
    assert settings.auth_cookie_secure is True
    assert settings.auth_max_failed_attempts == 5
    assert settings.auth_lockout_seconds == 900
    assert settings.auth_rate_limit_max_attempts == 10
    assert settings.auth_rate_limit_window_seconds == 300
    assert settings.trusted_proxy_hop_count == 0


def test_el_nombre_de_la_cookie_no_es_configuracion() -> None:
    """Es una constante, y la razon es que OpenAPI no puede mentir.

    FastAPI construye el esquema de seguridad al definir las rutas. Con un
    nombre configurable, un despliegue que lo cambiara publicaria una
    especificacion que declara una cookie distinta de la que el servidor
    usa. Nada pedia poder renombrarla, asi que la variable no existe.
    """
    from app.modules.authentication.presentation.cookies import NOMBRE_DE_LA_COOKIE

    assert NOMBRE_DE_LA_COOKIE == "blog_admin_session"
    assert not [nombre for nombre in Settings.model_fields if "cookie_name" in nombre]


def test_la_cookie_se_limita_al_prefijo_administrativo(settings: Settings) -> None:
    """La cookie no viaja a los endpoints publicos.

    Es higiene de exposicion, no una frontera de seguridad: `Path` lo aplica el
    navegador. Se deriva del prefijo configurado en lugar de escribirse a mano
    para que las dos cosas no puedan separarse.
    """
    assert settings.auth_cookie_path == "/api/v1/admin"


def test_la_lista_de_origenes_esta_vacia_por_defecto(settings: Settings) -> None:
    """No existe un origen por defecto seguro, asi que no se inventa ninguno."""
    assert settings.origenes_administrativos_permitidos == ()


@pytest.mark.parametrize(
    ("declarado", "esperado"),
    [
        ("https://example.com", ("https://example.com",)),
        (
            "https://example.com, http://localhost:5173",
            ("https://example.com", "http://localhost:5173"),
        ),
        ("  https://example.com  ", ("https://example.com",)),
        ("https://example.com,,", ("https://example.com",)),
    ],
)
def test_los_origenes_se_declaran_separados_por_comas(
    settings_factory: Any, declarado: str, esperado: tuple[str, ...]
) -> None:
    configuracion = settings_factory(admin_allowed_origins=declarado)

    assert configuracion.origenes_administrativos_permitidos == esperado


# --- F-02 ------------------------------------------------------------------
@pytest.mark.parametrize("comodin", ["*", "https://example.com,*", "  *  "])
def test_el_comodin_de_origen_impide_arrancar(settings_factory: Any, comodin: str) -> None:
    """Requisito S-04: nunca `*`, y menos con credenciales.

    Un `Access-Control-Allow-Origin: *` junto a una cookie de sesion es la
    combinacion que ningun navegador deberia tener que rechazar por nosotros.
    """
    with pytest.raises(ConfigurationError, match="BLOG_ADMIN_ALLOWED_ORIGINS"):
        settings_factory(admin_allowed_origins=comodin)


# --- F-03 ------------------------------------------------------------------
@pytest.mark.parametrize(
    "invalido",
    [
        "example.com",
        "https://example.com/panel",
        "https://example.com/",
        "ftp://example.com",
        "https://",
        "https://example.com?x=1",
    ],
)
def test_un_origen_malformado_impide_arrancar(settings_factory: Any, invalido: str) -> None:
    """Un origen es esquema + anfitrion + puerto. Ni ruta, ni consulta, ni barra.

    Comparar el `Origin` recibido con una cadena que no es un origen no falla
    ruidosamente: falla **rechazando siempre**, y eso se descubre cuando el panel
    ya no entra.
    """
    with pytest.raises(ConfigurationError, match="BLOG_ADMIN_ALLOWED_ORIGINS"):
        settings_factory(admin_allowed_origins=invalido)


def test_una_cookie_no_segura_en_produccion_impide_arrancar(settings_factory: Any) -> None:
    """No se debilita produccion para facilitar `localhost` (decision D-011).

    En produccion la cookie viaja por Internet: sin `Secure` puede acabar en una
    peticion en claro.
    """
    with pytest.raises(ConfigurationError, match="BLOG_AUTH_COOKIE_SECURE"):
        settings_factory(app_env="production", auth_cookie_secure=False, storage_provider="s3")


def test_una_cookie_no_segura_fuera_de_produccion_si_arranca(settings_factory: Any) -> None:
    """Control positivo: el entorno local usa HTTP y debe poder trabajar."""
    configuracion = settings_factory(app_env="local", auth_cookie_secure=False)

    assert configuracion.auth_cookie_secure is False


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("auth_session_ttl_seconds", 0),
        ("auth_max_failed_attempts", 0),
        ("auth_lockout_seconds", 0),
        ("auth_rate_limit_max_attempts", 0),
        ("auth_rate_limit_window_seconds", 0),
        ("trusted_proxy_hop_count", -1),
    ],
)
def test_un_limite_sin_sentido_impide_arrancar(
    settings_factory: Any, campo: str, valor: int
) -> None:
    """Un umbral de cero intentos bloquearia la cuenta antes del primer intento.

    Y una ventana de cero segundos convertiria el limite de tasa en un adorno.
    """
    with pytest.raises(ConfigurationError):
        settings_factory(**{campo: valor})


# --- F-04 ------------------------------------------------------------------
def test_la_configuracion_de_autenticacion_no_introduce_ningun_secreto(
    settings: Settings,
) -> None:
    """Decision D-011-Q: la arquitectura elegida **no tiene nada que firmar**.

    No hay `JWT_SECRET`, ni `AUTH_SECRET`, ni una clave "por si acaso". Un
    secreto sin uso no es prudencia: es superficie que alguien tendra que rotar,
    custodiar y explicar.
    """
    sospechosos = {
        nombre
        for nombre in type(settings).model_fields
        if nombre.startswith("auth_") and ("secret" in nombre or "key" in nombre)
    }

    assert sospechosos == set()


def test_la_representacion_de_la_configuracion_no_filtra_credenciales(
    settings: Settings,
) -> None:
    """Regresion de `Task/005`, ampliada: sigue sin haber nada que filtrar.

    La configuracion se registra al arrancar (requisito S-08), asi que su `repr`
    es texto que acaba en un log.
    """
    representacion = repr(settings)

    assert "clave_de_prueba" not in representacion
    assert "secreto_de_prueba" not in representacion
