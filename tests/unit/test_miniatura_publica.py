"""Exposicion publica de la miniatura (`Task/016`, requisito P-04).

Cierra la **deuda 2 de `Task/010`**: *"la miniatura se almacena pero no se expone
en la API publica"*, cuyo propietario canonico es `Task/016` — asignado en el
reporte de `Task/010` y replicado en `STATUS.md`.

Que anade y que NO decide
-------------------------

Anade **un** campo mas de acceso, de la **misma naturaleza temporal** que
`access_url`: un enlace prefirmado que se genera al servir y caduca. Es un cambio
compatible (api-contracts.md seccion 10, regla 3): anade un campo opcional y no
retira ni renombra ninguno.

**No** decide nada de **D-08**: no crea ninguna URL estable de medios, ni
semantica de cache, ni TTL productivo, ni CDN. Eso sigue siendo de `Task/030`.
Confundir esta miniatura con una URL estable seria exactamente el error que
`Task/015` y `open-decisions.md` prohiben.

Por que no se exponen las dimensiones de la miniatura
-----------------------------------------------------

La miniatura **no** es una fila: su clave se deriva de la del original
(decision D-010-I) y sus dimensiones no se persisten. `width` y `height` del
medio son los del **original**, y sirven igual para reservar el espacio: la
miniatura conserva la proporcion (D-010-H, `thumbnail` nunca amplia), asi que la
relacion de aspecto es la misma. Derivar unas dimensiones aqui seria
reimplementar el redimensionado en el DTO.

Casos cubiertos: **M-01**, **M-03** de la matriz de la ficha. **M-02** —que la
clave no se filtre— depende de MinIO real y vive en
`tests/integration/test_acceso_publico_a_medios.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.media.domain.claves import clave_de_la_miniatura
from app.modules.media.infrastructure.models import MediaAsset
from app.modules.media.presentation.acceso import AccesoAMedios
from app.modules.media.presentation.schemas import MedioPublico
from app.shared.storage import (
    AccesoTemporal,
    ContenidoDeObjeto,
    ObjectStorage,
    ObjetoAlmacenado,
)

CLAVE_ORIGINAL = "medios/11111111-2222-3333-4444-555555555555/original.jpg"


class _AlmacenamientoQueFirmaLocalmente(ObjectStorage):
    """Doble que devuelve un enlace reconocible por clave, sin tocar la red.

    Es legitimo como doble aqui porque lo que se prueba es **que el DTO pida el
    enlace de la clave correcta**, no que la firma sea valida: eso ultimo se
    prueba contra MinIO real en `tests/contract/`.
    """

    def __init__(self) -> None:
        self.claves_pedidas: list[str] = []

    def acceso_temporal(self, clave: str, *, duracion: timedelta) -> AccesoTemporal:
        self.claves_pedidas.append(clave)
        return AccesoTemporal(
            url=f"https://almacenamiento.invalid/{clave}?X-Amz-Signature=abc",
            expira_en=datetime.now(UTC) + duracion,
        )

    def guardar(  # pragma: no cover - no se usa en estas pruebas
        self, *, clave: str, contenido: bytes, tipo_de_contenido: str
    ) -> ObjetoAlmacenado:
        raise NotImplementedError

    def obtener(self, clave: str) -> ContenidoDeObjeto:  # pragma: no cover - no se usa
        raise NotImplementedError

    def existe(self, clave: str) -> bool:  # pragma: no cover - no se usa
        raise NotImplementedError

    def eliminar(self, clave: str) -> None:  # pragma: no cover - no se usa
        raise NotImplementedError

    def comprobar_disponibilidad(self) -> None:
        """Este doble siempre esta disponible: `Task/017` no cambia estas pruebas."""
        return None


def _medio(*, con_alt: str | None = "Una portada") -> MediaAsset:
    return MediaAsset(
        id=uuid.uuid4(),
        object_key=CLAVE_ORIGINAL,
        alt_text=con_alt,
        width=1200,
        height=800,
    )


@pytest.fixture
def acceso() -> AccesoAMedios:
    return AccesoAMedios(
        almacenamiento=_AlmacenamientoQueFirmaLocalmente(),
        duracion=timedelta(seconds=900),
    )


class TestM01ElCampoExiste:
    """M-01: la miniatura se expone y apunta a la clave derivada."""

    def test_el_medio_publico_trae_un_enlace_de_miniatura(self, acceso: AccesoAMedios) -> None:
        publico = MedioPublico.de_modelo(_medio(), acceso)

        assert publico is not None
        assert publico.thumbnail_access_url is not None

    def test_el_enlace_apunta_a_la_clave_derivada_de_la_miniatura(
        self, acceso: AccesoAMedios
    ) -> None:
        publico = MedioPublico.de_modelo(_medio(), acceso)

        assert publico is not None
        assert publico.thumbnail_access_url is not None
        assert clave_de_la_miniatura(CLAVE_ORIGINAL) in publico.thumbnail_access_url

    def test_el_enlace_del_original_sigue_apuntando_al_original(
        self, acceso: AccesoAMedios
    ) -> None:
        """El campo nuevo no puede robarle su valor al que ya existia."""
        publico = MedioPublico.de_modelo(_medio(), acceso)

        assert publico is not None
        assert publico.access_url is not None
        assert publico.access_url.endswith("original.jpg?X-Amz-Signature=abc")
        assert publico.access_url != publico.thumbnail_access_url

    def test_es_un_enlace_firmado_y_por_tanto_temporal(self, acceso: AccesoAMedios) -> None:
        publico = MedioPublico.de_modelo(_medio(), acceso)

        assert publico is not None
        assert publico.thumbnail_access_url is not None
        assert "X-Amz-Signature" in publico.thumbnail_access_url


class TestM03NoRompeNadaDeLoQueYaHabia:
    """M-03: los campos anteriores se conservan; sin medio sigue siendo `None`."""

    def test_sin_medio_sigue_devolviendo_none(self, acceso: AccesoAMedios) -> None:
        assert MedioPublico.de_modelo(None, acceso) is None

    def test_los_campos_anteriores_se_conservan(self, acceso: AccesoAMedios) -> None:
        publico = MedioPublico.de_modelo(_medio(), acceso)

        assert publico is not None
        assert publico.alt_text == "Una portada"
        assert publico.width == 1200
        assert publico.height == 800

    def test_un_medio_sin_texto_alternativo_no_rompe(self, acceso: AccesoAMedios) -> None:
        publico = MedioPublico.de_modelo(_medio(con_alt=None), acceso)

        assert publico is not None
        assert publico.alt_text is None
        assert publico.thumbnail_access_url is not None

    def test_el_contrato_no_transporta_la_clave_como_dato(self, acceso: AccesoAMedios) -> None:
        """Ni `object_key` ni el nombre del campo aparecen en el JSON serializado."""
        publico = MedioPublico.de_modelo(_medio(), acceso)

        assert publico is not None
        serializado = publico.model_dump()

        assert "object_key" not in serializado
        assert set(serializado) == {
            "alt_text",
            "width",
            "height",
            "access_url",
            "thumbnail_access_url",
        }
