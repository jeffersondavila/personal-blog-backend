"""Construccion del documento `sitemap.xml` (`Task/016`, requisito E-05).

Esta mitad es **pura**: recibe un origen y una lista de entradas, y devuelve el
XML. No toca la base de datos, y por eso vive en `tests/unit/`. La otra mitad
—que solo aparezca contenido `published`, que es la **invariante 19** de
`data-model.md` y el requisito **E-08**— depende del filtro que ejecuta
PostgreSQL y se demuestra en `tests/integration/test_api_sitemap.py`
(BACKEND_TESTING_STRATEGY.md seccion 8.3: eso no se prueba con un doble).

Casos cubiertos aqui: **S-01**, **S-07**, **S-09**, **S-10** y **S-11** de la
matriz de la ficha.
"""

from __future__ import annotations

from datetime import UTC, datetime
from xml.etree import ElementTree

import pytest

from app.modules.sitemap.documento import construir_documento_de_sitemap
from app.modules.sitemap.tipos import RUTAS_ESTATICAS, EntradaDeSitemap

SITIO = "http://localhost:8081"

#: Espacio de nombres obligatorio del protocolo de sitemaps.
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _urls(documento: str) -> list[str]:
    raiz = ElementTree.fromstring(documento)  # noqa: S314 - XML generado por este mismo proyecto, no entrada de terceros
    return [nodo.text or "" for nodo in raiz.iterfind(f"{{{NS}}}url/{{{NS}}}loc")]


def _entradas(documento: str) -> list[tuple[str, str | None]]:
    raiz = ElementTree.fromstring(documento)  # noqa: S314 - XML generado por este mismo proyecto, no entrada de terceros
    resultado: list[tuple[str, str | None]] = []
    for url in raiz.iterfind(f"{{{NS}}}url"):
        loc = url.find(f"{{{NS}}}loc")
        lastmod = url.find(f"{{{NS}}}lastmod")
        direccion = (loc.text or "") if loc is not None else ""
        modificado = None if lastmod is None else lastmod.text
        resultado.append((direccion, modificado))
    return resultado


class TestFormaDelDocumento:
    """S-01 y S-07: el documento es un sitemap valido, no un XML cualquiera."""

    def test_es_xml_bien_formado_con_el_espacio_de_nombres_del_protocolo(self) -> None:
        documento = construir_documento_de_sitemap(base_url=SITIO, entradas=[])

        raiz = ElementTree.fromstring(documento)  # noqa: S314 - XML generado por este mismo proyecto, no entrada de terceros

        assert raiz.tag == f"{{{NS}}}urlset"

    def test_declara_la_codificacion(self) -> None:
        documento = construir_documento_de_sitemap(base_url=SITIO, entradas=[])

        assert documento.startswith("<?xml")
        assert "UTF-8" in documento.split("?>")[0]

    def test_sin_contenido_publicado_solo_contiene_las_rutas_estaticas(self) -> None:
        """S-01. Un sitio recien desplegado tiene paginas, aunque no tenga contenido."""
        documento = construir_documento_de_sitemap(base_url=SITIO, entradas=[])

        assert _urls(documento) == [f"{SITIO}{ruta}" for ruta in RUTAS_ESTATICAS]

    def test_las_siete_rutas_estaticas_son_exactamente_las_esperadas(self) -> None:
        assert RUTAS_ESTATICAS == (
            "/",
            "/quien-soy",
            "/articulos",
            "/reviews",
            "/videos",
            "/proyectos",
            "/contacto",
        )


class TestUrlAbsolutasDelSitio:
    """S-09: las URL son del sitio, y absolutas."""

    def test_toda_url_es_absoluta_y_cuelga_del_origen_configurado(self) -> None:
        documento = construir_documento_de_sitemap(
            base_url="https://ejemplo.test",
            entradas=[EntradaDeSitemap(ruta="/articulos/hola", ultima_modificacion=None)],
        )

        for url in _urls(documento):
            assert url.startswith("https://ejemplo.test/")

    def test_ninguna_url_contiene_el_origen_del_api(self) -> None:
        """El sitemap describe el sitio; que apuntara al API seria simplemente falso."""
        documento = construir_documento_de_sitemap(
            base_url="https://ejemplo.test",
            entradas=[EntradaDeSitemap(ruta="/articulos/hola", ultima_modificacion=None)],
        )

        assert "api." not in documento
        assert "/api/v1" not in documento

    def test_un_origen_con_barra_final_no_produce_barras_duplicadas(self) -> None:
        documento = construir_documento_de_sitemap(
            base_url="https://ejemplo.test/",
            entradas=[EntradaDeSitemap(ruta="/articulos/hola", ultima_modificacion=None)],
        )

        assert "https://ejemplo.test//" not in documento

    def test_la_raiz_no_pierde_su_barra(self) -> None:
        documento = construir_documento_de_sitemap(base_url=SITIO, entradas=[])

        assert f"{SITIO}/" in _urls(documento)


class TestLastmod:
    """`lastmod` sale de `published_at`, y solo cuando existe."""

    def test_una_entrada_con_fecha_declara_lastmod_en_formato_iso(self) -> None:
        documento = construir_documento_de_sitemap(
            base_url=SITIO,
            entradas=[
                EntradaDeSitemap(
                    ruta="/articulos/hola",
                    ultima_modificacion=datetime(2026, 3, 14, 15, 9, 26, tzinfo=UTC),
                )
            ],
        )

        assert ("http://localhost:8081/articulos/hola", "2026-03-14") in [
            (loc, None if mod is None else mod[:10]) for loc, mod in _entradas(documento)
        ]

    def test_una_entrada_sin_fecha_omite_lastmod_en_lugar_de_inventarla(self) -> None:
        documento = construir_documento_de_sitemap(
            base_url=SITIO,
            entradas=[EntradaDeSitemap(ruta="/articulos/hola", ultima_modificacion=None)],
        )

        entradas = dict(_entradas(documento))

        assert entradas["http://localhost:8081/articulos/hola"] is None

    def test_las_rutas_estaticas_no_declaran_lastmod(self) -> None:
        """No hay ningun dato que diga cuando cambio un listado. No se inventa."""
        documento = construir_documento_de_sitemap(base_url=SITIO, entradas=[])

        assert all(lastmod is None for _, lastmod in _entradas(documento))


class TestExclusiones:
    """S-10: lo que nunca puede aparecer."""

    @pytest.mark.parametrize(
        "prohibido",
        ["/buscar", "/admin", "/api/v1", "sitemap.xml", "/videos/"],
    )
    def test_no_aparecen_rutas_excluidas_en_un_documento_sin_contenido(
        self, prohibido: str
    ) -> None:
        documento = construir_documento_de_sitemap(base_url=SITIO, entradas=[])

        assert prohibido not in documento

    def test_el_listado_de_videos_aparece_pero_no_un_detalle_de_video(self) -> None:
        """No existe `/videos/:slug`: el contrato no tiene detalle de video."""
        urls = _urls(construir_documento_de_sitemap(base_url=SITIO, entradas=[]))

        assert f"{SITIO}/videos" in urls
        assert not any(url.startswith(f"{SITIO}/videos/") for url in urls)


class TestEscapeXml:
    """S-11: un slug con caracteres especiales no puede romper el documento."""

    @pytest.mark.parametrize("slug", ["a&b", "a<b", 'a"b', "a>b", "a'b"])
    def test_el_documento_sigue_siendo_bien_formado(self, slug: str) -> None:
        documento = construir_documento_de_sitemap(
            base_url=SITIO,
            entradas=[EntradaDeSitemap(ruta=f"/articulos/{slug}", ultima_modificacion=None)],
        )

        # Si el escape faltara, `fromstring` lanzaria en lugar de fallar una
        # asercion: es la comprobacion que importa.
        raiz = ElementTree.fromstring(documento)  # noqa: S314 - XML generado por este mismo proyecto, no entrada de terceros

        assert raiz is not None

    def test_el_ampersand_se_escapa_y_no_viaja_crudo(self) -> None:
        documento = construir_documento_de_sitemap(
            base_url=SITIO,
            entradas=[EntradaDeSitemap(ruta="/articulos/a&b", ultima_modificacion=None)],
        )

        assert "&amp;" in documento
        # Ningun `&` suelto: todos los que haya deben abrir una entidad.
        assert "&b" not in documento
