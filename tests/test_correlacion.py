"""Pruebas del contrato del correlation ID (`Task/017`, requisito O-02).

El contrato completo esta en la ficha `TASK-017` seccion 9. Lo que aqui se fija:

- **Cabecera `X-Request-ID`**, el unico nombre que el proyecto ya usa en el
  cuerpo de error, en `audit_events` y en el frontend.
- **8 a 64 caracteres**, del alfabeto `A-Za-z0-9-_`. El limite superior **no es
  una eleccion**: `audit_events.request_id` es `VARCHAR(64)`, y un valor mas
  largo fallaria al escribir la auditoria de una operacion ya ejecutada.
- **Cero, una o varias cabeceras** se resuelven con una politica *fail-safe*
  que no depende de la resolucion *first-wins* o *last-wins* de ningun
  componente de la cadena.
"""

from __future__ import annotations

import uuid

import pytest

from app.shared.logging.contexto import (
    LONGITUD_MAXIMA_DEL_REQUEST_ID,
    LONGITUD_MINIMA_DEL_REQUEST_ID,
    NOMBRE_DE_LA_CABECERA_DE_CORRELACION,
    es_request_id_valido,
    generar_request_id,
    resolver_request_id,
)


def test_la_cabecera_del_proyecto_es_x_request_id() -> None:
    assert NOMBRE_DE_LA_CABECERA_DE_CORRELACION == "X-Request-ID"


def test_el_identificador_generado_es_un_uuid4_canonico() -> None:
    generado = generar_request_id()

    assert uuid.UUID(generado).version == 4
    assert generado == str(uuid.UUID(generado))


def test_dos_identificadores_generados_no_coinciden() -> None:
    assert generar_request_id() != generar_request_id()


def test_el_identificador_generado_supera_su_propia_validacion() -> None:
    assert es_request_id_valido(generar_request_id())


# --- Validacion del valor entrante ---------------------------------------


@pytest.mark.parametrize(
    "valor",
    [
        "a" * LONGITUD_MINIMA_DEL_REQUEST_ID,
        "a" * LONGITUD_MAXIMA_DEL_REQUEST_ID,
        "trace-0001_ABC",
        "0123456789abcdef",
    ],
)
def test_se_acepta_un_valor_del_alfabeto_y_de_longitud_permitida(valor: str) -> None:
    assert es_request_id_valido(valor)


@pytest.mark.parametrize(
    ("valor", "motivo"),
    [
        ("", "vacio"),
        ("a" * (LONGITUD_MINIMA_DEL_REQUEST_ID - 1), "demasiado corto"),
        ("a" * (LONGITUD_MAXIMA_DEL_REQUEST_ID + 1), "excede VARCHAR(64)"),
        ("con espacio", "espacio"),
        ("salto\nde-linea", "inyeccion de linea de log"),
        ("retorno\r-carro", "inyeccion de linea de log"),
        ("tabulador\tinterno", "control"),
        ("información-acentuada", "no ASCII: el alfabeto es cerrado"),
        ("emoji-😀-dentro", "no ASCII"),
        ("con:dos:puntos", "fuera del alfabeto"),
        ("con/barra", "fuera del alfabeto"),
        ("con.punto", "fuera del alfabeto"),
    ],
)
def test_se_rechaza_un_valor_fuera_del_contrato(valor: str, motivo: str) -> None:
    assert not es_request_id_valido(valor), motivo


def test_el_limite_de_longitud_coincide_con_la_columna_de_auditoria() -> None:
    """`audit_events.request_id` es `VARCHAR(64)`: el limite no es arbitrario."""
    from app.modules.audit.infrastructure.models import LONGITUD_DE_IDENTIFICADOR_DE_PETICION

    assert LONGITUD_MAXIMA_DEL_REQUEST_ID == LONGITUD_DE_IDENTIFICADOR_DE_PETICION


# --- Politica de resolucion ----------------------------------------------


def test_sin_cabeceras_se_genera_uno_nuevo() -> None:
    resuelto, descartado = resolver_request_id([])

    assert es_request_id_valido(resuelto)
    assert descartado is False


def test_con_exactamente_una_cabecera_valida_se_reutiliza() -> None:
    resuelto, descartado = resolver_request_id(["trace-de-un-cliente"])

    assert resuelto == "trace-de-un-cliente"
    assert descartado is False


def test_con_exactamente_una_cabecera_invalida_se_descarta_y_se_genera() -> None:
    resuelto, descartado = resolver_request_id(["no valido"])

    assert resuelto != "no valido"
    assert es_request_id_valido(resuelto)
    assert descartado is True


def test_con_dos_cabeceras_validas_se_descartan_las_dos_no_una() -> None:
    """Fail-safe: con varios candidatos no hay eleccion no arbitraria posible.

    Es el caso que la version anterior de la ficha resolvia apoyandose en que
    *"Starlette devuelve el primer valor"*. Depender de la politica
    *first-wins* / *last-wins* de un framework —o de un proxy intermedio, que
    puede ser la contraria— produce justo la ambiguedad que un correlation ID
    existe para eliminar.
    """
    resuelto, descartado = resolver_request_id(["primero-valido", "segundo-valido"])

    assert resuelto != "primero-valido"
    assert resuelto != "segundo-valido"
    assert es_request_id_valido(resuelto)
    assert descartado is True


def test_con_una_valida_y_una_invalida_tampoco_se_conserva_la_valida() -> None:
    resuelto, descartado = resolver_request_id(["valido-de-verdad", "no valido"])

    assert resuelto != "valido-de-verdad"
    assert descartado is True


def test_con_tres_o_mas_cabeceras_se_descartan_todas() -> None:
    entrantes = ["uno-valido", "dos-valido", "tres-valido"]

    resuelto, descartado = resolver_request_id(entrantes)

    assert resuelto not in entrantes
    assert descartado is True


def test_la_resolucion_nunca_concatena_los_valores_recibidos() -> None:
    resuelto, _ = resolver_request_id(["aaaaaaaa", "bbbbbbbb"])

    assert "aaaaaaaa" not in resuelto
    assert "bbbbbbbb" not in resuelto
