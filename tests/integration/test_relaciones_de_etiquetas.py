"""Relacion muchos a muchos con `Tag`, contra PostgreSQL real (matriz D).

La regla que estas pruebas protegen es la que mas dano haria si se implementara
mal: **eliminar una etiqueta desasocia contenido, nunca lo elimina**
(CONTENT_MODEL.md seccion 3.6, USER_FLOWS.md B.11). Una cascada mal orientada
borraria articulos al limpiar etiquetas, y no habria forma de recuperarlos.

Es tambien el caso tipico de comportamiento que solo el motor demuestra: la
cascada la ejecuta PostgreSQL, no el ORM.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.posts.infrastructure.models import Post
from app.modules.tags.infrastructure.models import Tag, post_tags

pytestmark = pytest.mark.integration


def _articulo(slug: str) -> Post:
    return Post(slug=slug, title=f"Articulo {slug}")


def _etiqueta(slug: str) -> Tag:
    return Tag(slug=slug, name=slug.capitalize())


# --- D-01 ------------------------------------------------------------------
def test_un_articulo_puede_llevar_varias_etiquetas(sesion_de_pruebas: Session) -> None:
    articulo = _articulo("con-etiquetas")
    articulo.tags = [_etiqueta("docker"), _etiqueta("postgresql")]
    sesion_de_pruebas.add(articulo)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.expire(articulo)

    assert sorted(etiqueta.slug for etiqueta in articulo.tags) == ["docker", "postgresql"]


def test_una_etiqueta_puede_estar_en_varios_articulos(sesion_de_pruebas: Session) -> None:
    etiqueta = _etiqueta("compartida")
    primero, segundo = _articulo("primero"), _articulo("segundo")
    primero.tags = [etiqueta]
    segundo.tags = [etiqueta]
    sesion_de_pruebas.add_all([primero, segundo])
    sesion_de_pruebas.flush()

    asociaciones = sesion_de_pruebas.execute(
        select(func.count()).select_from(post_tags).where(post_tags.c.tag_id == etiqueta.id)
    ).scalar_one()
    assert asociaciones == 2


# --- D-02 ------------------------------------------------------------------
def test_una_asociacion_duplicada_se_rechaza(sesion_de_pruebas: Session) -> None:
    """La clave primaria compuesta es lo que la rechaza.

    Se inserta por SQL directo porque el ORM deduplica la coleccion en memoria y
    nunca llegaria a enviar la segunda fila: lo que se comprueba aqui es la
    garantia de **la base**, no la del ORM.
    """
    articulo = _articulo("duplicado")
    etiqueta = _etiqueta("unica")
    articulo.tags = [etiqueta]
    sesion_de_pruebas.add(articulo)
    sesion_de_pruebas.flush()

    # La sentencia viaja al motor en el acto, asi que el rechazo llega aqui y no
    # en un `flush` posterior: el ORM no tiene nada pendiente que vaciar.
    with pytest.raises(IntegrityError):
        sesion_de_pruebas.execute(
            post_tags.insert().values(post_id=articulo.id, tag_id=etiqueta.id)
        )


# --- D-03 ------------------------------------------------------------------
def test_eliminar_una_etiqueta_no_elimina_el_contenido(sesion_de_pruebas: Session) -> None:
    """Invariante del producto. Si esto falla, borrar etiquetas destruye el blog."""
    articulo = _articulo("sobrevive")
    etiqueta = _etiqueta("efimera")
    articulo.tags = [etiqueta]
    sesion_de_pruebas.add(articulo)
    sesion_de_pruebas.flush()
    identificador = articulo.id

    sesion_de_pruebas.delete(etiqueta)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.expire_all()

    assert sesion_de_pruebas.get(Post, identificador) is not None
    asociaciones = sesion_de_pruebas.execute(
        select(func.count()).select_from(post_tags).where(post_tags.c.post_id == identificador)
    ).scalar_one()
    assert asociaciones == 0


# --- D-04 ------------------------------------------------------------------
def test_eliminar_contenido_no_elimina_la_etiqueta(sesion_de_pruebas: Session) -> None:
    """La simetria opuesta: una etiqueta sigue sirviendo a otro contenido."""
    articulo = _articulo("efimero")
    etiqueta = _etiqueta("permanente")
    articulo.tags = [etiqueta]
    sesion_de_pruebas.add(articulo)
    sesion_de_pruebas.flush()
    identificador = etiqueta.id

    sesion_de_pruebas.delete(articulo)
    sesion_de_pruebas.flush()
    sesion_de_pruebas.expire_all()

    assert sesion_de_pruebas.get(Tag, identificador) is not None


# --- D-05 ------------------------------------------------------------------
def test_asociar_una_etiqueta_inexistente_se_rechaza(sesion_de_pruebas: Session) -> None:
    articulo = _articulo("con-etiqueta-fantasma")
    sesion_de_pruebas.add(articulo)
    sesion_de_pruebas.flush()

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.execute(
            post_tags.insert().values(post_id=articulo.id, tag_id=uuid.uuid4())
        )


# --- D-06 ------------------------------------------------------------------
def test_dos_etiquetas_no_pueden_compartir_slug(sesion_de_pruebas: Session) -> None:
    sesion_de_pruebas.add(_etiqueta("repetida"))
    sesion_de_pruebas.flush()

    sesion_de_pruebas.add(_etiqueta("repetida"))

    with pytest.raises(IntegrityError):
        sesion_de_pruebas.flush()
