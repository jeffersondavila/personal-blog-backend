"""`alt_text` se exige **donde se usa** la imagen (`Task/012`).

De dónde sale esta obligación
-----------------------------

No de esta tarea. La asignan dos fuentes **anteriores** a `Task/012`:

`data-model.md` §4.1, tabla `media_assets`, fila `alt_text`:

> *accesibilidad (A-04). `Task/010` decidió no exigirlo al subir (D-010-N): se
> escribe al **usar** la imagen, no al cargarla, y el flujo B.4 no lo pide.
> **Exigirlo donde se usa es de `Task/012` y `Task/014`**.*

Ficha de `Task/010`, decisión **D-010-N**:

> *`data-model.md` dice «se escribe al usar la imagen, no al subirla». El flujo
> B.4 no lo pide y B.5 asocia después. **La accesibilidad se garantiza donde se
> usa el medio (`Task/012`, `Task/014`)**, no en el almacén.*

Dónde «se usa» una imagen, en la superficie de `Task/012`
----------------------------------------------------------

Cuando un contenido la referencia **y ese contenido es visible para el público**.
Antes de eso no hay ningún lector al que le falte el texto alternativo.

Eso da dos puntos de aplicación, y los decide el propio modelo, no una
preferencia:

**Los cuatro tipos publicables: al publicar.** Un borrador no lo ve nadie, y B.5
asocia la imagen *después* de cargarla; bloquear la asociación haría imposible
ese flujo.

**El perfil: al editar.** No tiene `status` —*«siempre existe y siempre está
visible»*, CONTENT_MODEL.md §2—, así que no hay un momento posterior en el que
exigirlo.

Lo que **no** hace esta tarea: exigirlo al cargar. Eso contradiría **D-010-N**,
que es una decisión aprobada.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.administracion import ADMIN, administrador_con_sesion, codigo_de_error
from tests.integration.datos import medio, perfil

pytestmark = pytest.mark.integration

#: Cuerpo **publicable** de cada tipo y el nombre de su campo de imagen.
TIPOS: list[tuple[str, str, str, dict[str, Any]]] = [
    (
        "articulo",
        f"{ADMIN}/posts",
        "cover_id",
        {"title": "Un titulo", "summary": "Resumen.", "content": "Cuerpo."},
    ),
    (
        "review",
        f"{ADMIN}/book-reviews",
        "cover_id",
        {
            "title": "Un titulo",
            "summary": "Resumen.",
            "content": "Cuerpo.",
            "book_title": "El libro",
            "book_author": "La autora",
            "rating": 4,
        },
    ),
    (
        "video",
        f"{ADMIN}/videos",
        "thumbnail_id",
        {
            "title": "Un titulo",
            "summary": "Resumen.",
            "provider": "youtube",
            "video_url": "https://example.invalid/v/1",
        },
    ),
    (
        "proyecto",
        f"{ADMIN}/projects",
        "cover_id",
        {"title": "Un titulo", "summary": "Resumen.", "content": "Cuerpo."},
    ),
]
IDS = [tipo[0] for tipo in TIPOS]


# --- Los cuatro tipos publicables: se exige AL PUBLICAR --------------------
@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_no_se_publica_un_contenido_cuya_imagen_no_tiene_texto_alternativo(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """Requisito A-04, exigido **donde se usa** la imagen."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-sin-alt/original.png", texto_alternativo=None)
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()
    creado = cliente_administrativo.post(ruta, json={**cuerpo, campo: str(imagen.id)}).json()

    respuesta = cliente_administrativo.post(f"{ruta}/{creado['id']}/publish")

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "cannot_publish_incomplete_draft"
    esperado = "thumbnail_alt_text" if campo == "thumbnail_id" else "cover_alt_text"
    assert esperado in respuesta.json()["error"]["details"]["campos"]


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_con_texto_alternativo_el_contenido_se_publica(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """Control del caso anterior: la imagen no es lo que impide publicar."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-con-alt/original.png", texto_alternativo="Un retrato")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()
    creado = cliente_administrativo.post(ruta, json={**cuerpo, campo: str(imagen.id)}).json()

    respuesta = cliente_administrativo.post(f"{ruta}/{creado['id']}/publish")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "published"


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_sin_imagen_no_se_exige_ningun_texto_alternativo(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """La portada sigue siendo **opcional**: ninguna fuente la exige."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    creado = cliente_administrativo.post(ruta, json=cuerpo).json()

    assert cliente_administrativo.post(f"{ruta}/{creado['id']}/publish").status_code == 200


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_un_borrador_si_puede_referenciar_una_imagen_sin_texto_alternativo(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """**D-010-N** se respeta: *«B.5 asocia después»*.

    Bloquear la asociación en el borrador haría imposible el flujo que la propia
    decisión de `Task/010` describe. Lo que se impide es **publicarlo**, que es
    donde la imagen pasa a tener lectores.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-borrador/original.png", texto_alternativo=None)
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.post(ruta, json={**cuerpo, campo: str(imagen.id)})

    assert respuesta.status_code == 201
    assert respuesta.json()["status"] == "draft"


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_un_texto_alternativo_en_blanco_cuenta_como_ausente(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """Un `alt` de espacios no describe nada: para un lector de pantalla es nada."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-blanco/original.png", texto_alternativo="   ")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()
    creado = cliente_administrativo.post(ruta, json={**cuerpo, campo: str(imagen.id)}).json()

    assert cliente_administrativo.post(f"{ruta}/{creado['id']}/publish").status_code == 409


# --- El perfil: se exige AL EDITAR, porque siempre es visible --------------
def test_el_perfil_no_admite_una_foto_sin_texto_alternativo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """El perfil **no tiene `status`**: no hay un «publicar» donde exigirlo después.

    CONTENT_MODEL.md §2: *«`Profile` no tiene estado ni fecha de publicación:
    siempre existe y siempre está visible»*. Asignar la foto **es** usarla.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil(nombre="Antiguo"))
    imagen = medio(clave="medios/perfil-sin-alt/original.png", texto_alternativo=None)
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(
        f"{ADMIN}/profile",
        json={"full_name": "Nuevo", "photo_id": str(imagen.id)},
    )

    assert respuesta.status_code == 422
    assert codigo_de_error(respuesta) == "media_without_alt_text"
    assert respuesta.json()["error"]["details"]["campo"] == "photo_id"


def test_el_perfil_admite_una_foto_con_texto_alternativo(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    imagen = medio(clave="medios/perfil-con-alt/original.png", texto_alternativo="Retrato")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(
        f"{ADMIN}/profile", json={"full_name": "Nuevo", "photo_id": str(imagen.id)}
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["photo"]["alt_text"] == "Retrato"


def test_el_perfil_sin_foto_no_exige_nada(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(f"{ADMIN}/profile", json={"full_name": "Nuevo"})

    assert respuesta.status_code == 200


def test_el_rechazo_del_perfil_no_deja_el_perfil_a_medias(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """Se comprueba **antes** de escribir, como el resto de referencias."""
    from sqlalchemy import select

    from app.modules.profile.infrastructure.models import Profile

    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil(nombre="Antiguo"))
    imagen = medio(clave="medios/perfil-rechazo/original.png", texto_alternativo=None)
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    cliente_administrativo.put(
        f"{ADMIN}/profile", json={"full_name": "Nuevo", "photo_id": str(imagen.id)}
    )

    assert sesion_de_pruebas.execute(select(Profile)).scalar_one().full_name == "Antiguo"


# --- «Se escribe al USAR la imagen»: set-on-first-use ----------------------
#
# Comprobar que el texto ya existe no es lo que dicen las fuentes. `data-model.md`
# §4.1 y **D-010-N** dicen que **se escribe al usar** la imagen, no al cargarla.
# Si el unico momento posible de escritura fuera la carga, la frase seria falsa y
# el administrador estaria obligado a anticipar el texto sin saber todavia en que
# contenido va a aparecer la imagen — que es exactamente lo que `Task/010`
# rechazo.
#
# Decision **D-012-Y**: el **primer uso** puede escribirlo, en la misma
# transaccion en la que se establece la referencia.


def _alt(campo: str) -> str:
    """Nombre del campo de texto alternativo que acompana a cada referencia."""
    return "thumbnail_alt_text" if campo == "thumbnail_id" else "cover_alt_text"


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_el_primer_uso_escribe_el_texto_alternativo_al_crear(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """El recorrido completo que exigen las fuentes: cargar sin texto, usarlo con texto.

    1. la imagen existe **sin** `alt_text`;
    2. se asocia a un borrador y se proporciona el texto **en ese uso**;
    3. queda persistido en `media_assets`;
    4. publicar prospera.
    """
    from app.modules.media.infrastructure.models import MediaAsset

    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-primer-uso/original.png", texto_alternativo=None)
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    creado = cliente_administrativo.post(
        ruta, json={**cuerpo, campo: str(imagen.id), _alt(campo): "Un retrato del autor"}
    )

    assert creado.status_code == 201, creado.text
    sesion_de_pruebas.expire_all()
    assert sesion_de_pruebas.get(MediaAsset, imagen.id).alt_text == "Un retrato del autor"  # type: ignore[union-attr]
    publicado = cliente_administrativo.post(f"{ruta}/{creado.json()['id']}/publish")
    assert publicado.status_code == 200


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_el_primer_uso_escribe_el_texto_alternativo_al_editar(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """B.5 asocia **despues** de cargar: la edicion es el momento natural."""
    from app.modules.media.infrastructure.models import MediaAsset

    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-editar/original.png", texto_alternativo=None)
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()
    creado = cliente_administrativo.post(ruta, json=cuerpo).json()

    editado = cliente_administrativo.put(
        f"{ruta}/{creado['id']}",
        json={
            **cuerpo,
            "slug": creado["slug"],
            campo: str(imagen.id),
            _alt(campo): "Diagrama de la arquitectura",
        },
    )

    assert editado.status_code == 200, editado.text
    sesion_de_pruebas.expire_all()
    assert sesion_de_pruebas.get(MediaAsset, imagen.id).alt_text == "Diagrama de la arquitectura"  # type: ignore[union-attr]
    assert cliente_administrativo.post(f"{ruta}/{creado['id']}/publish").status_code == 200


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_una_imagen_que_ya_tiene_texto_se_reutiliza_sin_reenviarlo(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """El texto es metadato **del asset**: quien lo reutiliza no lo repite."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-reutiliza/original.png", texto_alternativo="Retrato")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    creado = cliente_administrativo.post(ruta, json={**cuerpo, campo: str(imagen.id)})

    assert creado.status_code == 201
    assert cliente_administrativo.post(f"{ruta}/{creado.json()['id']}/publish").status_code == 200


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_reenviar_exactamente_el_mismo_texto_es_aceptable(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """Un panel que devuelve el texto que mostro no puede estar equivocandose."""
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-mismo/original.png", texto_alternativo="Retrato")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    creado = cliente_administrativo.post(
        ruta, json={**cuerpo, campo: str(imagen.id), _alt(campo): "Retrato"}
    )

    assert creado.status_code == 201


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_un_texto_distinto_no_sobrescribe_en_silencio(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """`alt_text` vive en el **asset**, no en la asociacion.

    Sobrescribirlo cambiaria el texto que ya usa **otro** contenido. Es el mismo
    riesgo que **D-010-J** describe para la deduplicacion —*"reutilizar en
    silencio haria que borrar un medio afectara a contenidos que nunca lo
    subieron"*— y ninguna fuente vigente define que debe ocurrir aqui.

    Ante una semantica no definida, la respuesta conservadora es **rechazar**:
    no cambia nada y una decision posterior puede relajarla. Sobrescribir seria
    irreversible.
    """
    from app.modules.media.infrastructure.models import MediaAsset

    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-distinto/original.png", texto_alternativo="Retrato")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.post(
        ruta, json={**cuerpo, campo: str(imagen.id), _alt(campo): "Otro texto"}
    )

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "alt_text_conflict"
    sesion_de_pruebas.expire_all()
    assert sesion_de_pruebas.get(MediaAsset, imagen.id).alt_text == "Retrato"  # type: ignore[union-attr]


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_un_texto_alternativo_sin_imagen_es_una_combinacion_invalida(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """Se rechaza en lugar de ignorarse.

    Un campo que no hace nada es una trampa: el panel creeria haber guardado un
    texto que no existe en ningun sitio. Misma postura que `extra="forbid"`.
    """
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)

    respuesta = cliente_administrativo.post(ruta, json={**cuerpo, _alt(campo): "Sin imagen"})

    assert respuesta.status_code == 422


@pytest.mark.parametrize(("nombre", "ruta", "campo", "cuerpo"), TIPOS, ids=IDS)
def test_un_rechazo_no_deja_el_texto_escrito_a_medias(
    cliente_administrativo: TestClient,
    sesion_de_pruebas: Session,
    nombre: str,
    ruta: str,
    campo: str,
    cuerpo: dict[str, Any],
) -> None:
    """La escritura del texto y la asociacion son **la misma transaccion**.

    Se provoca el fallo con una etiqueta desconocida, que se comprueba despues:
    si el texto se hubiera escrito fuera de la transaccion, quedaria persistido
    aunque la peticion entera fallara.
    """
    import uuid as _uuid

    from app.modules.media.infrastructure.models import MediaAsset

    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    imagen = medio(clave=f"medios/{nombre}-rollback/original.png", texto_alternativo=None)
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.post(
        ruta,
        json={
            **cuerpo,
            campo: str(imagen.id),
            _alt(campo): "Texto que no debe persistir",
            "tag_ids": [str(_uuid.uuid4())],
        },
    )

    assert respuesta.status_code == 422
    sesion_de_pruebas.expire_all()
    assert sesion_de_pruebas.get(MediaAsset, imagen.id).alt_text is None  # type: ignore[union-attr]


# --- El perfil tambien escribe en el primer uso ----------------------------
def test_el_perfil_escribe_el_texto_alternativo_en_el_primer_uso(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    """No obliga a borrar y volver a cargar la imagen."""
    from app.modules.media.infrastructure.models import MediaAsset

    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    imagen = medio(clave="medios/perfil-primer-uso/original.png", texto_alternativo=None)
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(
        f"{ADMIN}/profile",
        json={
            "full_name": "Jefferson Davila",
            "photo_id": str(imagen.id),
            "photo_alt_text": "Retrato del autor",
        },
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["photo"]["alt_text"] == "Retrato del autor"
    sesion_de_pruebas.expire_all()
    assert sesion_de_pruebas.get(MediaAsset, imagen.id).alt_text == "Retrato del autor"  # type: ignore[union-attr]


def test_el_perfil_no_sobrescribe_un_texto_distinto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    imagen = medio(clave="medios/perfil-distinto/original.png", texto_alternativo="Retrato")
    sesion_de_pruebas.add(imagen)
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(
        f"{ADMIN}/profile",
        json={
            "full_name": "Nuevo",
            "photo_id": str(imagen.id),
            "photo_alt_text": "Otro texto",
        },
    )

    assert respuesta.status_code == 409
    assert codigo_de_error(respuesta) == "alt_text_conflict"


def test_el_perfil_rechaza_un_texto_alternativo_sin_foto(
    cliente_administrativo: TestClient, sesion_de_pruebas: Session
) -> None:
    administrador_con_sesion(cliente_administrativo, sesion_de_pruebas)
    sesion_de_pruebas.add(perfil())
    sesion_de_pruebas.flush()

    respuesta = cliente_administrativo.put(
        f"{ADMIN}/profile", json={"full_name": "Nuevo", "photo_alt_text": "Sin foto"}
    )

    assert respuesta.status_code == 422


# --- La carga sigue sin exigirlo: D-010-N es una decisión aprobada ---------
def test_cargar_una_imagen_sin_texto_alternativo_sigue_permitido(
    cliente_administrativo_con_medios: TestClient, sesion_de_pruebas: Session
) -> None:
    """**D-010-N** no se toca.

    `Task/012` exige el texto alternativo **donde se usa** la imagen, que es lo
    que las fuentes le asignan. Exigirlo al cargar sería revertir una decisión
    aprobada de `Task/010`, y además obligaría a inventar un texto antes de saber
    en qué contenido va a aparecer la imagen.
    """
    from tests.imagenes import imagen as imagen_valida

    administrador_con_sesion(cliente_administrativo_con_medios, sesion_de_pruebas)

    respuesta = cliente_administrativo_con_medios.post(
        f"{ADMIN}/media",
        files={"archivo": ("foto.png", imagen_valida(ancho=32, alto=32), "image/png")},
    )

    assert respuesta.status_code == 201
    assert respuesta.json()["alt_text"] is None
