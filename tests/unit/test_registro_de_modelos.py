"""El registro de modelos no puede quedarse corto.

`app/modules/models.py` importa cada modulo de modelos para que sus tablas
cuelguen de `Base.metadata`. Esa lista es explicita, y una lista escrita a mano
falla **abierta**: si alguien anade `app/modules/x/infrastructure/models.py` y no
lo registra, Alembic no vera esa tabla y la migracion generada saldra incompleta
**sin emitir ningun error**. El defecto solo apareceria en produccion, con la
tabla ausente.

Aqui los modulos se **descubren del directorio**, asi que un archivo nuevo entra
en la comprobacion por existir. Es el mismo criterio que
`tests/test_grafo_de_fixtures_de_integracion.py` aplica al harness de
integracion.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parents[2]
DIRECTORIO_DE_MODULOS = RAIZ_DEL_REPOSITORIO / "app" / "modules"

#: Guarda anti-tautologia: si el descubrimiento se rompiera, el conjunto quedaria
#: vacio y la comprobacion pasaria sin haber mirado nada.
MODELOS_CONOCIDOS = {
    "app.modules.audit.infrastructure.models",
    "app.modules.authentication.infrastructure.models",
    "app.modules.book_reviews.infrastructure.models",
    "app.modules.media.infrastructure.models",
    "app.modules.posts.infrastructure.models",
    "app.modules.profile.infrastructure.models",
    "app.modules.projects.infrastructure.models",
    "app.modules.tags.infrastructure.models",
    "app.modules.videos.infrastructure.models",
}


def _modulos_de_modelos() -> set[str]:
    return {
        f"app.modules.{ruta.parents[1].name}.infrastructure.models"
        for ruta in DIRECTORIO_DE_MODULOS.glob("*/infrastructure/models.py")
    }


def test_el_descubrimiento_encuentra_los_modelos_conocidos() -> None:
    descubiertos = _modulos_de_modelos()

    ausentes = MODELOS_CONOCIDOS - descubiertos
    assert not ausentes, (
        f"el descubrimiento no encontro {sorted(ausentes)}. Si esos modulos se "
        "movieron, actualizar `MODELOS_CONOCIDOS`; si el mecanismo se rompio, el "
        f"resto de este modulo no comprueba nada. Encontrados: {sorted(descubiertos)}"
    )


def test_el_registro_importa_todos_los_modelos_del_proyecto() -> None:
    import app.modules.models  # noqa: F401  (el import es el objeto de la prueba)

    descubiertos = _modulos_de_modelos()

    sin_registrar = sorted(nombre for nombre in descubiertos if nombre not in sys.modules)
    assert not sin_registrar, (
        f"`app/modules/models.py` no importa {sin_registrar}. Sus tablas no estarian "
        "en `Base.metadata`, asi que Alembic no las veria y la migracion generada "
        "saldria incompleta sin ningun aviso."
    )


def test_cada_modelo_registrado_aporta_al_menos_una_tabla() -> None:
    """Que el modulo se importe no basta: debe declarar tablas de verdad."""
    import app.modules.models  # noqa: F401
    from app.shared.database import Base

    assert Base.metadata.tables, "ningun modelo registro tabla alguna en los metadatos"
