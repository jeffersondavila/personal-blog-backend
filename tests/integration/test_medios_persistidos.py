"""Medios contra PostgreSQL **y** MinIO reales.

Lo que aqui se demuestra no se puede demostrar con dobles:

- Que la fila y los objetos existen de verdad **a la vez** despues de una subida.
- Que `object_key` es unico de verdad, porque es un indice de la base.
- Que un medio en uso no se borra, porque hay cinco claves foraneas con
  `ON DELETE RESTRICT` (invariante 12 de `data-model.md`).
- Que el error de borrado dice **donde** se usa la imagen (flujo B.5).

`BACKEND_TESTING_STRATEGY.md` seccion 8.3 lo exige explicitamente: PostgreSQL
real cuando el comportamiento depende de SQL, restricciones o transacciones.
**SQLite no se usa.**

El aislamiento viene de las dos guardas *fail-closed*: la base debe llevar su
marca (`Task/005.6`) y el bucket lo crea y lo destruye la propia suite
(`Task/010`).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.modules.media.application.eliminar_medio import EliminarMedio
from app.modules.media.application.subir_imagen import SubirImagen
from app.modules.media.domain.claves import clave_de_la_miniatura
from app.modules.media.domain.errores import MedioEnUsoError
from app.modules.media.infrastructure.models import MediaAsset
from app.modules.media.infrastructure.repositorio import RepositorioDeMediosSQL
from app.shared.errors.exceptions import ResourceNotFoundError
from app.shared.storage import ObjectStorage
from tests import imagenes
from tests.integration import datos

pytestmark = pytest.mark.integration


def _subir(
    sesion: Session, almacenamiento: ObjectStorage, *, contenido: bytes | None = None
) -> object:
    caso_de_uso = SubirImagen(
        almacenamiento=almacenamiento, repositorio=RepositorioDeMediosSQL(sesion)
    )
    return caso_de_uso(
        contenido=contenido if contenido is not None else imagenes.png(ancho=900, alto=600),
        nombre_original="portada.png",
    )


def _eliminar(sesion: Session, almacenamiento: ObjectStorage, identificador: uuid.UUID) -> None:
    EliminarMedio(almacenamiento=almacenamiento, repositorio=RepositorioDeMediosSQL(sesion))(
        identificador
    )


# --- P-01 ------------------------------------------------------------------
def test_una_subida_deja_los_dos_objetos_y_la_fila(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    resultado = _subir(sesion_de_pruebas, almacenamiento_minio)

    assert almacenamiento_minio.existe(resultado.object_key)  # type: ignore[attr-defined]
    assert almacenamiento_minio.existe(resultado.clave_de_la_miniatura)  # type: ignore[attr-defined]
    fila = sesion_de_pruebas.get(MediaAsset, resultado.id)  # type: ignore[attr-defined]
    assert fila is not None
    assert fila.object_key == resultado.object_key  # type: ignore[attr-defined]


# --- P-02 ------------------------------------------------------------------
def test_la_fila_guarda_los_metadatos_reales_de_la_imagen(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    contenido = imagenes.jpeg(ancho=640, alto=480)

    resultado = _subir(sesion_de_pruebas, almacenamiento_minio, contenido=contenido)

    fila = sesion_de_pruebas.get(MediaAsset, resultado.id)  # type: ignore[attr-defined]
    assert fila is not None
    assert fila.mime_type == "image/jpeg"
    assert (fila.width, fila.height) == (640, 480)
    assert fila.size_bytes == len(contenido)
    assert fila.original_filename == "portada.png"
    assert fila.alt_text is None


def test_el_objeto_almacenado_es_byte_a_byte_el_que_se_subio(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """La imagen original **no** se recodifica: se guarda tal cual llego."""
    contenido = imagenes.png(ancho=300, alto=200)

    resultado = _subir(sesion_de_pruebas, almacenamiento_minio, contenido=contenido)

    recuperado = almacenamiento_minio.obtener(resultado.object_key)  # type: ignore[attr-defined]
    assert recuperado.contenido == contenido
    assert recuperado.tipo_de_contenido == "image/png"


def test_la_miniatura_almacenada_es_un_webp_mas_pequeno(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    contenido = imagenes.png(ancho=1200, alto=800)

    resultado = _subir(sesion_de_pruebas, almacenamiento_minio, contenido=contenido)

    miniatura = almacenamiento_minio.obtener(resultado.clave_de_la_miniatura)  # type: ignore[attr-defined]
    assert miniatura.tipo_de_contenido == "image/webp"
    assert imagenes.formato(miniatura.contenido) == "WEBP"
    assert len(miniatura.contenido) < len(contenido)


# --- P-08 ------------------------------------------------------------------
def test_dos_subidas_identicas_no_se_deduplican(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """Decision D-010-J. Y la clave unica de la tabla lo haria imposible de otro
    modo: dos filas no pueden reclamar el mismo `object_key`."""
    contenido = imagenes.png(ancho=200, alto=200)

    primera = _subir(sesion_de_pruebas, almacenamiento_minio, contenido=contenido)
    segunda = _subir(sesion_de_pruebas, almacenamiento_minio, contenido=contenido)

    assert primera.id != segunda.id  # type: ignore[attr-defined]
    assert primera.object_key != segunda.object_key  # type: ignore[attr-defined]
    assert primera.checksum == segunda.checksum  # type: ignore[attr-defined]


# --- D-01 a D-04 -----------------------------------------------------------
@pytest.mark.parametrize(
    ("constructor", "campo", "tipo_esperado"),
    [
        ("articulo", "cover", "post"),
        ("review", "cover", "book_review"),
        ("proyecto", "cover", "project"),
    ],
)
def test_no_se_elimina_un_medio_usado_como_portada(
    sesion_de_pruebas: Session,
    almacenamiento_minio: ObjectStorage,
    constructor: str,
    campo: str,
    tipo_esperado: str,
) -> None:
    resultado = _subir(sesion_de_pruebas, almacenamiento_minio)
    medio = sesion_de_pruebas.get(MediaAsset, resultado.id)  # type: ignore[attr-defined]
    contenido = getattr(datos, constructor)("con-portada", titulo="Con portada")
    setattr(contenido, campo, medio)
    sesion_de_pruebas.add(contenido)
    sesion_de_pruebas.flush()

    with pytest.raises(MedioEnUsoError) as fallo:
        _eliminar(sesion_de_pruebas, almacenamiento_minio, resultado.id)  # type: ignore[attr-defined]

    assert [uso["tipo"] for uso in fallo.value.details["usos"]] == [tipo_esperado]
    assert fallo.value.details["usos"][0]["slug"] == "con-portada"
    # Ni la fila ni los objetos se han tocado.
    assert sesion_de_pruebas.get(MediaAsset, resultado.id) is not None  # type: ignore[attr-defined]
    assert almacenamiento_minio.existe(resultado.object_key)  # type: ignore[attr-defined]


def test_no_se_elimina_la_foto_del_perfil(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    resultado = _subir(sesion_de_pruebas, almacenamiento_minio)
    medio = sesion_de_pruebas.get(MediaAsset, resultado.id)  # type: ignore[attr-defined]
    sesion_de_pruebas.add(datos.perfil(foto=medio))
    sesion_de_pruebas.flush()

    with pytest.raises(MedioEnUsoError) as fallo:
        _eliminar(sesion_de_pruebas, almacenamiento_minio, resultado.id)  # type: ignore[attr-defined]

    assert fallo.value.details["usos"][0]["tipo"] == "profile"


def test_no_se_elimina_una_miniatura_de_video(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    resultado = _subir(sesion_de_pruebas, almacenamiento_minio)
    medio = sesion_de_pruebas.get(MediaAsset, resultado.id)  # type: ignore[attr-defined]
    creado = datos.video("con-miniatura")
    creado.thumbnail = medio
    sesion_de_pruebas.add(creado)
    sesion_de_pruebas.flush()

    with pytest.raises(MedioEnUsoError) as fallo:
        _eliminar(sesion_de_pruebas, almacenamiento_minio, resultado.id)  # type: ignore[attr-defined]

    assert fallo.value.details["usos"][0]["tipo"] == "video"


def test_el_error_enumera_todos_los_usos(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """Un mensaje que solo mencionara el primer uso obligaria al administrador a
    repetir el intento tantas veces como contenidos usen la imagen."""
    resultado = _subir(sesion_de_pruebas, almacenamiento_minio)
    medio = sesion_de_pruebas.get(MediaAsset, resultado.id)  # type: ignore[attr-defined]
    articulo = datos.articulo("usa-la-imagen", titulo="Articulo")
    articulo.cover = medio
    proyecto = datos.proyecto("tambien-la-usa", titulo="Proyecto")
    proyecto.cover = medio
    sesion_de_pruebas.add_all([articulo, proyecto])
    sesion_de_pruebas.flush()

    with pytest.raises(MedioEnUsoError) as fallo:
        _eliminar(sesion_de_pruebas, almacenamiento_minio, resultado.id)  # type: ignore[attr-defined]

    tipos = sorted(uso["tipo"] for uso in fallo.value.details["usos"])
    assert tipos == ["post", "project"]


# --- D-05 ------------------------------------------------------------------
def test_un_medio_sin_uso_se_elimina_por_completo(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """La proteccion es para lo que esta en uso; no convierte los medios en eternos."""
    resultado = _subir(sesion_de_pruebas, almacenamiento_minio)

    _eliminar(sesion_de_pruebas, almacenamiento_minio, resultado.id)  # type: ignore[attr-defined]

    assert sesion_de_pruebas.get(MediaAsset, resultado.id) is None  # type: ignore[attr-defined]
    assert not almacenamiento_minio.existe(resultado.object_key)  # type: ignore[attr-defined]
    assert not almacenamiento_minio.existe(resultado.clave_de_la_miniatura)  # type: ignore[attr-defined]


def test_la_miniatura_se_borra_aunque_no_este_persistida(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """Decision D-010-I: la clave de la miniatura **se deriva** de la del original.

    Es lo que hace innecesaria una columna nueva. Si la derivacion se rompiera,
    borrar un medio dejaria su miniatura huerfana para siempre, sin ninguna
    referencia que permitiera encontrarla.
    """
    resultado = _subir(sesion_de_pruebas, almacenamiento_minio)
    derivada = clave_de_la_miniatura(resultado.object_key)  # type: ignore[attr-defined]
    assert almacenamiento_minio.existe(derivada)

    _eliminar(sesion_de_pruebas, almacenamiento_minio, resultado.id)  # type: ignore[attr-defined]

    assert not almacenamiento_minio.existe(derivada)


# --- D-06 ------------------------------------------------------------------
def test_eliminar_un_medio_inexistente_es_un_recurso_no_encontrado(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    with pytest.raises(ResourceNotFoundError):
        _eliminar(sesion_de_pruebas, almacenamiento_minio, uuid.uuid4())


# --- Orden del borrado -----------------------------------------------------
def test_la_fila_se_borra_antes_que_los_objetos(
    sesion_de_pruebas: Session, almacenamiento_minio: ObjectStorage
) -> None:
    """Asimetria deliberada, la misma que en la subida (decision D-010-P).

    Si el borrado del objeto fallara despues de haber borrado la fila, queda
    basura en el bucket: molesto y recuperable. Al reves quedaria una fila
    apuntando a un objeto que no esta, es decir, una imagen rota en el blog
    publicado. Se elige el fallo tolerable.
    """
    resultado = _subir(sesion_de_pruebas, almacenamiento_minio)

    class _AlmacenamientoQueFallaAlBorrar:
        def __getattr__(self, nombre: str) -> object:
            return getattr(almacenamiento_minio, nombre)

        def eliminar(self, clave: str) -> None:
            raise RuntimeError("fallo simulado al borrar el objeto")

    caso_de_uso = EliminarMedio(
        almacenamiento=_AlmacenamientoQueFallaAlBorrar(),  # type: ignore[arg-type]
        repositorio=RepositorioDeMediosSQL(sesion_de_pruebas),
    )

    with pytest.raises(RuntimeError):
        caso_de_uso(resultado.id)  # type: ignore[attr-defined]

    # La fila ya no esta: se borro primero, y el fallo posterior no la resucita.
    assert sesion_de_pruebas.get(MediaAsset, resultado.id) is None  # type: ignore[attr-defined]


# --- El repositorio es tolerante con una fila que ya no esta ---------------
def test_eliminar_del_repositorio_una_fila_inexistente_no_falla(
    sesion_de_pruebas: Session,
) -> None:
    """`EliminarMedio` comprueba la existencia antes, asi que esta rama es una
    defensa, no el camino normal.

    Existe igualmente: entre la comprobacion y el borrado hay una ventana, y un
    repositorio que reventara al no encontrar la fila convertiria una carrera
    inocua —dos borrados del mismo medio— en un error. La operacion es
    idempotente por la misma razon que lo es la del almacenamiento (D-010-C).
    """
    RepositorioDeMediosSQL(sesion_de_pruebas).eliminar(uuid.uuid4())  # no debe lanzar
