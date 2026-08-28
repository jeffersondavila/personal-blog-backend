"""Constructores de contenido para las pruebas de integracion de la API publica.

Todo lo que se crea aqui vive **dentro** de la sesion transaccional del harness
(`sesion_de_pruebas`), que revierte al terminar cada prueba. No se siembra nada
permanente, no se toca la base de desarrollo y no se versiona ningun dato real
del autor.

Los constructores existen para que cada prueba diga **solo lo que le importa**:
`articulo("uno", publicado_el=AYER)` se lee como el escenario que describe,
mientras que rellenar a mano las columnas obligatorias en cada prueba
escondería el caso detras del andamiaje.

**No definen fixtures**, a proposito: son funciones normales. El harness de
integracion exige que toda fixture derive del resolutor verificado
(`CERT-AUD-002`), y estas funciones no resuelven ningun destino — reciben la
sesion que la prueba ya obtuvo por el camino comprobado.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.book_reviews.domain import BookReviewStatus
from app.modules.book_reviews.infrastructure.models import BookReview
from app.modules.media.infrastructure.models import MediaAsset
from app.modules.posts.domain import PostStatus
from app.modules.posts.infrastructure.models import Post
from app.modules.profile.infrastructure.models import Profile, ProfileSocialLink
from app.modules.projects.domain import ProjectStatus, ProjectWorkStatus
from app.modules.projects.infrastructure.models import Project
from app.modules.tags.infrastructure.models import Tag
from app.modules.videos.domain import VideoStatus
from app.modules.videos.infrastructure.models import Video

#: Instantes fijos. Un reloj real haria que el orden dependiera de la velocidad
#: de la maquina, que es justo lo que las pruebas de orden no deben tolerar.
ANTIGUO = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
INTERMEDIO = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
RECIENTE = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _fecha_de(estado: str, publicado_el: datetime | None) -> datetime | None:
    """Resuelve `published_at` respetando el `CHECK` del esquema.

    `status = 'published'` exige `published_at` no nulo (invariante 1 de
    CONTENT_MODEL.md). Un borrador puede tener fecha o no tenerla: ambas cosas
    son legitimas, y las pruebas de visibilidad usan las dos.
    """
    if publicado_el is not None:
        return publicado_el
    return RECIENTE if estado == "published" else None


def articulo(
    slug: str,
    *,
    estado: PostStatus = PostStatus.PUBLISHED,
    titulo: str | None = None,
    resumen: str | None = None,
    contenido: str = "",
    publicado_el: datetime | None = None,
    destacado: bool = False,
    etiquetas: list[Tag] | None = None,
    portada: MediaAsset | None = None,
) -> Post:
    """Articulo listo para persistir."""
    creado = Post(
        slug=slug,
        title=titulo if titulo is not None else f"Articulo {slug}",
        summary=resumen,
        content=contenido,
        status=estado,
        published_at=_fecha_de(estado.value, publicado_el),
        featured=destacado,
        cover=portada,
    )
    creado.tags = etiquetas or []
    return creado


def review(
    slug: str,
    *,
    estado: BookReviewStatus = BookReviewStatus.PUBLISHED,
    titulo: str | None = None,
    resumen: str | None = None,
    contenido: str = "",
    publicado_el: datetime | None = None,
    destacado: bool = False,
    etiquetas: list[Tag] | None = None,
    titulo_del_libro: str | None = None,
    autor_del_libro: str | None = None,
    valoracion: int | None = None,
    enlace_externo: str | None = None,
) -> BookReview:
    """Review de libro lista para persistir."""
    creada = BookReview(
        slug=slug,
        title=titulo if titulo is not None else f"Review {slug}",
        summary=resumen,
        content=contenido,
        status=estado,
        published_at=_fecha_de(estado.value, publicado_el),
        featured=destacado,
        book_title=titulo_del_libro,
        book_author=autor_del_libro,
        rating=valoracion,
        external_link=enlace_externo,
    )
    creada.tags = etiquetas or []
    return creada


def video(
    slug: str,
    *,
    estado: VideoStatus = VideoStatus.PUBLISHED,
    titulo: str | None = None,
    resumen: str | None = None,
    publicado_el: datetime | None = None,
    destacado: bool = False,
    etiquetas: list[Tag] | None = None,
    proveedor: str | None = None,
    url: str | None = None,
    referencia_de_embed: str | None = None,
    duracion: int | None = None,
    miniatura: MediaAsset | None = None,
) -> Video:
    """Video listo para persistir."""
    creado = Video(
        slug=slug,
        title=titulo if titulo is not None else f"Video {slug}",
        summary=resumen,
        status=estado,
        published_at=_fecha_de(estado.value, publicado_el),
        featured=destacado,
        provider=proveedor,
        video_url=url,
        embed_reference=referencia_de_embed,
        duration_seconds=duracion,
        thumbnail=miniatura,
    )
    creado.tags = etiquetas or []
    return creado


def proyecto(
    slug: str,
    *,
    estado: ProjectStatus = ProjectStatus.PUBLISHED,
    titulo: str | None = None,
    resumen: str | None = None,
    contenido: str = "",
    publicado_el: datetime | None = None,
    destacado: bool = False,
    etiquetas: list[Tag] | None = None,
    marcha: ProjectWorkStatus = ProjectWorkStatus.ACTIVE,
    tecnologias: list[str] | None = None,
    repositorio: str | None = None,
    demo: str | None = None,
) -> Project:
    """Proyecto listo para persistir."""
    creado = Project(
        slug=slug,
        title=titulo if titulo is not None else f"Proyecto {slug}",
        summary=resumen,
        content=contenido,
        status=estado,
        published_at=_fecha_de(estado.value, publicado_el),
        featured=destacado,
        project_status=marcha,
        technologies=tecnologias if tecnologias is not None else [],
        repository_url=repositorio,
        demo_url=demo,
    )
    creado.tags = etiquetas or []
    return creado


def etiqueta(slug: str, *, nombre: str | None = None, descripcion: str | None = None) -> Tag:
    """Etiqueta lista para persistir."""
    return Tag(
        slug=slug,
        name=nombre if nombre is not None else slug.capitalize(),
        description=descripcion,
    )


def medio(
    *,
    clave: str,
    texto_alternativo: str | None = None,
    ancho: int | None = None,
    alto: int | None = None,
) -> MediaAsset:
    """Medio listo para persistir.

    `object_key` es unico por restriccion del esquema, asi que cada prueba debe
    pasar el suyo.
    """
    return MediaAsset(
        object_key=clave,
        original_filename="imagen.png",
        mime_type="image/png",
        size_bytes=1024,
        alt_text=texto_alternativo,
        width=ancho,
        height=alto,
    )


def perfil(
    *,
    nombre: str = "Nombre De Prueba",
    titular: str | None = None,
    biografia: str = "",
    correo: str | None = None,
    foto: MediaAsset | None = None,
    seo_title: str | None = None,
    seo_description: str | None = None,
    enlaces: list[tuple[str, str, int]] | None = None,
) -> Profile:
    """Perfil listo para persistir.

    `enlaces` recibe tripletas `(etiqueta, url, orden)`. Se pasan desordenadas a
    proposito en la prueba de orden: lo que debe ordenar es la consulta, no el
    orden en que se insertaron.
    """
    creado = Profile(
        full_name=nombre,
        headline=titular,
        biography=biografia,
        contact_email=correo,
        photo=foto,
        seo_title=seo_title,
        seo_description=seo_description,
    )
    creado.social_links = [
        ProfileSocialLink(label=texto, url=direccion, display_order=orden)
        for texto, direccion, orden in (enlaces or [])
    ]
    return creado
