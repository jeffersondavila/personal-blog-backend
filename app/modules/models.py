"""Registro unico de los modelos ORM del proyecto.

Importar este modulo deja **todas** las tablas del blog colgando de
`app.shared.database.Base.metadata`. Lo necesitan Alembic —para comparar el
esquema con los metadatos— y cualquier prueba que inspeccione el modelo
completo.

Por que no vive en `app/modules/__init__.py`
--------------------------------------------

Porque importar un submodulo ejecuta el `__init__` de su paquete. Si los modelos
se importaran ahi, un `import app.modules.posts.domain` cargaria SQLAlchemy y el
esquema entero, y el dominio dejaria de ser Python plano (ADR-004). La regresion
esta en `tests/unit/test_independencia_del_dominio.py`.

Por que la lista es explicita y aun asi no puede quedarse corta
---------------------------------------------------------------

Una lista escrita a mano falla **abierta**: quien anada un modulo nuevo y no lo
registre aqui haria que Alembic no viera su tabla, y la migracion generada
saldria incompleta **sin ningun error**. La guarda es
`tests/unit/test_registro_de_modelos.py`, que **descubre del directorio** todos
los `app/modules/*/infrastructure/models.py` y exige que este modulo los importe
todos. Un archivo nuevo entra en la comprobacion por el hecho de existir.
"""

from __future__ import annotations

from app.modules.audit.infrastructure import models as audit_models
from app.modules.authentication.infrastructure import models as authentication_models
from app.modules.book_reviews.infrastructure import models as book_review_models
from app.modules.media.infrastructure import models as media_models
from app.modules.posts.infrastructure import models as post_models
from app.modules.profile.infrastructure import models as profile_models
from app.modules.projects.infrastructure import models as project_models
from app.modules.tags.infrastructure import models as tag_models
from app.modules.videos.infrastructure import models as video_models

__all__ = [
    "audit_models",
    "authentication_models",
    "book_review_models",
    "media_models",
    "post_models",
    "profile_models",
    "project_models",
    "tag_models",
    "video_models",
]
