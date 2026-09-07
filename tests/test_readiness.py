"""Contrato HTTP de `GET /ready` (`Task/017`, requisito O-04).

Aqui se fija la **forma** del endpoint. Que la sonda detecte de verdad cada
escenario de fallo se prueba contra PostgreSQL y MinIO reales en
`tests/integration/test_readiness_dependencias.py` y
`tests/integration/test_readiness_almacenamiento.py`: eso no se simula.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shared.storage import ErrorDeAlmacenamiento


class _AlmacenamientoDisponible:
    """Doble de `ObjectStorage` que dice estar disponible."""

    def comprobar_disponibilidad(self) -> None:
        return None


class _AlmacenamientoCaido:
    """Doble cuyo fallo trae un mensaje con datos que no deben salir por HTTP."""

    def comprobar_disponibilidad(self) -> None:
        raise ErrorDeAlmacenamiento(
            "no se pudo comprobar la disponibilidad en el bucket privado-interno "
            "contra http://minio-interno:9000 (NoSuchBucket)"
        )


@pytest.fixture
def aplicacion_lista(application: FastAPI) -> FastAPI:
    """Aplicacion con las dos dependencias respondiendo que si."""
    from app.api.readiness import comprobar_base_de_datos, obtener_almacenamiento_para_readiness

    application.dependency_overrides[comprobar_base_de_datos] = lambda: None
    application.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoDisponible()
    )
    return application


def _cliente(aplicacion: FastAPI) -> TestClient:
    return TestClient(aplicacion, raise_server_exceptions=False)


def test_ready_responde_200_cuando_todo_esta_disponible(aplicacion_lista: FastAPI) -> None:
    respuesta = _cliente(aplicacion_lista).get("/ready")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ready"}


def test_ready_declara_json(aplicacion_lista: FastAPI) -> None:
    respuesta = _cliente(aplicacion_lista).get("/ready")

    assert respuesta.headers["content-type"].startswith("application/json")


def test_ready_no_se_cachea(aplicacion_lista: FastAPI) -> None:
    """Una sonda cacheada informaria del pasado, que es peor que no informar."""
    respuesta = _cliente(aplicacion_lista).get("/ready")

    assert respuesta.headers["cache-control"] == "no-store"


def test_ready_esta_fuera_del_prefijo_versionado(aplicacion_lista: FastAPI) -> None:
    """Mismo criterio que `/health`: la consume la plataforma, no el frontend."""
    cliente = _cliente(aplicacion_lista)

    assert cliente.get("/ready").status_code == 200
    assert cliente.get("/api/v1/ready").status_code == 404


def test_ready_no_responde_a_metodos_no_permitidos(aplicacion_lista: FastAPI) -> None:
    assert _cliente(aplicacion_lista).post("/ready").status_code == 405


def test_ready_no_exige_autenticacion(aplicacion_lista: FastAPI) -> None:
    assert _cliente(aplicacion_lista).get("/ready").status_code == 200


# --- Fallo ----------------------------------------------------------------


def test_ready_responde_503_si_la_base_de_datos_falla(application: FastAPI) -> None:
    from app.api.readiness import (
        COMPONENTE_BASE_DE_DATOS,
        comprobar_base_de_datos,
        obtener_almacenamiento_para_readiness,
    )

    application.dependency_overrides[comprobar_base_de_datos] = lambda: COMPONENTE_BASE_DE_DATOS
    application.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoDisponible()
    )

    respuesta = _cliente(application).get("/ready")

    assert respuesta.status_code == 503
    assert respuesta.json() == {"status": "not_ready"}


def test_ready_responde_503_si_el_almacenamiento_falla(application: FastAPI) -> None:
    from app.api.readiness import comprobar_base_de_datos, obtener_almacenamiento_para_readiness

    application.dependency_overrides[comprobar_base_de_datos] = lambda: None
    application.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoCaido()
    )

    respuesta = _cliente(application).get("/ready")

    assert respuesta.status_code == 503
    assert respuesta.json() == {"status": "not_ready"}


def test_el_cuerpo_del_fallo_no_filtra_infraestructura(application: FastAPI) -> None:
    """Ni bucket, ni anfitrion interno, ni excepcion cruda, ni traza (S-07)."""
    from app.api.readiness import comprobar_base_de_datos, obtener_almacenamiento_para_readiness

    application.dependency_overrides[comprobar_base_de_datos] = lambda: None
    application.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoCaido()
    )

    cuerpo = _cliente(application).get("/ready").text

    for filtracion in (
        "privado-interno",
        "minio-interno",
        "NoSuchBucket",
        "ErrorDeAlmacenamiento",
        "Traceback",
        "postgresql://",
    ):
        assert filtracion not in cuerpo, filtracion


def test_el_cuerpo_del_fallo_no_dice_que_componente_fallo(application: FastAPI) -> None:
    """A un cliente anonimo no se le dice **que** parte de la infraestructura cayo.

    El operador obtiene el detalle del log, que si distingue componente y motivo.
    """
    from app.api.readiness import comprobar_base_de_datos, obtener_almacenamiento_para_readiness

    application.dependency_overrides[comprobar_base_de_datos] = lambda: None
    application.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoCaido()
    )

    cuerpo = _cliente(application).get("/ready").json()

    assert set(cuerpo) == {"status"}


def test_ready_lleva_el_correlation_id(aplicacion_lista: FastAPI) -> None:
    from app.shared.logging.contexto import NOMBRE_DE_LA_CABECERA_DE_CORRELACION

    respuesta = _cliente(aplicacion_lista).get("/ready")

    assert NOMBRE_DE_LA_CABECERA_DE_CORRELACION in respuesta.headers


def test_el_fallo_se_registra_con_el_componente_y_el_motivo(
    application: FastAPI, settings_factory: Any
) -> None:
    """Lo que la respuesta calla, el log lo dice."""
    import json
    import logging

    from app.api.readiness import comprobar_base_de_datos, obtener_almacenamiento_para_readiness

    application.dependency_overrides[comprobar_base_de_datos] = lambda: None
    application.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoCaido()
    )

    registros: list[logging.LogRecord] = []

    class _Recolector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            registros.append(record)

    recolector = _Recolector()
    logging.getLogger("app.api.readiness").addHandler(recolector)
    try:
        _cliente(application).get("/ready")
    finally:
        logging.getLogger("app.api.readiness").removeHandler(recolector)

    assert registros, "el fallo de readiness no se registro"
    contexto = json.dumps(registros[-1].__dict__, default=str)
    assert "almacenamiento" in contexto


def test_ready_acota_el_tiempo_total_aunque_el_driver_se_bloquee(
    aplicacion_lista: FastAPI,
) -> None:
    from app.api.readiness import obtener_almacenamiento_para_readiness

    liberar = threading.Event()

    class _AlmacenamientoBloqueado:
        def comprobar_disponibilidad(self) -> None:
            liberar.wait(timeout=3.5)

    aplicacion_lista.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoBloqueado()
    )
    try:
        inicio = time.perf_counter()
        respuesta = _cliente(aplicacion_lista).get("/ready")
        duracion = time.perf_counter() - inicio
        assert respuesta.status_code == 503
        assert respuesta.json() == {"status": "not_ready"}
        assert duracion < 3.0
        assert respuesta.headers["cache-control"] == "no-store"
        assert respuesta.headers["x-request-id"]
    finally:
        liberar.set()


def test_el_evento_de_ready_fallido_se_emite_a_warning(application: FastAPI) -> None:
    import logging

    from app.api.readiness import comprobar_base_de_datos, obtener_almacenamiento_para_readiness

    application.dependency_overrides[comprobar_base_de_datos] = lambda: None
    application.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoCaido()
    )
    registros: list[logging.LogRecord] = []

    class _Recolector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            registros.append(record)

    recolector = _Recolector()
    logger = logging.getLogger("app.peticion")
    logger.addHandler(recolector)
    try:
        assert _cliente(application).get("/ready").status_code == 503
    finally:
        logger.removeHandler(recolector)
    assert registros[-1].levelno == logging.WARNING


def test_sondas_bloqueadas_no_acumulan_trabajo_y_se_recuperan(aplicacion_lista: FastAPI) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from app.api.readiness import obtener_almacenamiento_para_readiness

    liberar = threading.Event()
    bloqueo = threading.Lock()
    llamadas = 0
    terminadas = 0

    class _AlmacenamientoBloqueado:
        def comprobar_disponibilidad(self) -> None:
            nonlocal llamadas, terminadas
            with bloqueo:
                llamadas += 1
            liberar.wait(timeout=4)
            with bloqueo:
                terminadas += 1

    aplicacion_lista.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoBloqueado()
    )
    try:
        with ThreadPoolExecutor(max_workers=4) as peticiones:
            respuestas = list(
                peticiones.map(lambda _: _cliente(aplicacion_lista).get("/ready"), range(4))
            )
        assert all(respuesta.status_code == 503 for respuesta in respuestas)
        assert 0 < llamadas <= 2, "las sondas agotadas acumularon trabajo"
    finally:
        liberar.set()
        limite = time.perf_counter() + 2
        while terminadas < llamadas and time.perf_counter() < limite:
            time.sleep(0.01)
    assert terminadas == llamadas
    aplicacion_lista.dependency_overrides[obtener_almacenamiento_para_readiness] = lambda: (
        _AlmacenamientoDisponible()
    )
    assert _cliente(aplicacion_lista).get("/ready").status_code == 200
