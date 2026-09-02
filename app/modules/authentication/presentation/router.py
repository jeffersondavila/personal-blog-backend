"""Endpoints de autenticacion administrativa (`Task/011`).

Los tres del contrato (api-contracts.md seccion 4), y ninguno mas:

    POST /api/v1/admin/auth/login     unico endpoint administrativo publico
    POST /api/v1/admin/auth/logout    exige sesion
    GET  /api/v1/admin/auth/me        exige sesion

No hay `register`, ni `forgot-password`, ni `change-password`: **ninguna fuente
canonica los asigna a esta tarea**, y no hay registro publico en el producto
(MVP_SCOPE.md seccion 3).

Endpoints delgados (software-architecture.md seccion 3.5, regla 2): validan la
entrada, invocan el caso de uso y serializan. Ninguna decision de autenticacion
se toma aqui — se toma en `application`, y por eso vale igual detras de uvicorn
que detras de Lambda.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.modules.authentication.application.iniciar_sesion import (
    AccesoLimitado,
    SesionIniciada,
)
from app.modules.authentication.domain.errores import (
    MENSAJE_DE_CREDENCIALES,
    CredencialesInvalidasError,
    LimiteDeAccesosError,
)
from app.modules.authentication.presentation.cookies import (
    instalar_credencial,
    retirar_credencial,
)
from app.modules.authentication.presentation.dependencias import (
    AdministradorRequerido,
    CasoDeCierreDeSesion,
    CasoDeInicioDeSesion,
    ConfiguracionDependencia,
    ContextoRequerido,
    SesionEnCursoRequerida,
    exigir_origen_permitido,
    sin_cache,
)
from app.modules.authentication.presentation.schemas import (
    AdministradorPublico,
    CredencialesDeAcceso,
)
from app.shared.errors.schemas import RESPUESTAS_DE_ERROR, RespuestaDeError

router = APIRouter(
    prefix="/admin/auth",
    tags=["administracion: autenticacion"],
    # `no-store` en las tres respuestas: una respuesta de autenticacion guardada
    # en una cache compartida es una fuga. `200` es cacheable por defecto segun
    # la norma, asi que decirlo cuesta una cabecera.
    dependencies=[Depends(sin_cache), Depends(exigir_origen_permitido)],
    # `RESPUESTAS_DE_ERROR` trae el `422` con la envoltura real del proyecto.
    # Sin el, FastAPI documentaria su propia forma (`HTTPValidationError`, con
    # una lista `detail`), que este backend **no devuelve**: un cliente
    # generado desde esa especificacion fallaria al leer el primer error de
    # validacion del formulario de acceso.
    responses={
        **RESPUESTAS_DE_ERROR,
        403: {
            "model": RespuestaDeError,
            "description": "La peticion no procede de un origen permitido.",
        },
        401: {
            "model": RespuestaDeError,
            "description": "Credenciales invalidas o sesion no valida.",
        },
    },
)


@router.post(
    "/login",
    response_model=AdministradorPublico,
    status_code=status.HTTP_200_OK,
    summary="Iniciar sesion administrativa",
    description=(
        "Unico endpoint administrativo publico. Con credenciales validas entrega la "
        "sesion en una cookie `HttpOnly`; **la credencial no aparece en el cuerpo**.\n\n"
        "Un correo inexistente, una contrasena incorrecta y una cuenta bloqueada "
        "producen exactamente la misma respuesta: la API no revela si una cuenta existe."
    ),
    responses={
        429: {
            "model": RespuestaDeError,
            "description": "Se agotaron los intentos admitidos para este origen.",
        }
    },
)
def iniciar_sesion(
    credenciales: CredencialesDeAcceso,
    respuesta: Response,
    settings: ConfiguracionDependencia,
    caso_de_uso: CasoDeInicioDeSesion,
    contexto: ContextoRequerido,
) -> AdministradorPublico:
    """Verifica las credenciales y abre una sesion."""
    resultado = caso_de_uso(
        correo=credenciales.email,
        contrasena=credenciales.password.get_secret_value(),
        contexto=contexto,
    )
    if isinstance(resultado, AccesoLimitado):
        raise LimiteDeAccesosError(
            "Demasiados intentos de acceso. Intentalo mas tarde.",
            reintentar_en_segundos=resultado.reintentar_en_segundos,
        )
    if not isinstance(resultado, SesionIniciada):
        # Mensaje unico y constante: ver `CredencialesInvalidasError`.
        raise CredencialesInvalidasError(MENSAJE_DE_CREDENCIALES)

    instalar_credencial(respuesta, credencial=resultado.credencial, settings=settings)
    return AdministradorPublico.de_identidad(resultado.administrador)


@router.get(
    "/me",
    response_model=AdministradorPublico,
    status_code=status.HTTP_200_OK,
    summary="Consultar la sesion actual",
    description=(
        "Devuelve la identidad del administrador **derivada de la sesion**. Nada de lo "
        "que envie el cliente participa en esa resolucion.\n\n"
        "Sin sesion, con una credencial desconocida, caducada o revocada responde el mismo "
        "`401`."
    ),
)
def sesion_actual(administrador: AdministradorRequerido) -> AdministradorPublico:
    """Devuelve quien es el titular de la sesion en curso."""
    return AdministradorPublico.de_identidad(administrador)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cerrar la sesion administrativa",
    description=(
        "Invalida la sesion **en el servidor** y pide al navegador que olvide la cookie.\n\n"
        "La credencial presentada deja de autenticar de inmediato, aunque alguien la "
        "hubiera copiado antes de cerrar sesion."
    ),
)
def cerrar_sesion(
    respuesta: Response,
    settings: ConfiguracionDependencia,
    actual: SesionEnCursoRequerida,
    caso_de_uso: CasoDeCierreDeSesion,
    contexto: ContextoRequerido,
) -> None:
    """Revoca la sesion en curso.

    El orden importa: **primero se revoca en el servidor** y despues se borra la
    cookie. Al reves, un fallo entre medias dejaria al propietario sin cookie y
    con la sesion viva — es decir, sin poder cerrarla.
    """
    caso_de_uso(
        credencial=actual.credencial,
        administrador_id=actual.administrador.id,
        contexto=contexto,
    )
    retirar_credencial(respuesta, settings=settings)
