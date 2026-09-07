"""Pruebas de la redaccion del log (`Task/017`, requisito O-08, riesgo R-36).

R-36 quedo abierto en `Task/005.6` con esta causa exacta: *"`JsonLogFormatter`
emite en `context` **todo** atributo propio del `LogRecord` y serializa las
excepciones completas [...] no hay ningun mecanismo que lo impida"*.

Estas pruebas exigen un mecanismo, no disciplina. Los senuelos son unicos e
inequivocos, y se buscan en **la salida completa serializada**, nunca en un
campo concreto: un secreto que se filtre por `message` en lugar de por `context`
debe poner la prueba en rojo igual.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Final

import pytest

from app.shared.logging import JsonLogFormatter
from app.shared.logging.redaccion import MARCADOR_DE_REDACCION, redactar_texto, redactar_valor

SENUELO_PASSWORD: Final[str] = "TASK017_SECRET_PASSWORD_9f3a1c7e"
SENUELO_COOKIE: Final[str] = "TASK017_SECRET_COOKIE_5b2d8e4a"
SENUELO_AUTH: Final[str] = "TASK017_SECRET_AUTH_1a7c3f9b"
SENUELO_STORAGE_KEY: Final[str] = "TASK017_SECRET_STORAGE_KEY_6e4b2d8f"


def _linea(record: logging.LogRecord) -> str:
    return JsonLogFormatter().format(record)


def _registro(mensaje: str = "Mensaje de prueba", **extra: Any) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.prueba",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg=mensaje,
        args=(),
        exc_info=None,
    )
    for clave, valor in extra.items():
        setattr(record, clave, valor)
    return record


# --- Claves sensibles por nombre -----------------------------------------


def test_una_clave_de_contexto_sensible_se_redacta_por_su_nombre() -> None:
    salida = _linea(_registro(password=SENUELO_PASSWORD))

    assert SENUELO_PASSWORD not in salida
    assert MARCADOR_DE_REDACCION in salida


def test_el_nombre_de_la_clave_sensible_se_reconoce_sin_distinguir_mayusculas() -> None:
    for clave in ("Authorization", "AUTHORIZATION", "authorization"):
        salida = _linea(_registro(**{clave: SENUELO_AUTH}))
        assert SENUELO_AUTH not in salida, clave


def test_se_redactan_todas_las_familias_de_claves_sensibles() -> None:
    sensibles = {
        "password": SENUELO_PASSWORD,
        "password_hash": SENUELO_PASSWORD,
        "authorization": SENUELO_AUTH,
        "cookie": SENUELO_COOKIE,
        "set_cookie": SENUELO_COOKIE,
        "session_id": SENUELO_COOKIE,
        "token": SENUELO_AUTH,
        "secret_key": SENUELO_STORAGE_KEY,
        "access_key": SENUELO_STORAGE_KEY,
        "storage_secret_key": SENUELO_STORAGE_KEY,
        "database_url": SENUELO_PASSWORD,
        "email": "victima@example.invalid",
        "request_body": SENUELO_PASSWORD,
        "response_body": SENUELO_PASSWORD,
    }
    for clave, valor in sensibles.items():
        salida = _linea(_registro(**{clave: valor}))
        assert valor not in salida, f"la clave {clave} no se redacto"


def test_una_clave_sensible_anidada_tambien_se_redacta() -> None:
    salida = _linea(_registro(detalle={"nivel": {"password": SENUELO_PASSWORD}}))

    assert SENUELO_PASSWORD not in salida


def test_una_clave_sensible_dentro_de_una_lista_tambien_se_redacta() -> None:
    salida = _linea(_registro(intentos=[{"token": SENUELO_AUTH}]))

    assert SENUELO_AUTH not in salida


# --- Patrones por forma del valor ----------------------------------------


def test_una_dsn_con_contrasena_se_redacta_aunque_la_clave_sea_inocente() -> None:
    dsn = f"postgresql://blog:{SENUELO_PASSWORD}@postgres:5432/personal_blog"

    salida = _linea(_registro(dato_cualquiera=dsn))

    assert SENUELO_PASSWORD not in salida
    assert "postgres" in salida, "la parte no sensible sigue siendo util para diagnosticar"


def test_una_url_prefirmada_pierde_su_firma() -> None:
    url = (
        "http://localhost:9000/media/abc.jpg?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        f"&X-Amz-Credential={SENUELO_STORAGE_KEY}&X-Amz-Signature=deadbeefcafe"
    )

    salida = _linea(_registro(enlace=url))

    assert SENUELO_STORAGE_KEY not in salida
    assert "deadbeefcafe" not in salida


def test_una_credencial_bearer_en_el_mensaje_se_redacta() -> None:
    salida = _linea(_registro(f"Fallo con Bearer {SENUELO_AUTH} al final"))

    assert SENUELO_AUTH not in salida


def test_el_mensaje_tambien_pasa_por_el_redactor() -> None:
    dsn = f"postgresql://blog:{SENUELO_PASSWORD}@postgres:5432/db"

    salida = _linea(_registro(f"No se pudo conectar a {dsn}"))

    assert SENUELO_PASSWORD not in salida


# --- Excepciones: el punto ciego que R-36 describe -------------------------


def test_una_excepcion_que_lleva_un_secreto_no_lo_filtra_por_la_traza() -> None:
    try:
        raise RuntimeError(f"conexion rechazada para postgresql://u:{SENUELO_PASSWORD}@h/db")
    except RuntimeError:
        record = _registro("Error no controlado")
        record.exc_info = sys.exc_info()

    salida = _linea(record)

    assert SENUELO_PASSWORD not in salida
    assert "RuntimeError" in salida, "el tipo se conserva: sin el no hay diagnostico"


def test_la_causa_encadenada_tampoco_filtra_el_secreto() -> None:
    """La fuga real de un driver llega por la **causa**, no por la excepcion visible.

    Es el escenario que R-36 describe: `FalloDelProveedorDeAlmacenamientoError`
    y las excepciones de `psycopg` sanean su propio mensaje, pero dejan la
    original en `__cause__` *"para el log"* — y esa si trae la cadena de
    conexion entera.
    """
    dsn = f"postgresql://blog:{SENUELO_PASSWORD}@postgres:5432/personal_blog"
    try:
        try:
            raise ValueError(f"connection to server failed: {dsn}")
        except ValueError as original:
            raise RuntimeError("fallo del proveedor") from original
    except RuntimeError:
        record = _registro("Error no controlado")
        record.exc_info = sys.exc_info()

    salida = _linea(record)

    assert SENUELO_PASSWORD not in salida
    assert "ValueError" in salida, "la causa sigue identificable para diagnosticar"


def test_limite_conocido_un_secreto_opaco_en_texto_libre_no_es_detectable() -> None:
    """Fija por prueba el limite REAL del redactor, en lugar de suponerlo cubierto.

    Un redactor por patrones reconoce **formas**: una DSN, una URL firmada, un
    esquema de autorizacion, un nombre de campo. Una cadena arbitraria sin
    ninguna marca —un secreto interpolado a mano en un texto libre— **no tiene
    forma que reconocer**, y ningun mecanismo automatico puede distinguirla de
    un dato legitimo.

    Por eso la regla de **no pasar secretos al logger** sigue vigente como
    segunda capa (S-08), y por eso `Task/018` conserva su parte de R-36. Esta
    prueba existe para que ese limite este escrito y se descubra al leerlo, no
    al sufrirlo: si algun dia el redactor lo cubriera, esta prueba fallara y
    obligara a actualizar la documentacion.
    """
    opaco = "TASK017_SECRET_OPACO_SIN_FORMA_RECONOCIBLE"

    salida = _linea(_registro(f"un texto libre cualquiera con {opaco} dentro"))

    assert opaco in salida


def test_la_pila_solicitada_tambien_se_redacta() -> None:
    record = _registro("Con pila")
    record.stack_info = f"linea con Bearer {SENUELO_AUTH}"

    assert SENUELO_AUTH not in _linea(record)


# --- Ruido interno de Uvicorn --------------------------------------------


def test_el_color_message_de_uvicorn_no_llega_al_json() -> None:
    """Medido en el contenedor: llegaba con secuencias ANSI dentro de `context`."""
    ansi = "Started server process [\x1b[36m%d\x1b[0m]"

    salida = _linea(_registro(color_message=ansi))

    assert "color_message" not in salida
    assert "\\u001b" not in salida
    assert "\x1b" not in salida


# --- Prueba positiva: el redactor no puede borrarlo todo ------------------


def test_los_campos_operativos_legitimos_si_aparecen() -> None:
    """Un redactor que borra todo pasaria las pruebas negativas y seria inutil."""
    salida = _linea(
        _registro(
            request_id="7f3c1a90-0000-4000-8000-000000000001",
            method="GET",
            path="/api/v1/posts",
            status_code=200,
            duration_ms=12.4,
            error_code="resource_not_found",
        )
    )
    contexto = json.loads(salida)["context"]

    assert contexto["request_id"] == "7f3c1a90-0000-4000-8000-000000000001"
    assert contexto["method"] == "GET"
    assert contexto["path"] == "/api/v1/posts"
    assert contexto["status_code"] == 200
    assert contexto["duration_ms"] == 12.4
    assert contexto["error_code"] == "resource_not_found"


def test_un_mensaje_sin_nada_sensible_se_conserva_intacto() -> None:
    assert "Aplicacion inicializada" in _linea(_registro("Aplicacion inicializada"))


def test_la_salida_sigue_siendo_una_sola_linea_de_json_valido() -> None:
    salida = _linea(_registro(password=SENUELO_PASSWORD, method="POST"))

    assert "\n" not in salida
    assert json.loads(salida)["context"]["method"] == "POST"


# --- Las funciones publicas del redactor ----------------------------------


def test_redactar_texto_es_idempotente() -> None:
    una_vez = redactar_texto(f"Bearer {SENUELO_AUTH}")

    assert redactar_texto(una_vez) == una_vez


def test_redactar_valor_sustituye_por_un_marcador_fijo_y_no_trunca() -> None:
    """Truncar filtraria el prefijo del secreto, que a veces ya basta."""
    redactado = redactar_valor("password", SENUELO_PASSWORD)

    assert redactado == MARCADOR_DE_REDACCION
    assert SENUELO_PASSWORD[:8] not in str(redactado)


@pytest.mark.parametrize(
    "mensaje",
    [
        "password=TASK017_SECRETO_ETIQUETADO",
        "Cookie: session=TASK017_SECRETO_ETIQUETADO",
        "storage_secret_key='TASK017_SECRETO_ETIQUETADO'",
        'fallo {"password": "TASK017_SECRETO_ETIQUETADO"}',
        "correo: TASK017_SECRETO_ETIQUETADO@example.invalid",
    ],
)
def test_una_excepcion_con_un_secreto_reconocible_no_lo_filtra(mensaje: str) -> None:
    try:
        try:
            raise ValueError(mensaje)
        except ValueError as causa:
            raise RuntimeError("fallo de prueba") from causa
    except RuntimeError:
        record = _registro("Error no controlado")
        record.exc_info = sys.exc_info()
    salida = _linea(record)
    assert "TASK017_SECRETO_ETIQUETADO" not in salida
    assert "ValueError" in salida
    assert "RuntimeError" in salida


def test_el_formato_texto_redacta_y_conserva_el_request_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import logging

    from app.shared.logging import configure_logging
    from app.shared.logging.contexto import establecer_request_id, restablecer_request_id

    configure_logging(log_format="text")
    token = establecer_request_id("task017-texto-seguro")
    try:
        logging.getLogger("prueba").error("Fallo Bearer TASK017_TOKEN_EN_TEXTO")
    finally:
        restablecer_request_id(token)
    salida = capsys.readouterr().out
    assert "TASK017_TOKEN_EN_TEXTO" not in salida
    assert "task017-texto-seguro" in salida


@pytest.mark.parametrize(
    "dato", ["password=secreto", "Cookie: session=secreto", "X-Amz-Signature=firma"]
)
def test_redaccion_etiquetada_es_idempotente(dato: str) -> None:
    una_vez = redactar_texto(dato)
    assert redactar_texto(una_vez) == una_vez


def test_un_cuerpo_en_bytes_en_el_mensaje_tambien_se_redacta() -> None:
    salida = _linea(_registro("request body: b'TASK017_CUERPO_BYTES'"))
    assert "TASK017_CUERPO_BYTES" not in salida


def test_un_dsn_ya_saneado_conserva_el_host_y_puerto() -> None:
    dsn = "postgresql://operador:***@127.0.0.1:55432/base"
    assert redactar_texto(dsn) == dsn
