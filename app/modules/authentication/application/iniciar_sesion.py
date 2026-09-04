"""Caso de uso: iniciar sesion administrativa (`Task/011`).

Orquesta los puertos del dominio y **no conoce** SQLAlchemy, FastAPI ni cookies.
Eso es lo que permite probarlo con dobles y lo que hace que el mismo caso de uso
funcione detras de uvicorn o detras de Lambda.

Por que devuelve un resultado en lugar de lanzar (decision D-011-N)
-------------------------------------------------------------------

Un intento fallido **escribe**: incrementa el contador, puede activar el bloqueo,
consume una unidad del limite de tasa y deja un evento de auditoria. Si el fallo
se senalara lanzando una excepcion, esa excepcion subiria por la dependencia de
sesion de FastAPI, `session_scope` haria `rollback` y **todo ese estado
defensivo se perderia**: el contador volveria a cero en cada intento y el bloqueo
no llegaria a existir nunca.

Por eso el caso de uso **confirma su propia transaccion** —tambien en el camino
de fallo— y devuelve un resultado que la presentacion traduce. La regresion que
lo fija vive en `tests/integration/test_persistencia_del_acceso_fallido.py`, que
ejercita la ruta real de sesion en lugar de la transaccion del harness.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from app.modules.audit.domain.acciones import ENTIDAD_ADMINISTRADOR, AccionAuditada
from app.modules.authentication.domain.bloqueo import (
    cuenta_bloqueada,
    estado_tras_un_fallo,
)
from app.modules.authentication.domain.puertos import (
    AdministradorAutenticado,
    ContextoDeAuditoria,
    LimitadorDeAccesos,
    RegistroDeAuditoria,
    Reloj,
    RepositorioDeAdministradores,
    RepositorioDeSesiones,
    UnidadDeTrabajo,
)
from app.modules.authentication.domain.sesion import (
    generar_credencial,
    huella_de_credencial,
)
from app.shared.security import (
    contrasena_valida,
    hash_de_contrasena,
    necesita_rehash,
    verificacion_senuelo,
)


@dataclass(frozen=True, slots=True)
class SesionIniciada:
    """El acceso prospero. La credencial viaja **solo** en la cookie."""

    credencial: str
    duracion_en_segundos: int
    administrador: AdministradorAutenticado


@dataclass(frozen=True, slots=True)
class AccesoRechazado:
    """El acceso no prospera.

    No dice **por que**, y es deliberado: quien lo traduce a HTTP no tiene forma
    de responder distinto segun el motivo aunque quisiera. Correo inexistente,
    contrasena incorrecta y cuenta bloqueada producen este mismo resultado.
    """


@dataclass(frozen=True, slots=True)
class AccesoLimitado:
    """Se agotaron los intentos admitidos para este origen.

    Es el unico rechazo que **si** se distingue del resto, y puede hacerlo sin
    filtrar nada: depende del origen de la peticion, no de si la cuenta existe.
    Un correo inventado y uno real alcanzan el limite exactamente igual.
    """

    reintentar_en_segundos: int


ResultadoDeAcceso = SesionIniciada | AccesoRechazado | AccesoLimitado


class IniciarSesion:
    """Verifica unas credenciales y, si valen, abre una sesion."""

    def __init__(
        self,
        *,
        administradores: RepositorioDeAdministradores,
        sesiones: RepositorioDeSesiones,
        limitador: LimitadorDeAccesos,
        auditoria: RegistroDeAuditoria,
        unidad_de_trabajo: UnidadDeTrabajo,
        reloj: Reloj,
        duracion_de_la_sesion: timedelta,
        maximo_de_fallos: int,
        duracion_del_bloqueo: timedelta,
    ) -> None:
        self._administradores = administradores
        self._sesiones = sesiones
        self._limitador = limitador
        self._auditoria = auditoria
        self._unidad_de_trabajo = unidad_de_trabajo
        self._reloj = reloj
        self._duracion = duracion_de_la_sesion
        self._maximo_de_fallos = maximo_de_fallos
        self._duracion_del_bloqueo = duracion_del_bloqueo

    def __call__(
        self, *, correo: str, contrasena: str, contexto: ContextoDeAuditoria
    ) -> ResultadoDeAcceso:
        """Ejecuta el intento de acceso.

        El orden de los pasos importa y no es casual:

        0. **El limite de tasa se consulta primero**, antes de tocar la fila del
           administrador y antes de gastar Argon2id. Ponerlo despues haria que
           una rafaga siguiera costando una verificacion criptografica por
           peticion, que es justo lo que el limite existe para evitar. Se
           cuentan todos los intentos, acertados o no.
        1. Se lee el administrador **bloqueando su fila**. Sin ese bloqueo, dos
           intentos simultaneos leerian el mismo contador y una de las dos
           escrituras se perderia.
        2. Si el correo no corresponde a nadie, se ejecuta una **verificacion
           senuelo**. Salir aqui sin gastar Argon2id haria que el caso "este
           correo no existe" respondiera perceptiblemente antes que el caso "la
           contrasena es incorrecta", y esa diferencia de milisegundos es
           suficiente para enumerar cuentas con un reloj.
        3. **La contrasena se verifica siempre**, incluso con la cuenta
           bloqueada. Salir antes por estar bloqueada ahorraria el trabajo
           criptografico y volveria a crear la diferencia de tiempo que el paso
           anterior existe para eliminar: bastaria con provocar el bloqueo de un
           correo y medir para saber si esa cuenta existe.
        4. Solo despues se decide, y una cuenta bloqueada se rechaza **aunque la
           contrasena fuera correcta**.
        """
        ahora = self._reloj.ahora()

        limite = self._limitador.registrar_intento(contexto.origen, ahora=ahora)
        if not limite.permitido:
            # Un limite superado **no** se audita: es un hecho operativo del
            # endpoint que cualquiera puede provocar desde fuera, y anadirlo
            # al historial permitiria llenarlo de ruido a voluntad.
            self._unidad_de_trabajo.confirmar()
            return AccesoLimitado(reintentar_en_segundos=limite.reintentar_en_segundos)

        estado = self._administradores.bloquear_por_correo(correo)

        if estado is None:
            verificacion_senuelo(contrasena)
            # Sin actor: no hay administrador al que atribuir el intento, y el
            # correo recibido **no** se guarda (requisito O-09). Que
            # `actor_id` sea nulo es, en si mismo, la informacion de que el
            # correo probado no existe.
            self._auditar(AccionAuditada.ACCESO_FALLIDO, None, contexto)
            self._unidad_de_trabajo.confirmar()
            return AccesoRechazado()

        bloqueada = cuenta_bloqueada(estado.locked_until, ahora=ahora)
        credenciales_correctas = contrasena_valida(estado.password_hash, contrasena)

        if bloqueada or not credenciales_correctas:
            # Un intento fallido con la cuenta ya bloqueada no cuenta ni alarga
            # el bloqueo: la regla vive en el dominio, no aqui.
            defensivo = estado_tras_un_fallo(
                fallos=estado.failed_login_attempts,
                bloqueado_hasta=estado.locked_until,
                ahora=ahora,
                umbral=self._maximo_de_fallos,
                duracion=self._duracion_del_bloqueo,
            )
            self._administradores.registrar_intento_fallido(
                estado.id,
                fallos=defensivo.fallos,
                bloqueado_hasta=defensivo.bloqueado_hasta,
            )
            self._auditar(AccionAuditada.ACCESO_FALLIDO, estado.id, contexto)
            if not bloqueada and defensivo.bloqueado_hasta is not None:
                # Se audita la **transicion**, no el estado: sin esta
                # condicion, cada intento durante el bloqueo anadiria un
                # evento y el historial quedaria inservible justo cuando hace
                # falta leerlo.
                self._auditar(AccionAuditada.CUENTA_BLOQUEADA, estado.id, contexto)
            self._unidad_de_trabajo.confirmar()
            return AccesoRechazado()

        credencial = generar_credencial()
        self._sesiones.crear(
            administrador_id=estado.id,
            huella=huella_de_credencial(credencial),
            expira_en=ahora + self._duracion,
        )
        self._administradores.registrar_acceso_correcto(
            estado.id,
            instante=ahora,
            # Rehash silencioso: si el hash guardado usaba parametros anteriores,
            # se sustituye ahora, que es el unico momento en que la contrasena en
            # claro esta disponible para recalcularlo. El propietario no se entera
            # y no tiene que hacer nada.
            password_hash=(
                hash_de_contrasena(contrasena) if necesita_rehash(estado.password_hash) else None
            ),
        )
        self._auditar(AccionAuditada.ACCESO_CORRECTO, estado.id, contexto)
        self._unidad_de_trabajo.confirmar()
        return SesionIniciada(
            credencial=credencial,
            duracion_en_segundos=int(self._duracion.total_seconds()),
            administrador=estado.identidad,
        )

    def _auditar(
        self,
        accion: AccionAuditada,
        administrador_id: uuid.UUID | None,
        contexto: ContextoDeAuditoria,
    ) -> None:
        """Deja constancia del intento en el historial administrativo.

        Sin metadatos: lo unico que podria ponerse ahi —el correo recibido— es
        justamente lo que no debe guardarse. Quien actuo lo dice `actor_id`;
        desde donde, el origen; y con que peticion, el `request_id`.
        """
        self._auditoria.registrar(
            accion.value,
            entidad=ENTIDAD_ADMINISTRADOR,
            actor_id=administrador_id,
            entidad_id=administrador_id,
            request_id=contexto.request_id,
            ip=contexto.origen,
        )
