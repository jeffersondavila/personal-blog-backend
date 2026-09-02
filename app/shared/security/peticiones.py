"""De quien viene una peticion (`Task/011`, decision D-011-J).

La direccion del cliente decide dos cosas: la **particion del limite de tasa** y
el campo `ip_address` de cada evento de auditoria. Equivocarse aqui tiene dos
consecuencias concretas y ninguna es teorica: un atacante podria falsificar una
direccion en cada intento —y disponer de infinitos cubos, es decir, de ningun
limite— y el historial se llenaria de direcciones inventadas.

Por que `X-Forwarded-For` no se cree por defecto
------------------------------------------------

Es una cabecera **que escribe el cliente**. En una peticion directa contra el
backend, `X-Forwarded-For: 1.2.3.4` es simplemente texto que alguien envio. Solo
tiene valor cuando hay un proxy de confianza delante que la **anade**, y aun
entonces solo son fiables los valores que ese proxy escribio: los de su izquierda
pudo ponerlos el cliente.

De ahi la regla: se cuenta **desde la derecha** tantas posiciones como proxies de
confianza se hayan declarado. Con `saltos_de_confianza = 0` —el valor por
defecto— la cabecera **se ignora entera**.

Cuantos saltos declarar en cada despliegue no se decide aqui: API Gateway es de
`Task/033` y el Traefik local, del runbook del entorno. Lo que si es de aqui es
que el valor por defecto sea el seguro.

Fail-closed
-----------

Cuando la direccion no puede establecerse con confianza —no hay par TCP, la
cabecera es mas corta de lo declarado, o el valor no es una direccion IP— se
devuelve una particion **compartida**. Todas esas peticiones caen en el mismo
cubo, asi que el limite se aplica de mas, nunca de menos.
"""

from __future__ import annotations

from ipaddress import ip_address as _analizar_ip
from typing import Final

#: Particion compartida para todo aquello cuya direccion no puede establecerse.
#: Es un literal y no una cadena vacia para que se lea como lo que es en un
#: volcado de la tabla o en un evento de auditoria.
DIRECCION_DESCONOCIDA: Final[str] = "unknown"


def direccion_del_cliente(
    *,
    direccion_del_par: str | None,
    cabecera_reenviada: str | None,
    saltos_de_confianza: int,
) -> str:
    """Resuelve la direccion del cliente segun la politica de confianza declarada.

    Con `saltos_de_confianza = 0` devuelve la direccion del par TCP y **no mira
    la cabecera**. Con `n > 0` toma el valor n-esimo empezando por la derecha de
    `X-Forwarded-For`, que es el que anadio el proxy de confianza mas externo.
    """
    if saltos_de_confianza <= 0:
        return _direccion_valida(direccion_del_par)

    if not cabecera_reenviada:
        return DIRECCION_DESCONOCIDA

    saltos = [fragmento.strip() for fragmento in cabecera_reenviada.split(",")]
    if len(saltos) < saltos_de_confianza:
        # La cadena tiene menos saltos de los declarados: el despliegue real no
        # coincide con la configuracion. Tomar el valor que haya seria creerle al
        # cliente exactamente en el caso en que no hay que hacerlo.
        return DIRECCION_DESCONOCIDA

    return _direccion_valida(saltos[-saltos_de_confianza])


def _direccion_valida(candidato: str | None) -> str:
    """Devuelve el candidato si es una direccion IP, o la particion compartida.

    La validacion no es cosmetica: la particion acaba en una columna
    `VARCHAR(45)`, y aceptar texto arbitrario convertiria una cabecera manipulada
    en un error de base de datos **dentro del endpoint de acceso**, ademas de
    abrir una via para llenar la tabla de filas basura.
    """
    if candidato is None:
        return DIRECCION_DESCONOCIDA
    limpio = candidato.strip()
    try:
        _analizar_ip(limpio)
    except ValueError:
        return DIRECCION_DESCONOCIDA
    return limpio
