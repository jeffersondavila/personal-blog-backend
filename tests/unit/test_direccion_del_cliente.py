"""Resolucion de la direccion IP del cliente (`Task/011`, decision D-011-J).

Es la particion del limite de tasa y el dato que acompana a cada evento de
auditoria, asi que equivocarse aqui tiene dos consecuencias concretas: un
atacante podria falsificar una IP por intento —y anular el limite— y el historial
quedaria lleno de direcciones inventadas.
"""

from __future__ import annotations

import pytest

from app.shared.security import DIRECCION_DESCONOCIDA, direccion_del_cliente


def _resolver(
    par: str | None = "203.0.113.7",
    reenviada: str | None = None,
    saltos: int = 0,
) -> str:
    return direccion_del_cliente(
        direccion_del_par=par, cabecera_reenviada=reenviada, saltos_de_confianza=saltos
    )


# --- Sin proxies de confianza (valor por defecto) --------------------------
def test_sin_proxies_se_usa_la_direccion_del_par_tcp() -> None:
    assert _resolver() == "203.0.113.7"


def test_sin_proxies_la_cabecera_reenviada_se_ignora_por_completo() -> None:
    """Es la propiedad que impide evadir el limite de tasa.

    `X-Forwarded-For` la escribe cualquiera. Creersela sin un proxy de confianza
    delante permitiria enviar una direccion distinta en cada intento y disponer,
    en la practica, de infinitos cubos.
    """
    assert _resolver(reenviada="1.2.3.4") == "203.0.113.7"


def test_sin_proxies_una_cabecera_con_muchos_saltos_tampoco_influye() -> None:
    assert _resolver(reenviada="1.2.3.4, 5.6.7.8, 9.10.11.12") == "203.0.113.7"


# --- Con proxies de confianza ----------------------------------------------
def test_con_un_proxy_se_toma_el_ultimo_valor_de_la_cabecera() -> None:
    """El ultimo valor lo escribio el proxy de confianza; los anteriores, no.

    Se cuenta **desde la derecha** a proposito: la izquierda de la cadena es lo
    que el cliente pudo poner, y es justo lo que no debe decidir nada.
    """
    assert _resolver(reenviada="1.2.3.4, 198.51.100.9", saltos=1) == "198.51.100.9"


def test_con_dos_proxies_se_retrocede_dos_posiciones() -> None:
    cabecera = "1.2.3.4, 198.51.100.9, 203.0.113.200"

    assert _resolver(reenviada=cabecera, saltos=2) == "198.51.100.9"


def test_los_espacios_alrededor_de_cada_valor_no_cuentan() -> None:
    assert _resolver(reenviada="  1.2.3.4 ,  198.51.100.9  ", saltos=1) == "198.51.100.9"


def test_una_cabecera_mas_corta_que_los_saltos_declarados_no_se_adivina() -> None:
    """Si la cadena no tiene tantos saltos como se declararon, algo no encaja con
    el despliegue configurado. Tomar el valor que haya seria creerle al cliente
    exactamente en el caso en que no hay que hacerlo.
    """
    assert _resolver(reenviada="1.2.3.4", saltos=2) == DIRECCION_DESCONOCIDA


def test_sin_cabecera_pero_con_proxies_declarados_se_cae_a_desconocida() -> None:
    assert _resolver(reenviada=None, saltos=1) == DIRECCION_DESCONOCIDA


# --- Casos degenerados -----------------------------------------------------
def test_sin_direccion_de_par_la_particion_es_desconocida() -> None:
    """Ocurre con transportes que no exponen el par. Compartir un unico cubo es
    la respuesta *fail-closed*: limita de mas, nunca de menos.
    """
    assert _resolver(par=None) == DIRECCION_DESCONOCIDA


@pytest.mark.parametrize("basura", ["", "   ", "no-es-una-ip", "1.2.3.4.5", "999.1.1.1"])
def test_un_valor_que_no_es_una_direccion_se_descarta(basura: str) -> None:
    """La particion acaba en una columna `VARCHAR(45)`.

    Aceptar texto arbitrario convertiria una cabecera manipulada en un error de
    base de datos dentro del endpoint de acceso — y en una via para llenar la
    tabla de filas basura.
    """
    assert _resolver(reenviada=basura, saltos=1) == DIRECCION_DESCONOCIDA


def test_una_direccion_ipv6_se_conserva_entera() -> None:
    ipv6 = "2001:db8::8a2e:370:7334"

    assert _resolver(par=ipv6) == ipv6


def test_la_particion_nunca_excede_la_columna_que_la_guarda() -> None:
    """Control estructural: 45 caracteres cubren IPv6 y las formas IPv4 mapeadas."""
    from app.modules.authentication.infrastructure.models import LONGITUD_DE_PARTICION

    largo = "2001:0db8:85a3:0000:0000:8a2e:0370:7334" + "0" * 50

    assert len(_resolver(par=largo)) <= LONGITUD_DE_PARTICION
    assert len(DIRECCION_DESCONOCIDA) <= LONGITUD_DE_PARTICION
