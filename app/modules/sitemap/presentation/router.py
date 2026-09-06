"""Endpoint publico `GET /sitemap.xml` (requisito E-05).

**Fuera del prefijo `/api/v1`, a proposito**, con el mismo criterio que
`/health`: el prefijo versiona el contrato de datos que consume el frontend,
mientras que el sitemap es un artefacto del protocolo web que consume un
*crawler*. No debe cambiar de ruta cuando el contrato pase a `v2`.

**Endpoint delgado** (software-architecture.md seccion 3.5, regla 2): invoca la
consulta y serializa. No decide que es visible —eso lo expresa la consulta— ni
construye el XML —eso es `documento.py`—.

El origen del sitio llega por configuracion (`BLOG_PUBLIC_SITE_BASE_URL`) y no
de la peticion: `Host` lo escribe el cliente y, detras de un proxy o de API
Gateway, nombra el API y no el sitio.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.modules.sitemap.documento import TIPO_DE_CONTENIDO, construir_documento_de_sitemap
from app.modules.sitemap.infrastructure.queries import listar_entradas_publicadas
from app.shared.configuration import Settings, get_settings
from app.shared.database import get_session

router = APIRouter(tags=["sitemap"])


@router.get(
    "/sitemap.xml",
    summary="Sitemap del sitio publico",
    description=(
        "Enumera las paginas publicas y el contenido publicado. "
        "El contenido en borrador o archivado nunca aparece (requisito E-08)."
    ),
    response_class=Response,
    responses={200: {"content": {TIPO_DE_CONTENIDO: {}}, "description": "Sitemap XML."}},
)
def read_sitemap(
    sesion: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Devuelve el `sitemap.xml` del sitio publico."""
    documento = construir_documento_de_sitemap(
        base_url=settings.public_site_base_url,
        entradas=listar_entradas_publicadas(sesion),
    )
    return Response(content=documento, media_type=TIPO_DE_CONTENIDO)
