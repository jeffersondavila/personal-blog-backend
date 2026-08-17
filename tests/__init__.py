"""Arranque hermetico de la suite de pruebas de personal-blog-backend.

Este modulo se ejecuta **antes** que `conftest.py` y que cualquier modulo de
prueba, por ser el paquete que los contiene. Es el unico punto del harness
anterior a la collection, y por eso es aqui donde se aisla el proceso.

Por que hace falta un aislamiento a este nivel (`CERT-AUD-001`)
---------------------------------------------------------------

`Settings` declara `env_file=".env"`, que `pydantic-settings` resuelve **relativo
al directorio de trabajo**. Cualquier construccion de la configuracion que no
pase overrides explicitos lee, por tanto, el `.env` del desarrollador. Eso ocurre
en dos sitios que ninguna fixture puede interceptar:

1. **Durante la collection.** `app/main.py` construye la instancia ASGI al
   importarse (`app = create_app()`), como exige el arranque fail-fast del
   proyecto. Si algo del harness importa ese modulo mientras pytest colecciona,
   la aplicacion se construye con el `.env` que haya en el cwd. Las fixtures
   —incluidas las `autouse`— se ejecutan **despues** de la collection: llegan
   tarde por definicion.

2. **En la ruta de integracion.** `session_scope`, `get_session` y
   `alembic/env.py` resuelven la configuracion por si mismos con
   `get_settings()`, sin overrides.

`Task/005.6` cerro el primer frente —`settings_factory` construye con
`_env_file=None`— pero solo para las pruebas que usan esa fixture. Quedaban
abiertos los dos caminos de arriba: la certificacion final demostro que un `.env`
intruso cambiaba `app_name`, `log_level` y `app_debug` del proceso de pruebas.

Que se hace aqui
----------------

Las tres medidas son complementarias; ninguna sustituye a las otras:

1. **Se borra del entorno toda variable `BLOG_*` heredada**, para que la suite no
   dependa de lo que el desarrollador tenga exportado en su terminal.
2. **Se neutraliza el `.env` para todo el proceso de pruebas**, poniendo
   `env_file=None` en `model_config`. Es la unica medida que alcanza a la
   collection y a `get_settings()`.
3. **Se fija una `BLOG_DATABASE_URL` ficticia**, obligatoria para que la
   configuracion sea valida. Ninguna prueba unitaria se conecta a ella: las que
   necesitan PostgreSQL viven en `tests/integration/` y usan
   `PERSONAL_BLOG_TEST_DATABASE_URL`, que **no** lleva el prefijo `BLOG_` a
   proposito y sobrevive al paso 1.

El comportamiento de produccion no cambia: `model_config` se modifica en el
proceso que importa `tests`, y la aplicacion real sigue leyendo su `.env` como
siempre. La regresion vive en `tests/test_hermeticidad.py`.

Alcance de la garantia: el **harness oficial**. No se afirma que ningun codigo
Python imaginable pueda leer un `.env`; se afirma que arrancar y ejecutar esta
suite no lo hace.
"""

from __future__ import annotations

import os

#: URL ficticia, sintacticamente valida. No corresponde a ninguna base real.
FAKE_DATABASE_URL = "postgresql://usuario_de_prueba:clave_de_prueba@localhost:5432/base_de_prueba"


def _aislar_el_proceso_de_pruebas() -> None:
    """Deja el proceso con una configuracion controlada y sin dotenv.

    Se ejecuta al importar el paquete, es decir, antes de la collection y antes
    de cualquier import de `app.main`.
    """
    for nombre in list(os.environ):
        if nombre.upper().startswith("BLOG_"):
            del os.environ[nombre]

    # Import diferido: hacerlo dentro de la funcion mantiene el orden explicito
    # —primero limpiar el entorno, despues tocar la configuracion— y evita que el
    # modulo tenga efectos por el simple hecho de estar importado.
    from app.shared.configuration.settings import Settings

    # `model_config` es la superficie de configuracion publica de
    # `pydantic-settings` y se consulta en cada instanciacion, no al definir la
    # clase: ponerlo a `None` aqui basta para que ningun `Settings()` posterior
    # de este proceso busque un `.env`.
    Settings.model_config["env_file"] = None

    os.environ["BLOG_DATABASE_URL"] = FAKE_DATABASE_URL


_aislar_el_proceso_de_pruebas()

__all__ = ["FAKE_DATABASE_URL"]
