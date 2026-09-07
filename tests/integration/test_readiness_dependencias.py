"""`/health` y `/ready` contra PostgreSQL y MinIO **reales** (`Task/017`).

Aqui se comprueba lo que un doble no puede demostrar: que `/health` sigue
respondiendo con las dependencias caidas, que `/ready` las detecta de verdad y
que ninguna de las dos se cuelga.

La indisponibilidad se simula **apuntando a un destino inalcanzable**, nunca
parando un servicio: la suite no puede tumbar el entorno local de nadie.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.almacenamiento_de_pruebas import DestinoDeAlmacenamiento

#: Puerto local sin servicio: rechaza la conexion de inmediato.
_DESTINO_INALCANZABLE = "127.0.0.1:9099"

#: Presupuesto de la sonda. El `healthCheck` de Traefik usa `timeout: 3s`; se
#: comprueba con holgura para no volver la prueba dependiente de la maquina,
#: pero muy por debajo de los valores por defecto de `botocore`, que con sus
#: reintentos llegarian a decenas de segundos.
_SEGUNDOS_DE_PRESUPUESTO = 10.0


@pytest.fixture
def configuracion_real(
    settings_factory: Any,
    destino_de_integracion_verificado: Any,
    destino_de_almacenamiento_verificado: DestinoDeAlmacenamiento,
) -> Any:
    """Factoria de configuraciones apuntando a PostgreSQL y MinIO reales."""

    def _crear(**overrides: Any) -> Any:
        valores: dict[str, Any] = {
            "database_url": str(destino_de_integracion_verificado[0].database_url),
            "storage_provider": "minio",
            "storage_bucket": destino_de_almacenamiento_verificado.bucket,
            "storage_endpoint_url": destino_de_almacenamiento_verificado.endpoint_url,
            "storage_access_endpoint_url": (
                destino_de_almacenamiento_verificado.access_endpoint_url
            ),
            "storage_access_key": destino_de_almacenamiento_verificado.access_key,
            "storage_secret_key": destino_de_almacenamiento_verificado.secret_key,
            "storage_region": destino_de_almacenamiento_verificado.region,
            **overrides,
        }
        return settings_factory(**valores)

    return _crear


@pytest.fixture
def cliente_real(configuracion_real: Any) -> Any:
    """Factoria de clientes contra dependencias reales o deliberadamente caidas."""
    from contextlib import contextmanager

    from app.main import create_app
    from app.shared.database import dispose_engine

    @contextmanager
    def _crear(**overrides: Any) -> Iterator[TestClient]:
        # El motor se memoriza por proceso: sin descartarlo, una prueba que
        # apunta a una base inalcanzable reutilizaria el motor de la anterior y
        # no comprobaria nada.
        dispose_engine()
        aplicacion = create_app(settings=configuracion_real(**overrides))
        try:
            with TestClient(aplicacion, raise_server_exceptions=False) as cliente:
                yield cliente
        finally:
            dispose_engine()

    return _crear


# --- O-03: `/health` es liveness y no depende de nada ---------------------


def test_health_responde_200_con_todo_disponible(cliente_real: Any) -> None:
    with cliente_real() as cliente:
        assert cliente.get("/health").status_code == 200


def test_health_sigue_respondiendo_200_con_la_base_de_datos_inalcanzable(
    cliente_real: Any,
) -> None:
    """La verificacion que faltaba desde `Task/005`.

    Es la garantia que justifica que el `HEALTHCHECK` de Docker siga en
    `/health`: durante un incidente de base de datos el contenedor permanece en
    marcha **y sus logs siguen siendo consultables**.
    """
    inalcanzable = f"postgresql://usuario:clave@{_DESTINO_INALCANZABLE}/base"

    with cliente_real(database_url=inalcanzable) as cliente:
        respuesta = cliente.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"


def test_health_sigue_respondiendo_200_con_el_almacenamiento_inalcanzable(
    cliente_real: Any,
) -> None:
    with cliente_real(storage_endpoint_url=f"http://{_DESTINO_INALCANZABLE}") as cliente:
        respuesta = cliente.get("/health")

    assert respuesta.status_code == 200


def test_health_sigue_respondiendo_200_con_ambas_dependencias_inalcanzables(
    cliente_real: Any,
) -> None:
    with cliente_real(
        database_url=f"postgresql://usuario:clave@{_DESTINO_INALCANZABLE}/base",
        storage_endpoint_url=f"http://{_DESTINO_INALCANZABLE}",
    ) as cliente:
        respuesta = cliente.get("/health")

    assert respuesta.status_code == 200


def test_health_responde_deprisa_aunque_las_dependencias_esten_caidas(
    cliente_real: Any,
) -> None:
    """Si `/health` consultara algo, este tiempo se dispararia."""
    with cliente_real(
        database_url=f"postgresql://usuario:clave@{_DESTINO_INALCANZABLE}/base",
        storage_endpoint_url=f"http://{_DESTINO_INALCANZABLE}",
    ) as cliente:
        comenzado_en = time.perf_counter()
        cliente.get("/health")
        transcurrido = time.perf_counter() - comenzado_en

    assert transcurrido < 1.0, f"/health tardo {transcurrido:.2f}s: parece consultar dependencias"


# --- O-04: `/ready` si depende de ellas -----------------------------------


def test_ready_responde_200_con_ambas_dependencias_reales(cliente_real: Any) -> None:
    with cliente_real() as cliente:
        respuesta = cliente.get("/ready")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ready"}


def test_ready_responde_503_con_la_base_de_datos_inalcanzable(cliente_real: Any) -> None:
    with cliente_real(
        database_url=f"postgresql://usuario:clave@{_DESTINO_INALCANZABLE}/base"
    ) as cliente:
        respuesta = cliente.get("/ready")

    assert respuesta.status_code == 503
    assert respuesta.json() == {"status": "not_ready"}


def test_ready_responde_503_con_el_almacenamiento_inalcanzable(cliente_real: Any) -> None:
    with cliente_real(storage_endpoint_url=f"http://{_DESTINO_INALCANZABLE}") as cliente:
        respuesta = cliente.get("/ready")

    assert respuesta.status_code == 503
    assert respuesta.json() == {"status": "not_ready"}


def test_ready_responde_503_con_el_bucket_inexistente(cliente_real: Any) -> None:
    """El escenario del falso positivo, ahora extremo a extremo por HTTP."""
    with cliente_real(storage_bucket="bucket-que-no-existe-task017-e2e") as cliente:
        respuesta = cliente.get("/ready")

    assert respuesta.status_code == 503
    assert respuesta.json() == {"status": "not_ready"}


def test_ready_responde_503_con_credenciales_de_almacenamiento_invalidas(
    cliente_real: Any,
) -> None:
    with cliente_real(
        storage_access_key="TASK017_CLAVE_INVALIDA",
        storage_secret_key="TASK017_SECRETO_INVALIDO",
    ) as cliente:
        respuesta = cliente.get("/ready")

    assert respuesta.status_code == 503


def test_ready_responde_503_con_las_dos_dependencias_caidas_sin_colgarse(
    cliente_real: Any,
) -> None:
    with cliente_real(
        database_url=f"postgresql://usuario:clave@{_DESTINO_INALCANZABLE}/base",
        storage_endpoint_url=f"http://{_DESTINO_INALCANZABLE}",
    ) as cliente:
        comenzado_en = time.perf_counter()
        respuesta = cliente.get("/ready")
        transcurrido = time.perf_counter() - comenzado_en

    assert respuesta.status_code == 503
    assert transcurrido < _SEGUNDOS_DE_PRESUPUESTO, (
        f"la sonda tardo {transcurrido:.1f}s con las dos dependencias caidas"
    )


def test_el_cuerpo_del_503_real_no_filtra_la_cadena_de_conexion(cliente_real: Any) -> None:
    with cliente_real(
        database_url=f"postgresql://usuario:TASK017_SECRET_DSN_EN_READY@{_DESTINO_INALCANZABLE}/b"
    ) as cliente:
        cuerpo = cliente.get("/ready").text

    assert "TASK017_SECRET_DSN_EN_READY" not in cuerpo
    assert "postgresql://" not in cuerpo
    assert "Traceback" not in cuerpo


def test_ready_no_escribe_en_la_base_de_datos(cliente_real: Any, configuracion_real: Any) -> None:
    """Una sonda que muta no es una sonda: se cuenta antes y despues."""
    from sqlalchemy import text

    from app.api.readiness import motor_de_sonda

    motor = motor_de_sonda(configuracion_real())

    with cliente_real() as cliente:
        with motor.connect() as conexion:
            antes = conexion.execute(text("SELECT count(*) FROM audit_events")).scalar_one()

        for _ in range(3):
            assert cliente.get("/ready").status_code == 200

        with motor.connect() as conexion:
            despues = conexion.execute(text("SELECT count(*) FROM audit_events")).scalar_one()

    assert despues == antes


@pytest.mark.parametrize("escenario", ["db", "storage", "bucket", "credenciales", "ambas"])
def test_ready_resuelve_antes_del_timeout_real_de_traefik(
    cliente_real: Any,
    escenario: str,
) -> None:
    cambios: dict[str, str] = {}
    if escenario in ("db", "ambas"):
        cambios["database_url"] = f"postgresql://usuario:clave@{_DESTINO_INALCANZABLE}/base"
    if escenario in ("storage", "ambas"):
        cambios["storage_endpoint_url"] = f"http://{_DESTINO_INALCANZABLE}"
    if escenario == "bucket":
        cambios["storage_bucket"] = "bucket-que-no-existe-task017-presupuesto"
    if escenario == "credenciales":
        cambios.update(storage_access_key="TASK017_INVALIDA", storage_secret_key="TASK017_INVALIDO")
    with cliente_real(**cambios) as cliente:
        inicio = time.perf_counter()
        respuesta = cliente.get("/ready")
        duracion = time.perf_counter() - inicio
    print(f"READINESS {escenario}: status={respuesta.status_code} elapsed={duracion:.3f}s")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"status": "not_ready"}
    assert duracion < 3.0, f"{escenario}: {duracion:.3f}s excede al consumidor de 3s"
