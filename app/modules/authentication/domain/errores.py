"""Errores de la autenticacion administrativa (`Task/011`).

Extienden la jerarquia comun de `app.shared.errors`, asi que se traducen a HTTP
en el **unico punto** que hace esa traduccion y usan la envoltura de error del
proyecto (api-contracts.md seccion 7). No se crea ningun formato paralelo.

Por que hay dos codigos y no uno
--------------------------------

`invalid_credentials` y `unauthenticated` describen situaciones distintas y el
frontend reacciona distinto a cada una: la primera se muestra en el formulario de
acceso; la segunda devuelve al usuario a ese formulario. Distinguirlas **no
revela nada sobre ninguna cuenta**, que es lo que api-contracts.md prohibe.

Lo que si se mantiene indistinguible es todo lo que ocurre **dentro** de
`invalid_credentials`: correo inexistente, contrasena incorrecta y cuenta
bloqueada comparten codigo, estado y mensaje. Ver `IniciarSesion`.
"""

from __future__ import annotations

from http import HTTPStatus

from app.shared.errors.exceptions import ApplicationError

#: Mensaje unico de todo rechazo de credenciales. Es una constante y no un texto
#: repetido en cada punto: dos redacciones parecidas pero distintas serian
#: exactamente la senal que permite distinguir los casos.
MENSAJE_DE_CREDENCIALES = "Credenciales invalidas."

#: Mensaje unico de todo rechazo por falta de sesion valida. Misma razon:
#: cuatro redacciones parecidas pero distintas permitirian distinguir por que
#: se rechazo.
MENSAJE_DE_SESION = "Sesion no valida."


class CredencialesInvalidasError(ApplicationError):
    """El intento de acceso no prospera.

    **Cubre tres situaciones a proposito**: el correo no corresponde a ningun
    administrador, la contrasena no verifica, o la cuenta esta bloqueada por
    intentos fallidos. Responder distinto en cualquiera de ellas permitiria
    averiguar cual es el correo real —basta con provocar el bloqueo y ver cual de
    los dos cambia de respuesta—, y eso es la enumeracion que USER_FLOWS.md B.1
    prohibe.
    """

    code = "invalid_credentials"
    status_code = HTTPStatus.UNAUTHORIZED


class SesionNoAutenticadaError(ApplicationError):
    """No hay una sesion valida detras de la peticion.

    Cubre las cuatro formas de no tenerla —ausente, desconocida, caducada y
    revocada— con la **misma** respuesta: cual de ellas ocurrio es informacion
    sobre el estado del servidor que el cliente no necesita para actuar, porque
    en los cuatro casos debe volver a iniciar sesion.
    """

    code = "unauthenticated"
    status_code = HTTPStatus.UNAUTHORIZED


class LimiteDeAccesosError(ApplicationError):
    """Se agotaron los intentos de acceso admitidos para este origen.

    Lleva `Retry-After` porque un `429` sin el obliga al cliente legitimo a
    adivinar cuando puede volver (api-contracts.md seccion 8).
    """

    code = "too_many_requests"
    status_code = HTTPStatus.TOO_MANY_REQUESTS

    def __init__(self, message: str, *, reintentar_en_segundos: int) -> None:
        super().__init__(message, headers={"Retry-After": str(reintentar_en_segundos)})


class OrigenNoPermitidoError(ApplicationError):
    """La peticion viene de un origen que no esta en la lista explicita.

    Es la defensa CSRF de segunda capa (decision D-011-K). Responde `403` y no
    `401` porque no es un problema de identidad: la credencial puede ser
    perfectamente valida y aun asi la peticion no debe ejecutarse, que es
    justamente la forma de un ataque de falsificacion de peticion.
    """

    code = "forbidden"
    status_code = HTTPStatus.FORBIDDEN
