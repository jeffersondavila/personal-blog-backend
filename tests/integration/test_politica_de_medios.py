"""Politica de borrado de medios, contra PostgreSQL real (matriz E).

Invariante 5 de CONTENT_MODEL.md: **un `MediaAsset` en uso no puede
eliminarse**. `Task/008` la implementa donde no se puede esquivar —`ON DELETE
RESTRICT` en cada referencia— y `Task/010` construira encima la comprobacion
previa que explica **donde** se usa la imagen (USER_FLOWS.md B.5).

Las dos capas no se estorban: la de arriba da un mensaje util; la de abajo
garantiza que ningun camino, ni siquiera un `DELETE` escrito a mano, deja una
referencia rota.

`Task/008` **no** implementa `ObjectStorage`, ni MinIO, ni S3: aqui solo hay
filas de base de datos.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.media.infrastructure.models import MediaAsset
from app.modules.posts.infrastructure.models import Post
from app.modules.profile.infrastructure.models import Profile
from app.modules.videos.infrastructure.models import Video

pytestmark = pytest.mark.integration


def _medio(clave: str) -> MediaAsset:
    return MediaAsset(
        object_key=clave,
        original_filename="imagen.png",
        mime_type="image/png",
        size_bytes=1024,
    )


# --- E-01 ------------------------------------------------------------------
def test_dos_medios_no_pueden_compartir_clave_de_objeto(sesion_de_pruebas: Session) -> None:
    """Dos filas que reclamen el mismo objeto harian inutil la comprobacion de uso."""
    sesion_de_pruebas.add(_medio("medios/2026/repetida.png"))
    sesion_de_pruebas.flush()

    sesion_de_pruebas.add(_medio("medios/2026/repetida.png"))

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- E-02 ------------------------------------------------------------------
def test_no_se_puede_eliminar_un_medio_usado_como_portada(sesion_de_pruebas: Session) -> None:
    medio = _medio("medios/2026/portada.png")
    sesion_de_pruebas.add(medio)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.add(Post(slug="con-portada", title="Con portada", cover_id=medio.id))
    sesion_de_pruebas.flush()

    sesion_de_pruebas.delete(medio)

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


def test_no_se_puede_eliminar_un_medio_usado_como_miniatura(sesion_de_pruebas: Session) -> None:
    medio = _medio("medios/2026/miniatura.png")
    sesion_de_pruebas.add(medio)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.add(
        Video(
            slug="con-miniatura",
            title="Con miniatura",
            provider="proveedor-de-prueba",
            video_url="https://ejemplo.invalid/video",
            thumbnail_id=medio.id,
        )
    )
    sesion_de_pruebas.flush()

    sesion_de_pruebas.delete(medio)

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


def test_no_se_puede_eliminar_la_foto_del_perfil(sesion_de_pruebas: Session) -> None:
    medio = _medio("medios/2026/foto.png")
    sesion_de_pruebas.add(medio)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.add(Profile(full_name="Nombre De Prueba", photo_id=medio.id))
    sesion_de_pruebas.flush()

    sesion_de_pruebas.delete(medio)

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- E-03 ------------------------------------------------------------------
def test_un_medio_sin_referencias_si_se_elimina(sesion_de_pruebas: Session) -> None:
    """La restriccion protege lo que esta en uso; no convierte los medios en eternos."""
    medio = _medio("medios/2026/libre.png")
    sesion_de_pruebas.add(medio)
    sesion_de_pruebas.flush()
    identificador = medio.id

    sesion_de_pruebas.delete(medio)
    sesion_de_pruebas.flush()

    assert sesion_de_pruebas.get(MediaAsset, identificador) is None


# --- E-04 ------------------------------------------------------------------
def test_una_portada_inexistente_se_rechaza(sesion_de_pruebas: Session) -> None:
    sesion_de_pruebas.add(Post(slug="portada-fantasma", title="T", cover_id=uuid.uuid4()))

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


# --- E-05 ------------------------------------------------------------------
def test_un_contenido_puede_no_tener_portada(sesion_de_pruebas: Session) -> None:
    sesion_de_pruebas.add(Post(slug="sin-portada", title="T", cover_id=None))

    sesion_de_pruebas.flush()  # no debe lanzar


# --- E-06 ------------------------------------------------------------------
@pytest.mark.parametrize("tamano", [0, -1])
def test_un_medio_debe_tener_tamano_positivo(sesion_de_pruebas: Session, tamano: int) -> None:
    medio = _medio(f"medios/2026/tamano-{tamano}.png")
    medio.size_bytes = tamano
    sesion_de_pruebas.add(medio)

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


def test_las_dimensiones_declaradas_deben_ser_positivas(sesion_de_pruebas: Session) -> None:
    medio = _medio("medios/2026/dimensiones.png")
    medio.width = 0
    sesion_de_pruebas.add(medio)

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()


def test_la_base_guarda_la_clave_del_objeto_y_no_el_binario(sesion_de_pruebas: Session) -> None:
    """CONTENT_MODEL.md seccion 3.7 y la regla de persistencia de la ETAPA 03.

    Se comprueba sobre las columnas reales: ninguna es binaria y ninguna guarda
    una URL prefirmada, que caducaria.
    """
    columnas = {columna.name: columna.type for columna in MediaAsset.__table__.columns}

    assert "object_key" in columnas
    assert not any(tipo.__class__.__name__ in {"LargeBinary", "BLOB"} for tipo in columnas.values())
    assert not any(nombre.endswith("_url") for nombre in columnas)
