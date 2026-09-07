"""Caso de uso `SubirImagen`: orquestacion y compensacion.

Aqui se prueba lo que **ningun** componente por separado puede demostrar: que
entre PostgreSQL y el almacenamiento de objetos no hay transaccion, y que por
tanto un fallo a medio camino tiene que deshacerse a mano.

La matriz completa esta en la ficha, seccion G. Lo esencial:

```
validar  ->  miniatura  ->  guardar original  ->  guardar miniatura  ->  persistir
   |             |                 |                     |                   |
 falla        falla          falla: nada          falla: borrar        falla: borrar
 antes de     antes de       escrito, nada        el original          las dos claves
 tocar nada   tocar nada     en la base
```

Los dobles son de **frontera** —almacenamiento y repositorio—, que es
exactamente donde `BACKEND_TESTING_STRATEGY.md` seccion 10 los permite. El
comportamiento real de cada frontera se prueba en su sitio: el almacenamiento
contra MinIO en `tests/contract/`, la persistencia contra PostgreSQL en
`tests/integration/`. Lo que se afirma aqui es la **secuencia**, y una secuencia
no se puede observar contra servicios reales sin provocar fallos artificiales en
ellos.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Final

import pytest

from app.modules.media.application.repositorio import MedioParaRegistrar
from app.modules.media.application.subir_imagen import SubirImagen
from app.modules.media.domain.errores import ImagenInvalidaError
from app.shared.storage import (
    AccesoTemporal,
    ContenidoDeObjeto,
    FalloDelProveedorDeAlmacenamientoError,
    ObjectStorage,
    ObjetoAlmacenado,
)
from tests import imagenes

NOMBRE_ORIGINAL: Final = "mi foto de perfil.PNG"


class AlmacenamientoFalso(ObjectStorage):
    """Almacenamiento en memoria que puede fallar donde la prueba decida."""

    def __init__(
        self, *, falla_al_guardar: int | None = None, falla_al_eliminar: bool = False
    ) -> None:
        self.bucket = "bucket-falso"
        self.objetos: dict[str, bytes] = {}
        self.llamadas: list[str] = []
        self._falla_al_guardar = falla_al_guardar
        self._falla_al_eliminar = falla_al_eliminar
        self._guardados = 0

    def guardar(self, *, clave: str, contenido: bytes, tipo_de_contenido: str) -> ObjetoAlmacenado:
        self.llamadas.append(f"guardar:{clave}")
        self._guardados += 1
        if self._guardados == self._falla_al_guardar:
            raise FalloDelProveedorDeAlmacenamientoError("fallo simulado al guardar")
        self.objetos[clave] = contenido
        return ObjetoAlmacenado(
            clave=clave, tamano_bytes=len(contenido), tipo_de_contenido=tipo_de_contenido
        )

    def obtener(self, clave: str) -> ContenidoDeObjeto:  # pragma: no cover - no se usa aqui
        raise NotImplementedError

    def existe(self, clave: str) -> bool:
        return clave in self.objetos

    def eliminar(self, clave: str) -> None:
        self.llamadas.append(f"eliminar:{clave}")
        if self._falla_al_eliminar:
            raise FalloDelProveedorDeAlmacenamientoError("fallo simulado al eliminar")
        self.objetos.pop(clave, None)

    def acceso_temporal(
        self, clave: str, *, duracion: timedelta
    ) -> AccesoTemporal:  # pragma: no cover - no se usa aqui
        return AccesoTemporal(url=f"http://falso/{clave}", expira_en=datetime.now())

    def comprobar_disponibilidad(self) -> None:  # pragma: no cover - no se usa aqui
        """Este doble siempre esta disponible.

        **No** se anota en `llamadas`: estas pruebas afirman sobre la secuencia
        de operaciones de la subida, y una sonda que nunca se invoca aqui no
        puede aparecer en ella.
        """
        return None


class RepositorioFalso:
    """Repositorio en memoria que puede fallar al registrar."""

    def __init__(self, *, falla: bool = False) -> None:
        self.registrados: list[MedioParaRegistrar] = []
        self._falla = falla

    def registrar(self, medio: MedioParaRegistrar) -> uuid.UUID:
        if self._falla:
            raise RuntimeError("fallo simulado de la base de datos")
        self.registrados.append(medio)
        return uuid.uuid4()


def _subir(
    almacenamiento: AlmacenamientoFalso,
    repositorio: RepositorioFalso,
    *,
    contenido: bytes | None = None,
) -> object:
    caso_de_uso = SubirImagen(almacenamiento=almacenamiento, repositorio=repositorio)
    return caso_de_uso(
        contenido=contenido if contenido is not None else imagenes.png(ancho=200, alto=100),
        nombre_original=NOMBRE_ORIGINAL,
    )


# --- P-01 y P-02 -----------------------------------------------------------
def test_una_subida_correcta_deja_dos_objetos_y_una_fila() -> None:
    almacenamiento, repositorio = AlmacenamientoFalso(), RepositorioFalso()

    resultado = _subir(almacenamiento, repositorio)

    assert len(almacenamiento.objetos) == 2
    assert len(repositorio.registrados) == 1
    registrado = repositorio.registrados[0]
    assert registrado.object_key in almacenamiento.objetos
    assert resultado.object_key == registrado.object_key  # type: ignore[attr-defined]


def test_la_fila_guarda_metadatos_y_la_clave_pero_nunca_el_binario() -> None:
    """CONTENT_MODEL.md seccion 3.7: la base guarda metadatos y la clave del objeto."""
    almacenamiento, repositorio = AlmacenamientoFalso(), RepositorioFalso()
    contenido = imagenes.png(ancho=200, alto=100)

    _subir(almacenamiento, repositorio, contenido=contenido)

    registrado = repositorio.registrados[0]
    assert registrado.mime_type == "image/png"
    assert (registrado.width, registrado.height) == (200, 100)
    assert registrado.size_bytes == len(contenido)
    assert len(registrado.checksum) == 64
    assert registrado.original_filename == NOMBRE_ORIGINAL
    assert [valor for valor in asdict(registrado).values() if isinstance(valor, bytes)] == []


def test_ninguna_url_se_persiste() -> None:
    """Regla ya vigente de **D-08**: nunca se persiste una URL prefirmada."""
    almacenamiento, repositorio = AlmacenamientoFalso(), RepositorioFalso()

    _subir(almacenamiento, repositorio)

    textos = [v for v in asdict(repositorio.registrados[0]).values() if isinstance(v, str)]
    assert not any(texto.startswith(("http://", "https://")) for texto in textos)


# --- P-03 ------------------------------------------------------------------
def test_si_la_persistencia_falla_no_queda_ningun_objeto() -> None:
    """El caso que hace falta la compensacion: los objetos ya estan escritos.

    Sin esto, cada fallo de base de datos dejaria un original y una miniatura
    huerfanos en el bucket, sin ninguna fila que los mencione y por tanto sin
    forma de encontrarlos despues.
    """
    almacenamiento, repositorio = AlmacenamientoFalso(), RepositorioFalso(falla=True)

    with pytest.raises(RuntimeError, match="base de datos"):
        _subir(almacenamiento, repositorio)

    assert almacenamiento.objetos == {}


# --- P-04 ------------------------------------------------------------------
def test_si_falla_el_almacenamiento_del_original_no_hay_fila() -> None:
    almacenamiento = AlmacenamientoFalso(falla_al_guardar=1)
    repositorio = RepositorioFalso()

    with pytest.raises(FalloDelProveedorDeAlmacenamientoError):
        _subir(almacenamiento, repositorio)

    assert repositorio.registrados == []
    assert almacenamiento.objetos == {}


# --- P-05 ------------------------------------------------------------------
def test_si_falla_la_miniatura_se_elimina_el_original() -> None:
    """Un medio con original y sin miniatura seria un estado que nadie contempla."""
    almacenamiento = AlmacenamientoFalso(falla_al_guardar=2)
    repositorio = RepositorioFalso()

    with pytest.raises(FalloDelProveedorDeAlmacenamientoError):
        _subir(almacenamiento, repositorio)

    assert almacenamiento.objetos == {}
    assert repositorio.registrados == []
    assert any(llamada.startswith("eliminar:") for llamada in almacenamiento.llamadas)


# --- P-06 ------------------------------------------------------------------
def test_si_la_compensacion_tambien_falla_se_propaga_el_error_original() -> None:
    """El segundo fallo no puede tapar al primero.

    Quien recibe la excepcion necesita saber que fallo **la base de datos**. Si
    se propagara el fallo de la limpieza, el diagnostico apuntaria al
    almacenamiento y la causa real desapareceria.
    """
    almacenamiento = AlmacenamientoFalso(falla_al_eliminar=True)
    repositorio = RepositorioFalso(falla=True)

    with pytest.raises(RuntimeError, match="base de datos"):
        _subir(almacenamiento, repositorio)


def test_el_fallo_de_la_compensacion_se_registra(caplog: pytest.LogCaptureFixture) -> None:
    """Que no se propague no significa que se oculte: queda en el log.

    Es la unica pista de que hay basura en el bucket, asi que perderla
    convertiria un incidente diagnosticable en uno invisible.
    """
    almacenamiento = AlmacenamientoFalso(falla_al_eliminar=True)
    repositorio = RepositorioFalso(falla=True)

    with caplog.at_level("ERROR"), pytest.raises(RuntimeError):
        _subir(almacenamiento, repositorio)

    assert any("compensa" in registro.getMessage().lower() for registro in caplog.records)


# --- P-07 ------------------------------------------------------------------
def test_una_imagen_invalida_no_llega_a_tocar_el_almacenamiento() -> None:
    """Validar primero no es solo eficiencia: evita escribir basura que despues
    habria que compensar."""
    almacenamiento, repositorio = AlmacenamientoFalso(), RepositorioFalso()

    with pytest.raises(ImagenInvalidaError):
        _subir(almacenamiento, repositorio, contenido=b"no soy una imagen")

    assert almacenamiento.llamadas == []
    assert repositorio.registrados == []


# --- P-08 ------------------------------------------------------------------
def test_subir_dos_veces_el_mismo_archivo_crea_dos_medios_distintos() -> None:
    """Decision D-010-J: se calcula el checksum, pero **no** se deduplica.

    Reutilizar en silencio el primer medio haria que borrarlo afectara a
    contenidos que nunca lo subieron. Detectar duplicados y presentarlos al
    administrador es de `Task/012`.
    """
    almacenamiento, repositorio = AlmacenamientoFalso(), RepositorioFalso()
    contenido = imagenes.png(ancho=200, alto=100)

    _subir(almacenamiento, repositorio, contenido=contenido)
    _subir(almacenamiento, repositorio, contenido=contenido)

    claves = [medio.object_key for medio in repositorio.registrados]
    assert len(claves) == 2
    assert claves[0] != claves[1]
    assert repositorio.registrados[0].checksum == repositorio.registrados[1].checksum
    assert len(almacenamiento.objetos) == 4


# --- Orden de las operaciones ---------------------------------------------
def test_el_original_se_guarda_antes_que_la_miniatura() -> None:
    """El orden es parte de la decision D-010-P y de la compensacion que se
    deriva de ella; fijarlo evita que un refactor lo invierta sin querer."""
    almacenamiento, repositorio = AlmacenamientoFalso(), RepositorioFalso()

    _subir(almacenamiento, repositorio)

    guardados = [c for c in almacenamiento.llamadas if c.startswith("guardar:")]
    assert guardados[0].endswith("/original.png")
    assert guardados[1].endswith("/thumbnail.webp")
