"""Errores del almacenamiento de objetos.

Jerarquia deliberadamente **minima**. Se distinguen exactamente los tres casos
sobre los que el codigo llamante toma una decision distinta:

- **`ObjetoNoEncontradoError`.** Lo tratan la compensacion de una subida y la
  lectura de un medio: un objeto ausente no es un fallo del proveedor.
- **`ConfiguracionDeAlmacenamientoInvalidaError`.** Lo trata el arranque: se
  lanza al **construir** el adaptador, antes de que exista cliente alguno
  (arranque fail-fast, requisito T-01).
- **`FalloDelProveedorDeAlmacenamientoError`.** Todo lo demas que venga del SDK.

Un cuarto error para "operacion no permitida" se evaluo y se descarto: hoy
**nada** ramifica sobre el. Un `403` del proveedor llega como fallo del
proveedor conservando su codigo de operacion, que es lo que hace falta para
diagnosticarlo. Crear una clase por cada codigo posible del SDK seria mapear el
SDK en lugar de modelar el dominio.

Reglas de no filtracion (requisitos S-07 y S-08)
-----------------------------------------------

- **Nunca** se incrusta la clave de acceso, el secreto ni la URL firmada en el
  mensaje. Un error acaba en un log y un log acaba en un sistema de
  observabilidad.
- **Nunca** se propaga la excepcion del SDK hacia arriba: se envuelve. El
  dominio no conoce `botocore`, y su cadena de excepciones lleva nombres de
  clase y detalles internos.
- La excepcion original se conserva en `__cause__` para el diagnostico local,
  que va al log, no al cliente. La traduccion a HTTP sigue ocurriendo en
  `app.shared.errors.handlers`, que ya garantiza que nada interno sale.

Estos errores **no** heredan de `ApplicationError`: no son errores de negocio con
un codigo HTTP asociado. Que un objeto falte en el almacen no es un `404` para
el visitante, es una inconsistencia interna. Convertirlos en respuesta es
decision del caso de uso que los recibe, no del adaptador.
"""

from __future__ import annotations


# `N818` pide el sufijo `Error` en ingles. El proyecto nombra en espanol, donde
# el sustantivo va delante: `ErrorDeAlmacenamiento` **es** "storage error". Las
# subclases si terminan en `Error`.
class ErrorDeAlmacenamiento(RuntimeError):  # noqa: N818
    """Raiz de los fallos del almacenamiento de objetos."""


class ObjetoNoEncontradoError(ErrorDeAlmacenamiento):
    """La clave solicitada no existe en el bucket."""


class ConfiguracionDeAlmacenamientoInvalidaError(ErrorDeAlmacenamiento):
    """La configuracion del adaptador es invalida o esta incompleta.

    Se lanza al **construir** el adaptador, no al usarlo: un destino mal
    configurado debe romper el arranque y no la primera subida.
    """


class FalloDelProveedorDeAlmacenamientoError(ErrorDeAlmacenamiento):
    """El proveedor rechazo la operacion o no pudo completarla.

    Su mensaje nombra la operacion y el codigo que devolvio el proveedor.
    **Nunca** incluye credenciales ni la excepcion del SDK en texto.
    """
