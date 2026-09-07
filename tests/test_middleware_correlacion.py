"""Propagacion del correlation ID y evento de peticion (`Task/017`, O-01 y O-02).

Lo que estas pruebas fijan es el comportamiento **observable de extremo a
extremo**: que la respuesta lleve la cabecera, que el evento de peticion sea
parseable por campos, y que dos peticiones concurrentes no compartan
identificador.

Por que `capsys` y no `caplog`
-------------------------------

`create_app()` llama a `configure_logging()`, que **reemplaza** los manejadores
del logger raiz —es lo que garantiza un unico formato de salida—, y entre los
que reemplaza esta el que instala `caplog`. Leer `stdout` no es un rodeo: es la
comprobacion mas fiel, porque prueba exactamente la linea JSON que acabara en
Docker y en Portainer, incluido su nivel y su formato.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shared.logging.contexto import (
    NOMBRE_DE_LA_CABECERA_DE_CORRELACION,
    es_request_id_valido,
    request_id_actual,
)

CABECERA = NOMBRE_DE_LA_CABECERA_DE_CORRELACION


@pytest.fixture
def cliente_observable(settings_factory: Any) -> Any:
    """Factoria de un cliente cuya aplicacion emite log JSON a `DEBUG`.

    Es una **factoria** y no un cliente ya construido por una razon concreta de
    pytest: la captura de salida usa un `sys.stdout` distinto en cada fase
    —`setup`, `call`, `teardown`—, y `configure_logging` crea su `StreamHandler`
    con el que exista **en ese instante** y guarda la referencia. Una aplicacion
    construida durante el `setup` de una fixture escribiria al stream de esa
    fase, y `capsys.readouterr()` en el cuerpo del test devolveria vacio.

    Invocandola dentro del test, el manejador queda atado al stream correcto.

    `DEBUG` es necesario para observar el evento de las sondas, que a nivel
    normal no se emite justamente porque esta tarea lo baja de nivel.
    """
    from app.main import create_app

    @contextmanager
    def _construir() -> Iterator[TestClient]:
        configuracion = settings_factory(log_format="json", log_level="DEBUG")
        aplicacion = create_app(settings=configuracion)
        with TestClient(aplicacion, raise_server_exceptions=False) as cliente:
            yield cliente

    return _construir


def _lineas(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """Todas las lineas de log emitidas, ya parseadas.

    Que cada una sea JSON valido de forma independiente es parte de lo que se
    comprueba: si alguna no lo fuera, esto fallaria aqui (requisito O-01).
    """
    salida = capsys.readouterr().out
    return [json.loads(texto) for texto in salida.splitlines() if texto.strip()]


def _eventos_de_peticion(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [linea for linea in _lineas(capsys) if linea.get("message") == "Peticion completada"]


# --- La cabecera de respuesta --------------------------------------------


def test_una_respuesta_correcta_lleva_la_cabecera(client: TestClient) -> None:
    respuesta = client.get("/health")

    assert es_request_id_valido(respuesta.headers[CABECERA])


@pytest.mark.parametrize(
    "ruta",
    ["/health", "/openapi.json", "/api/v1/no-existe-task017", "/sitemap.xml"],
)
def test_toda_ruta_devuelve_la_cabecera_sea_cual_sea_su_estado(
    client: TestClient, ruta: str
) -> None:
    assert CABECERA in client.get(ruta).headers


def test_un_404_lleva_el_mismo_id_en_la_cabecera_y_en_el_cuerpo(client: TestClient) -> None:
    respuesta = client.get("/api/v1/no-existe-task017")

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["request_id"] == respuesta.headers[CABECERA]


def test_un_422_lleva_el_mismo_id_en_la_cabecera_y_en_el_cuerpo(client: TestClient) -> None:
    respuesta = client.get("/api/v1/posts", params={"page": "no-es-un-numero"})

    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["request_id"] == respuesta.headers[CABECERA]


def test_un_401_lleva_el_mismo_id_en_la_cabecera_y_en_el_cuerpo(client: TestClient) -> None:
    respuesta = client.get("/api/v1/admin/auth/me")

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["request_id"] == respuesta.headers[CABECERA]


def test_un_405_tambien_lleva_la_cabecera(client: TestClient) -> None:
    respuesta = client.post("/health")

    assert respuesta.status_code == 405
    assert CABECERA in respuesta.headers


def test_dos_peticiones_reciben_identificadores_distintos(client: TestClient) -> None:
    primera = client.get("/health").headers[CABECERA]
    segunda = client.get("/health").headers[CABECERA]

    assert primera != segunda


# --- Politica de entrada, extremo a extremo -------------------------------


def test_un_identificador_valido_entrante_se_reutiliza(client: TestClient) -> None:
    respuesta = client.get("/health", headers={CABECERA: "trace-de-un-cliente"})

    assert respuesta.headers[CABECERA] == "trace-de-un-cliente"


def test_un_identificador_invalido_no_produce_400_y_se_sustituye(client: TestClient) -> None:
    respuesta = client.get("/health", headers={CABECERA: "no valido"})

    assert respuesta.status_code == 200
    assert respuesta.headers[CABECERA] != "no valido"
    assert es_request_id_valido(respuesta.headers[CABECERA])


def test_un_identificador_demasiado_largo_se_sustituye(client: TestClient) -> None:
    respuesta = client.get("/health", headers={CABECERA: "a" * 65})

    assert respuesta.headers[CABECERA] != "a" * 65


def test_un_identificador_de_64_caracteres_se_acepta(client: TestClient) -> None:
    """El limite exacto de `VARCHAR(64)`, no uno aproximado."""
    respuesta = client.get("/health", headers={CABECERA: "b" * 64})

    assert respuesta.headers[CABECERA] == "b" * 64


def test_dos_cabeceras_repetidas_se_descartan_las_dos(client: TestClient) -> None:
    """Fail-safe: el resultado no depende de first-wins ni de last-wins."""
    respuesta = client.get(
        "/health",
        headers=[(CABECERA, "primero-valido"), (CABECERA, "segundo-valido")],
    )

    devuelto = respuesta.headers[CABECERA]
    assert devuelto != "primero-valido"
    assert devuelto != "segundo-valido"
    assert es_request_id_valido(devuelto)


def test_el_descarte_se_registra_como_booleano_y_sin_el_valor_recibido(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    with cliente_observable() as cliente:
        cliente.get("/health", headers={CABECERA: "valor rechazado con espacios"})

    lineas = _lineas(capsys)
    eventos = [linea for linea in lineas if linea.get("message") == "Peticion completada"]
    assert eventos, "no se emitio ningun evento de peticion"
    assert eventos[-1]["context"]["incoming_request_id_discarded"] is True

    completo = json.dumps(lineas)
    assert "valor rechazado con espacios" not in completo


def test_sin_descarte_no_se_marca_el_booleano(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    with cliente_observable() as cliente:
        cliente.get("/health")

    evento = _eventos_de_peticion(capsys)[-1]
    assert "incoming_request_id_discarded" not in evento["context"]


def test_un_valor_rechazado_nunca_aparece_en_ninguna_linea(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    with cliente_observable() as cliente:
        cliente.get("/health", headers={CABECERA: "TASK017 VALOR RECHAZADO"})

    assert "TASK017 VALOR RECHAZADO" not in json.dumps(_lineas(capsys))


# --- El evento de peticion ------------------------------------------------


def test_cada_peticion_emite_un_evento_con_los_campos_estructurados(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    with cliente_observable() as cliente:
        respuesta = cliente.get("/api/v1/no-existe-task017")

    eventos = _eventos_de_peticion(capsys)
    assert len(eventos) == 1
    contexto = eventos[0]["context"]

    assert contexto["request_id"] == respuesta.headers[CABECERA]
    assert contexto["method"] == "GET"
    assert contexto["path"] == "/api/v1/no-existe-task017"
    assert contexto["status_code"] == 404
    assert isinstance(contexto["duration_ms"], int | float)
    assert contexto["duration_ms"] >= 0


def test_el_evento_no_incluye_la_query_string_en_el_path(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Medido en el baseline: la query entraba tal cual en el log de acceso."""
    with cliente_observable() as cliente:
        cliente.get("/api/v1/posts", params={"page": 1, "page_size": 3})

    evento = _eventos_de_peticion(capsys)[-1]

    assert evento["context"]["path"] == "/api/v1/posts"
    assert "page_size" not in json.dumps(evento)


def test_todos_los_logs_de_una_peticion_llevan_su_identificador(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    with cliente_observable() as cliente:
        respuesta = cliente.get("/api/v1/admin/auth/me")
    esperado = respuesta.headers[CABECERA]

    con_id = [
        linea["context"]["request_id"]
        for linea in _lineas(capsys)
        if linea["logger"] in {"app.peticion", "app.shared.errors.handlers"}
    ]

    assert len(con_id) >= 2, "se esperan al menos el log de error y el evento de peticion"
    assert set(con_id) == {esperado}


def test_duration_ms_ignora_un_salto_del_reloj_civil(
    cliente_observable: Any,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.shared.logging import middleware

    monotono = iter((100.0, 100.0123))
    civil = iter((datetime(2026, 9, 6), datetime(2025, 9, 6)))
    monkeypatch.setattr(middleware, "time", SimpleNamespace(perf_counter=lambda: next(monotono)))
    monkeypatch.setattr(
        middleware, "datetime", SimpleNamespace(now=lambda: next(civil)), raising=False
    )
    with cliente_observable() as cliente:
        assert cliente.get("/health").status_code == 200
    assert _eventos_de_peticion(capsys)[-1]["context"]["duration_ms"] == 12.3


def test_uvicorn_error_conserva_el_id_despues_de_salir_del_middleware(
    settings_factory: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import logging

    from app.main import create_app

    aplicacion = create_app(settings=settings_factory(log_format="json"))

    @aplicacion.get("/_fallo_servidor")
    def _fallar() -> None:
        raise RuntimeError("fallo de servidor para correlacion")

    with TestClient(aplicacion, raise_server_exceptions=True) as cliente:
        try:
            cliente.get("/_fallo_servidor", headers={CABECERA: "task017-error-servidor"})
        except RuntimeError:
            assert request_id_actual() is None, "el contexto debe haberse restaurado"
            # Es el boundary real de Uvicorn: registra DESPUES de que ASGI
            # propague la excepcion. El TestClient no genera ese LogRecord.
            logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    servidor = next(linea for linea in _lineas(capsys) if linea["logger"] == "uvicorn.error")
    assert servidor["context"]["request_id"] == "task017-error-servidor"


def test_el_log_del_error_y_el_evento_comparten_identificador(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Es lo que el baseline no permitia: la linea de acceso no llevaba el ID."""
    with cliente_observable() as cliente:
        cliente.get("/api/v1/no-existe-task017")

    lineas = _lineas(capsys)
    del_error = next(linea for linea in lineas if linea["logger"] == "app.shared.errors.handlers")
    del_evento = next(linea for linea in lineas if linea.get("message") == "Peticion completada")

    assert del_error["context"]["request_id"] == del_evento["context"]["request_id"]


def test_cada_linea_emitida_es_json_independiente(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    with cliente_observable() as cliente:
        cliente.get("/api/v1/posts")
        cliente.get("/api/v1/no-existe-task017")

    lineas = _lineas(capsys)

    assert lineas, "no se emitio nada"
    for linea in lineas:
        assert {"timestamp", "level", "logger", "message"} <= set(linea)


def test_uvicorn_access_no_emite_una_segunda_linea_por_la_misma_peticion(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sustituido por el evento propio; `uvicorn.error` sigue intacto."""
    with cliente_observable() as cliente:
        cliente.get("/api/v1/posts")

    loggers = [linea["logger"] for linea in _lineas(capsys)]

    assert "uvicorn.access" not in loggers


# --- Niveles --------------------------------------------------------------


def test_una_sonda_satisfactoria_se_registra_a_debug(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """90,8 % del log medido eran sondas a `/health`: no pueden ir a INFO."""
    with cliente_observable() as cliente:
        cliente.get("/health")

    assert _eventos_de_peticion(capsys)[-1]["level"] == "DEBUG"


def test_una_peticion_normal_correcta_se_registra_a_info(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """`/openapi.json` y no `/api/v1/posts`: esta prueba habla de **niveles**.

    Un listado consulta PostgreSQL, que en una prueba unitaria no existe, asi
    que devolveria `500` y comprobaria el nivel del caso equivocado. La ruta
    elegida responde `200` sin dependencias y no es una sonda.
    """
    with cliente_observable() as cliente:
        cliente.get("/openapi.json")

    assert _eventos_de_peticion(capsys)[-1]["level"] == "INFO"


def test_un_404_no_se_registra_como_error(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un 404 en una API publica es funcionamiento correcto, no un defecto."""
    with cliente_observable() as cliente:
        cliente.get("/api/v1/no-existe-task017")

    assert _eventos_de_peticion(capsys)[-1]["level"] == "INFO"


def test_un_401_se_registra_como_advertencia(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    with cliente_observable() as cliente:
        cliente.get("/api/v1/admin/auth/me")

    assert _eventos_de_peticion(capsys)[-1]["level"] == "WARNING"


def test_un_422_no_se_registra_como_error(
    cliente_observable: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    with cliente_observable() as cliente:
        cliente.get("/api/v1/posts", params={"page": "x"})

    assert _eventos_de_peticion(capsys)[-1]["level"] == "INFO"


# --- Aislamiento entre peticiones ----------------------------------------


def test_el_contexto_no_sobrevive_a_la_peticion(client: TestClient) -> None:
    """Sin `reset` en un `finally`, el valor se filtra a la siguiente peticion."""
    client.get("/health")

    assert request_id_actual() is None


def test_dos_peticiones_concurrentes_no_mezclan_sus_identificadores(
    application: FastAPI,
) -> None:
    """Detecta una implementacion con estado compartido o sin `reset`.

    Cada peticion registra el `request_id` que ve **desde dentro del endpoint**,
    con la otra peticion en vuelo. Una variable global, un atributo de modulo o
    un `ContextVar` mal restaurado hacen que una de las dos vea el valor ajeno.
    """
    barrera = threading.Barrier(2, timeout=10)
    visto: dict[str, str] = {}

    @application.get("/_prueba_concurrencia_017")
    def _endpoint_de_prueba() -> dict[str, str]:
        propio = request_id_actual() or ""
        # Ambas peticiones quedan dentro del endpoint a la vez: si el contexto
        # se compartiera, aqui es donde se cruzarian.
        barrera.wait()
        assert propio == (request_id_actual() or ""), "el contexto cambio bajo los pies"
        return {"request_id": propio}

    def _pedir(nombre: str) -> None:
        with TestClient(application) as cliente:
            respuesta = cliente.get("/_prueba_concurrencia_017")
            visto[nombre] = respuesta.json()["request_id"]
            visto[f"{nombre}_cabecera"] = respuesta.headers[CABECERA]

    hilos = [threading.Thread(target=_pedir, args=(nombre,)) for nombre in ("a", "b")]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=20)

    assert visto.get("a") and visto.get("b")
    assert visto["a"] != visto["b"], "las dos peticiones compartieron identificador"
    assert visto["a"] == visto["a_cabecera"]
    assert visto["b"] == visto["b_cabecera"]
