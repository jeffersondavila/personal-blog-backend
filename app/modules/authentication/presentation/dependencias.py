"""Dependencias de la autenticacion administrativa (`Task/011`).

Aqui se **ensamblan** los casos de uso: es el unico punto que sabe a la vez que
existe una sesion de SQLAlchemy, una configuracion y un reloj. Los casos de uso
reciben puertos y siguen sin conocer ninguna de las tres cosas.

Se usa la inyeccion de dependencias **del framework** y nada mas
(software-architecture.md seccion 3.5, regla 6): no hay contenedor de DI, ni
localizador de servicios, ni registro global.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request, Response
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from app.modules.audit.infrastructure.registro import RegistroSqlDeAuditoria
from app.modules.authentication.application.cerrar_sesion import CerrarSesion
from app.modules.authentication.application.iniciar_sesion import IniciarSesion
from app.modules.authentication.domain.errores import (
    MENSAJE_DE_SESION,
    OrigenNoPermitidoError,
    SesionNoAutenticadaError,
)
from app.modules.authentication.domain.puertos import AdministradorAutenticado
from app.modules.authentication.domain.sesion import huella_de_credencial
from app.modules.authentication.infrastructure.limitador import (
    LimitadorSqlDeAccesos,
)
from app.modules.authentication.infrastructure.reloj import RelojDelSistema
from app.modules.authentication.infrastructure.repositorios import (
    RepositorioSqlDeAdministradores,
    RepositorioSqlDeSesiones,
    UnidadDeTrabajoSql,
)
from app.modules.authentication.presentation.cookies import NOMBRE_DE_LA_COOKIE
from app.shared.configuration import Settings, get_settings
from app.shared.database import get_session
from app.shared.errors.handlers import request_id_de
from app.shared.security import direccion_del_cliente, origen_permitido

ConfiguracionDependencia = Annotated[Settings, Depends(get_settings)]
SesionDeBaseDeDatos = Annotated[Session, Depends(get_session)]


def exigir_origen_permitido(peticion: Request, settings: ConfiguracionDependencia) -> None:
    """Rechaza una peticion que cambia estado y no viene de un origen declarado.

    Es la segunda capa de la defensa CSRF (decision D-011-K). La primera es
    `SameSite=Lax`, que impide que el navegador **envie** la cookie en una
    peticion *cross-site*; esta no depende de que el navegador se comporte.

    Se aplica a **todo** el router de autenticacion, incluido `login`: un CSRF de
    inicio de sesion —forzar a la victima a entrar con la cuenta del atacante— es
    menos grave, pero no hay ninguna razon para dejarlo abierto cuando la guarda
    ya esta puesta.

    La politica concreta —que metodos, que pasa sin `Origin`, por que la lista
    vacia rechaza— vive en `app.shared.security.origen`, con su justificacion.
    """
    if not origen_permitido(
        metodo=peticion.method,
        origen=peticion.headers.get("origin"),
        permitidos=settings.origenes_administrativos_permitidos,
    ):
        raise OrigenNoPermitidoError(
            "La peticion no procede de un origen permitido.",
        )


def sin_cache(respuesta: Response) -> None:
    """Marca la respuesta como no almacenable.

    Una respuesta de autenticacion guardada en una cache compartida es una fuga:
    la identidad de quien inicio sesion podria servirse a otro. `200` y `204` son
    cacheables por defecto segun la norma, asi que decir lo contrario cuesta una
    cabecera y evita depender de que ningun intermediario se equivoque.

    La politica **global** de cabeceras de seguridad sigue siendo de `Task/018`.
    Esto es solo lo que el contrato de estos tres endpoints necesita.
    """
    respuesta.headers["Cache-Control"] = "no-store"


@dataclass(frozen=True, slots=True)
class ContextoDeLaPeticion:
    """Lo que un caso de uso necesita saber de la peticion que lo invoco.

    Son los dos datos con los que se correlaciona un evento de auditoria:
    **desde donde** llego la peticion y **cual** fue. Van juntos en un objeto y
    no como dos argumentos sueltos para que anadir un tercero —cuando
    `Task/017` cierre la propagacion del correlation ID— no obligue a tocar la
    firma de cada caso de uso.

    El caso de uso sigue sin conocer HTTP: recibe dos cadenas.
    """

    origen: str
    request_id: str


def contexto_de_la_peticion(
    peticion: Request, settings: ConfiguracionDependencia
) -> ContextoDeLaPeticion:
    """Extrae de la peticion HTTP lo que los casos de uso necesitan.

    La direccion se resuelve con la politica de confianza en proxies, cuyo valor
    por defecto **ignora** `X-Forwarded-For`; el identificador es el mismo que
    aparecera en el cuerpo de error si la peticion acaba en uno.
    """
    return ContextoDeLaPeticion(
        origen=direccion_del_cliente(
            direccion_del_par=peticion.client.host if peticion.client else None,
            cabecera_reenviada=peticion.headers.get("x-forwarded-for"),
            saltos_de_confianza=settings.trusted_proxy_hop_count,
        ),
        request_id=request_id_de(peticion),
    )


ContextoRequerido = Annotated[ContextoDeLaPeticion, Depends(contexto_de_la_peticion)]


#: Esquema de seguridad que OpenAPI publica para los endpoints protegidos.
#:
#: `auto_error=False` es deliberado: con `True`, FastAPI responderia su propio
#: `403` con la forma `{'detail': ...}`, que **no es** la envoltura de error del
#: proyecto (api-contracts.md seccion 7) y ademas seria un codigo equivocado —la
#: ausencia de credencial es `401`—. Devolviendo `None` se decide aqui.
_credencial_de_sesion = APIKeyCookie(
    name=NOMBRE_DE_LA_COOKIE,
    scheme_name="sesionAdministrativa",
    description=(
        "Cookie de sesion administrativa. La emite `POST /admin/auth/login`, "
        "es `HttpOnly` y no es legible por JavaScript."
    ),
    auto_error=False,
)


@dataclass(frozen=True, slots=True)
class SesionEnCurso:
    """Sesion administrativa validada, con la credencial que la identifica.

    Existe porque **cerrar sesion necesita las dos mitades**: la identidad, para
    auditar quien cerro, y la credencial, para saber cual de sus sesiones
    revocar. Devolver solo la identidad obligaria al endpoint a volver a leer la
    cookie por su cuenta, que es la clase de duplicado que acaba divergiendo.

    **No sale nunca en una respuesta.** Lo que se serializa es
    `AdministradorPublico`, construido desde `administrador`.
    """

    administrador: AdministradorAutenticado
    credencial: str = field(repr=False)


def sesion_en_curso(
    credencial: Annotated[str | None, Depends(_credencial_de_sesion)],
    sesion: SesionDeBaseDeDatos,
) -> SesionEnCurso:
    """Valida la sesion presentada y la devuelve entera.

    Los cuatro motivos de rechazo —sin cookie, credencial desconocida, sesion
    caducada y sesion revocada— producen **la misma** respuesta: al cliente le
    sirven exactamente para lo mismo, y distinguirlos solo informaria a quien
    esta probando credenciales.
    """
    if not credencial:
        raise SesionNoAutenticadaError(MENSAJE_DE_SESION)

    identidad = RepositorioSqlDeSesiones(sesion).buscar_vigente(
        huella_de_credencial(credencial), ahora=RelojDelSistema().ahora()
    )
    if identidad is None:
        raise SesionNoAutenticadaError(MENSAJE_DE_SESION)
    return SesionEnCurso(administrador=identidad, credencial=credencial)


SesionEnCursoRequerida = Annotated[SesionEnCurso, Depends(sesion_en_curso)]


def requiere_administrador(actual: SesionEnCursoRequerida) -> AdministradorAutenticado:
    """Exige una sesion administrativa valida y devuelve quien la posee.

    **Es la proteccion reutilizable que `Task/012` aplicara a todos sus
    endpoints** (el `require_administrator` del alcance de la tarea). Se exporta
    desde `app.modules.authentication.presentation`, que es la interfaz publica
    del modulo: ningun router futuro necesita repetir esta logica ni conocer las
    entranas de la autenticacion.

    Hace cuatro cosas y ninguna mas: extrae la credencial, valida la sesion,
    resuelve el administrador y rechaza si algo falla. **No contiene ninguna
    regla de CRUD** ni depende de ningun router concreto.

    Devuelve la identidad y **no** la credencial: un endpoint de contenido no
    tiene ninguna razon para ver el secreto de sesion. Quien lo necesita —solo
    `logout`— pide `SesionEnCursoRequerida`.
    """
    return actual.administrador


#: Tipo que los endpoints protegidos declaran como parametro. `Task/012` hara
#: `administrador: AdministradorRequerido` y nada mas.
AdministradorRequerido = Annotated[AdministradorAutenticado, Depends(requiere_administrador)]


def construir_inicio_de_sesion(
    sesion: SesionDeBaseDeDatos, settings: ConfiguracionDependencia
) -> IniciarSesion:
    """Ensambla el caso de uso de inicio de sesion con sus adaptadores reales."""
    return IniciarSesion(
        administradores=RepositorioSqlDeAdministradores(sesion),
        sesiones=RepositorioSqlDeSesiones(sesion),
        limitador=LimitadorSqlDeAccesos(
            sesion,
            maximo=settings.auth_rate_limit_max_attempts,
            ventana=timedelta(seconds=settings.auth_rate_limit_window_seconds),
        ),
        auditoria=RegistroSqlDeAuditoria(sesion),
        unidad_de_trabajo=UnidadDeTrabajoSql(sesion),
        reloj=RelojDelSistema(),
        duracion_de_la_sesion=timedelta(seconds=settings.auth_session_ttl_seconds),
        maximo_de_fallos=settings.auth_max_failed_attempts,
        duracion_del_bloqueo=timedelta(seconds=settings.auth_lockout_seconds),
    )


CasoDeInicioDeSesion = Annotated[IniciarSesion, Depends(construir_inicio_de_sesion)]


def construir_cierre_de_sesion(sesion: SesionDeBaseDeDatos) -> CerrarSesion:
    """Ensambla el caso de uso de cierre de sesion."""
    return CerrarSesion(
        sesiones=RepositorioSqlDeSesiones(sesion),
        auditoria=RegistroSqlDeAuditoria(sesion),
        unidad_de_trabajo=UnidadDeTrabajoSql(sesion),
        reloj=RelojDelSistema(),
    )


CasoDeCierreDeSesion = Annotated[CerrarSesion, Depends(construir_cierre_de_sesion)]
