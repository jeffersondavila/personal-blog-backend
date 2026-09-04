"""La regla del texto alternativo al usar una imagen (`Task/012`, D-012-Y).

Dominio puro: decide **qué** hay que escribir, sin saber de PostgreSQL ni de HTTP.
La regla vive en el módulo `media` porque `alt_text` es metadato **del asset** —
está en `media_assets`, no en una columna por asociación— y ese módulo es su dueño
(software-architecture.md §3.3).

Fuente de la regla: `data-model.md` §4.1 y **D-010-N** de `Task/010`, que dicen
que `alt_text` *«se escribe al **usar** la imagen, no al cargarla»*.
"""

from __future__ import annotations

import pytest

from app.modules.media.domain.texto_alternativo import (
    TextoAlternativoEnConflictoError,
    texto_a_escribir,
)
from app.shared.errors.exceptions import ConflictError

CAMPO = "cover_alt_text"


def _resolver(actual: str | None, propuesto: str | None) -> str | None:
    return texto_a_escribir(actual=actual, propuesto=propuesto, campo=CAMPO)


# --- Primer uso: se escribe ------------------------------------------------
@pytest.mark.parametrize("actual", [None, "", "   "])
def test_el_primer_uso_escribe_el_texto_propuesto(actual: str | None) -> None:
    """Una imagen sin texto útil lo recibe de quien la usa.

    Los tres valores de `actual` son la misma cosa: para un lector de pantalla,
    la ausencia y una cadena en blanco no se distinguen.
    """
    assert _resolver(actual, "Un retrato") == "Un retrato"


def test_el_texto_propuesto_se_guarda_sin_espacios_sobrantes() -> None:
    assert _resolver(None, "  Un retrato  ") == "Un retrato"


# --- Nada que escribir -----------------------------------------------------
@pytest.mark.parametrize("propuesto", [None, "", "   "])
def test_sin_texto_propuesto_no_se_escribe_nada(propuesto: str | None) -> None:
    """No proponer nada **no** borra lo que la imagen ya tenga."""
    assert _resolver("Retrato", propuesto) is None


@pytest.mark.parametrize("propuesto", [None, "", "   "])
def test_sin_texto_propuesto_y_sin_texto_previo_tampoco(propuesto: str | None) -> None:
    assert _resolver(None, propuesto) is None


def test_reenviar_el_mismo_texto_no_escribe_nada() -> None:
    """Un panel que devuelve el texto que mostró no está pidiendo ningún cambio.

    Devolver `None` —y no el mismo valor— evita una escritura inútil que además
    movería `updated_at` de una fila que nadie cambió.
    """
    assert _resolver("Retrato", "Retrato") is None


def test_el_mismo_texto_con_espacios_alrededor_sigue_siendo_el_mismo() -> None:
    assert _resolver("Retrato", "  Retrato  ") is None


# --- Texto distinto: no se sobrescribe -------------------------------------
def test_un_texto_distinto_no_se_sobrescribe() -> None:
    """`alt_text` es del **asset**: cambiarlo afectaría a quien ya lo usa.

    Es la misma forma del riesgo que **D-010-J** describe para la
    deduplicación: *«reutilizar en silencio haría que borrar un medio afectara a
    contenidos que nunca lo subieron»*. Ninguna fuente vigente define qué debe
    ocurrir aquí, así que se rechaza —que no cambia nada y es reversible— en
    lugar de sobrescribir, que no lo sería.
    """
    with pytest.raises(TextoAlternativoEnConflictoError) as error:
        _resolver("Retrato del autor", "Diagrama de red")

    assert error.value.actual == "Retrato del autor"
    assert error.value.propuesto == "Diagrama de red"
    assert error.value.campo == CAMPO


def test_el_conflicto_es_un_409_con_su_codigo_estable() -> None:
    assert issubclass(TextoAlternativoEnConflictoError, ConflictError)
    assert TextoAlternativoEnConflictoError.code == "alt_text_conflict"

    error = TextoAlternativoEnConflictoError(campo=CAMPO, actual="A", propuesto="B")
    assert error.status_code == 409
    assert error.details == {"campo": CAMPO, "actual": "A", "propuesto": "B"}


def test_el_conflicto_no_se_dispara_contra_un_texto_previo_en_blanco() -> None:
    """Un texto en blanco no es un texto: se trata como primer uso, no conflicto."""
    assert _resolver("   ", "Un retrato") == "Un retrato"
