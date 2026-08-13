"""Suite de pruebas de personal-blog-backend.

Este modulo se ejecuta **antes** que `conftest.py` y que cualquier modulo de
prueba, por ser el paquete que los contiene. Se aprovecha para dejar en el
entorno una configuracion minima valida.

Hace falta porque `app.main` construye la instancia ASGI al importarse y la
configuracion se valida en ese momento: sin `BLOG_DATABASE_URL` el import
falla, que es justo el comportamiento fail-fast que el proyecto exige (T-01) y
que `tests/test_configuration.py` comprueba de forma explicita.

El valor es ficticio y **ninguna prueba unitaria se conecta a el**: las que
necesitan una base de datos real viven en `tests/integration/` y usan
`PERSONAL_BLOG_TEST_DATABASE_URL`.
"""

from __future__ import annotations

import os

#: URL ficticia, sintacticamente valida. No corresponde a ninguna base real.
FAKE_DATABASE_URL = "postgresql://usuario_de_prueba:clave_de_prueba@localhost:5432/base_de_prueba"

os.environ.setdefault("BLOG_DATABASE_URL", FAKE_DATABASE_URL)

__all__ = ["FAKE_DATABASE_URL"]
