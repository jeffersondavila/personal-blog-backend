"""Politica de `Origin` para peticiones administrativas (matriz C, D-011-K).

Es la **segunda capa** de la defensa CSRF. La primera es `SameSite=Lax`, que hace
que el navegador no envie la cookie en una peticion *cross-site* que cambie
estado. Esta capa no depende de que el navegador se comporte: comprueba en el
servidor de donde dice venir la peticion.
"""

from __future__ import annotations

import pytest

from app.shared.security import METODOS_QUE_CAMBIAN_ESTADO, origen_permitido

PERMITIDOS = ("https://example.com", "http://localhost:5173")


# --- Metodos que cambian estado --------------------------------------------
def test_los_metodos_que_cambian_estado_son_los_cuatro_esperados() -> None:
    """`GET`, `HEAD` y `OPTIONS` quedan fuera **a proposito**.

    Un CSRF que solo consiga provocar una lectura no consigue nada: la respuesta
    no es legible *cross-origin* sin que el servidor lo autorice con CORS.
    Incluir `OPTIONS` ademas romperia la peticion de comprobacion previa que el
    navegador envia **sin credenciales** antes de la real.
    """
    assert METODOS_QUE_CAMBIAN_ESTADO == frozenset({"POST", "PUT", "PATCH", "DELETE"})


@pytest.mark.parametrize("metodo", ["GET", "HEAD", "OPTIONS"])
def test_una_lectura_no_se_rechaza_aunque_el_origen_sea_ajeno(metodo: str) -> None:
    assert (
        origen_permitido(metodo=metodo, origen="https://evil.invalid", permitidos=PERMITIDOS)
        is True
    )


# --- C-07 ------------------------------------------------------------------
@pytest.mark.parametrize("metodo", sorted(METODOS_QUE_CAMBIAN_ESTADO))
def test_un_origen_ajeno_se_rechaza_en_los_metodos_que_escriben(metodo: str) -> None:
    assert (
        origen_permitido(metodo=metodo, origen="https://evil.invalid", permitidos=PERMITIDOS)
        is False
    )


def test_un_origen_parecido_pero_distinto_se_rechaza() -> None:
    """La comparacion es exacta, no por prefijo ni por sufijo.

    `https://example.com.evil.invalid` contiene el origen permitido como
    subcadena, y una comprobacion perezosa con `in` o `startswith` lo aceptaria.
    """
    for parecido in (
        "https://example.com.evil.invalid",
        "https://notexample.com",
        "http://example.com",
        "https://example.com:8443",
        "https://sub.example.com",
    ):
        assert origen_permitido(metodo="POST", origen=parecido, permitidos=PERMITIDOS) is False


# --- C-08 ------------------------------------------------------------------
@pytest.mark.parametrize("permitido", PERMITIDOS)
def test_un_origen_de_la_lista_se_acepta(permitido: str) -> None:
    assert origen_permitido(metodo="POST", origen=permitido, permitidos=PERMITIDOS) is True


# --- C-09 ------------------------------------------------------------------
def test_una_peticion_sin_origen_se_acepta() -> None:
    """No es una via de CSRF, y por eso no se rechaza.

    Un ataque de falsificacion **necesita** el navegador de la victima y su
    cookie ambiente, y todo navegador actual envia `Origin` en los metodos que
    cambian estado. Una peticion sin `Origin` viene de un cliente que no es una
    pagina —`curl`, un script, una sonda—, y ese cliente tendria que **poseer**
    la credencial para llegar a algo: si la tiene, el CSRF ya no es el problema.

    Rechazarla, en cambio, romperia toda automatizacion legitima sin cerrar
    ningun agujero.
    """
    assert origen_permitido(metodo="POST", origen=None, permitidos=PERMITIDOS) is True


# --- Lista vacia: fail-closed ----------------------------------------------
def test_sin_origenes_declarados_se_rechaza_cualquier_origen() -> None:
    """No existe un origen por defecto seguro, asi que no se supone ninguno.

    Consecuencia operativa, dicha sin adornos: hasta que
    `BLOG_ADMIN_ALLOWED_ORIGINS` se declare, ningun navegador puede iniciar ni
    cerrar sesion. Es deliberado — y `.env.example` lo explica.
    """
    assert origen_permitido(metodo="POST", origen="https://example.com", permitidos=()) is False


def test_sin_origenes_declarados_un_cliente_sin_origen_sigue_pasando() -> None:
    """Control del anterior: la lista vacia no bloquea a quien no es un navegador."""
    assert origen_permitido(metodo="POST", origen=None, permitidos=()) is True


# --- Normalizacion ---------------------------------------------------------
def test_el_metodo_se_compara_sin_distinguir_mayusculas() -> None:
    assert (
        origen_permitido(metodo="post", origen="https://evil.invalid", permitidos=PERMITIDOS)
        is False
    )


def test_el_origen_nulo_literal_se_rechaza() -> None:
    """Un `Origin: null` lo envian los contextos opacos —un `iframe` con
    `sandbox`, una pagina `data:`—. No es un origen de confianza y no esta en
    ninguna lista, asi que se rechaza como cualquier otro desconocido.
    """
    assert origen_permitido(metodo="POST", origen="null", permitidos=PERMITIDOS) is False
