"""Capacidades transversales de seguridad.

`software-architecture.md` seccion 3.4 asigna a este paquete el **hash de
contrasenas**, las **dependencias de autorizacion** y las **cabeceras de
seguridad**.

Que vive aqui y que no (precision de `Task/011`, decision D-011-O)
------------------------------------------------------------------

Aqui viven las **primitivas transversales**: no conocen administradores, ni
sesiones, ni ningun modulo de negocio.

La dependencia `require_administrator` **no** vive aqui, y no es un descuido:
resolver un administrador exige consultar sesiones y administradores, que son
del modulo `authentication`. Colocarla en `shared` obligaria a que `shared`
importara un modulo de negocio, que es justo lo que la regla de dependencias
prohibe (`presentation -> application -> domain <- infrastructure`, y `shared`
por debajo de todos). Vive, por tanto, en
`app/modules/authentication/presentation/`, que es su duenno natural, y se
exporta como interfaz publica del modulo para que `Task/012` la reutilice.

Las **cabeceras de seguridad** siguen siendo de `Task/018`.
"""

from app.shared.security.contrasenas import (
    PARAMETROS_DE_ARGON2,
    contrasena_valida,
    hash_de_contrasena,
    necesita_rehash,
    verificacion_senuelo,
)
from app.shared.security.origen import METODOS_QUE_CAMBIAN_ESTADO, origen_permitido
from app.shared.security.peticiones import DIRECCION_DESCONOCIDA, direccion_del_cliente

__all__ = [
    "DIRECCION_DESCONOCIDA",
    "METODOS_QUE_CAMBIAN_ESTADO",
    "PARAMETROS_DE_ARGON2",
    "contrasena_valida",
    "direccion_del_cliente",
    "hash_de_contrasena",
    "necesita_rehash",
    "origen_permitido",
    "verificacion_senuelo",
]
