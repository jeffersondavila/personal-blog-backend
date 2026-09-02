"""Politica de `Origin` de las peticiones administrativas (`Task/011`, D-011-K).

Es la **segunda capa** de la defensa contra CSRF, y existe precisamente porque
decir *"`SameSite` ya lo resuelve"* seria apoyar toda la proteccion en que el
navegador se comporte como se espera.

Las dos capas, y que cubre cada una
------------------------------------

1. **`SameSite=Lax`** hace que el navegador **no envie** la cookie de sesion en
   una peticion *cross-site* que cambie estado. Es la que evita el ataque
   clasico: un formulario en `evil.invalid` que hace `POST` contra el API.
2. **Esta comprobacion** no confia en el navegador: mira de donde **dice** venir
   la peticion y la rechaza si no esta en la lista explicita. Un navegador con
   una implementacion defectuosa de `SameSite`, o una version antigua, seguiria
   topandose con ella.

Por que no hay un *token* CSRF sincronizado
--------------------------------------------

Seria una tercera capa cuyo unico caso adicional —un navegador que envie cookies
*same-site* pero omita `Origin` en un `POST`— no existe en ningun navegador
vigente. Anadirlo tendria coste real en el panel y en cada endpoint de
`Task/012`, a cambio de cubrir un escenario que nadie puede producir. `Task/018`
puede endurecer si aparece un motivo.

Que **no** cubre esta capa, dicho claramente
---------------------------------------------

Una peticion **sin** `Origin` pasa. No es un agujero: un ataque de falsificacion
necesita el navegador de la victima y su cookie ambiente, y todo navegador actual
envia `Origin` en los metodos que cambian estado. Quien no es un navegador tendria
que **poseer** la credencial para llegar a algo — y entonces el CSRF ya no es el
problema. Rechazar esas peticiones romperia cualquier automatizacion legitima sin
cerrar nada.
"""

from __future__ import annotations

from typing import Final

#: Metodos en los que se comprueba el origen.
#:
#: `GET`, `HEAD` y `OPTIONS` quedan fuera **a proposito**: un CSRF que solo
#: consiga provocar una lectura no consigue nada, porque la respuesta no es
#: legible *cross-origin* sin que el servidor lo autorice con CORS. Incluir
#: `OPTIONS` ademas romperia la comprobacion previa que el navegador envia —sin
#: credenciales— antes de la peticion real.
METODOS_QUE_CAMBIAN_ESTADO: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def origen_permitido(*, metodo: str, origen: str | None, permitidos: tuple[str, ...]) -> bool:
    """Decide si una peticion administrativa puede ejecutarse desde ese origen.

    La comparacion es **exacta**. No se compara por prefijo ni por sufijo, y esa
    es una diferencia con consecuencias: `https://example.com.evil.invalid`
    contiene el origen permitido como subcadena, asi que una comprobacion
    perezosa con `in` o `startswith` la aceptaria.

    Con la lista **vacia** se rechaza cualquier origen. Es *fail-closed* a
    proposito: no existe un origen por defecto seguro, y suponer uno seria
    inventarse la configuracion de seguridad de otro.
    """
    if metodo.upper() not in METODOS_QUE_CAMBIAN_ESTADO:
        return True
    if origen is None:
        return True
    return origen in permitidos
