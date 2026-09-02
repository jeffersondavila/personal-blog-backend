"""Transporte de la credencial de sesion: la cookie (`Task/011`, D-011-B).

Un unico punto decide los atributos de la cookie, tanto al emitirla como al
borrarla. No es una comodidad: **el navegador solo sustituye o borra una cookie
si `Name`, `Domain` y `Path` coinciden**, asi que emitir con un `Path` y borrar
con otro deja la sesion instalada en el navegador aunque el servidor la haya
revocado.

Por que estos atributos
-----------------------

- **`HttpOnly`, siempre.** Es la razon entera de elegir cookie en lugar de
  `localStorage`: la credencial no es legible por JavaScript, asi que un XSS no
  puede exfiltrarla. (Puede seguir actuando en nombre del usuario mientras la
  pagina este abierta; eso no lo arregla ningun mecanismo de transporte.)
- **`Secure` por politica.** Verdadero por defecto y **obligatorio** en
  produccion, donde el proceso ni siquiera arranca sin el. Se puede apagar en
  local, que sirve por HTTP, y esa es la unica situacion en que se apaga.
- **`SameSite=Lax`.** La topologia elegida (D-011-A) pone sitio y API bajo el
  mismo dominio registrable, asi que la peticion del panel es *same-site* y la
  cookie **si viaja**, tambien en `POST`. Lo que `Lax` bloquea es exactamente lo
  que interesa bloquear: el `POST` forjado desde un sitio de terceros.
  `SameSite=None` seria necesario con dominios separados, y volveria la cookie de
  terceros —bloqueada por Safari y en retirada en Chrome—.
- **`Path` = prefijo administrativo.** La cookie no se envia a los endpoints
  publicos. Es higiene de exposicion, **no** una frontera de seguridad: quien
  aplica `Path` es el navegador.
- **Sin `Domain`** → cookie *host-only*. Un `Domain` la compartiria con todos los
  subdominios, incluidos los que no existen todavia.
"""

from __future__ import annotations

from typing import Final, Literal

from fastapi import Response

from app.shared.configuration import Settings

#: Nombre de la cookie de sesion. Es una **constante y no configuracion**,
#: y la razon es concreta: FastAPI construye el esquema de seguridad de
#: OpenAPI al definir las rutas, con el nombre que se le da en ese momento.
#: Si el nombre viniera de una variable de entorno, un despliegue que la
#: cambiara publicaria una especificacion que **declara una cookie distinta
#: de la que el servidor usa** — es decir, OpenAPI mentiria. Nada pide poder
#: renombrarla, asi que la variable se retira en lugar de aceptar esa
#: incoherencia (§36: no se anade configuracion que la arquitectura no
#: necesita).
NOMBRE_DE_LA_COOKIE: Final[str] = "blog_admin_session"

#: `Lax` y no `Strict`: con `Strict`, llegar al panel desde un enlace externo no
#: enviaria la cookie y el propietario veria una sesion cerrada que en realidad
#: sigue abierta. `Lax` ya bloquea el envio en peticiones *cross-site* que
#: cambian estado, que es la propiedad de la que depende la defensa CSRF.
SAMESITE: Final[Literal["lax"]] = "lax"


def instalar_credencial(respuesta: Response, *, credencial: str, settings: Settings) -> None:
    """Entrega la credencial de sesion al navegador.

    `max_age` acompana a la expiracion del servidor para que el navegador deje de
    enviar una credencial que ya no vale. **La autoridad sigue siendo el
    servidor**: un navegador que ignorara `max_age` no ganaria nada, porque la
    sesion caducada no resuelve a nadie en la base de datos.
    """
    respuesta.set_cookie(
        key=NOMBRE_DE_LA_COOKIE,
        value=credencial,
        max_age=settings.auth_session_ttl_seconds,
        path=settings.auth_cookie_path,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=SAMESITE,
    )


def retirar_credencial(respuesta: Response, *, settings: Settings) -> None:
    """Borra la cookie del navegador al cerrar sesion.

    Es la **mitad cosmetica** del cierre de sesion. La mitad que importa es la
    revocacion en el servidor: sin ella, una cookie copiada antes del borrado
    seguiria autenticando. Con ella, borrarla es solo cortesia hacia el
    navegador.

    Los atributos deben coincidir con los de emision o el navegador no la
    encuentra y se queda con la anterior.
    """
    respuesta.delete_cookie(
        key=NOMBRE_DE_LA_COOKIE,
        path=settings.auth_cookie_path,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=SAMESITE,
    )
