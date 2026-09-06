"""Endpoint administrativo del historial (`Task/012.1`).

    GET /api/v1/admin/audit-events

**Uno, y de solo lectura.** `MVP_SCOPE.md` seccion 3.3 fija como alcance minimo
del dashboard *"conteo de contenido por tipo y estado, ultimos elementos
modificados y **ultimos eventos de auditoria"*, y las 38 operaciones que dejaron
`Task/011` y `Task/012` no incluyen ninguna que lea `audit_events`.

Que **no** existe aqui, y la ausencia es el contrato
-----------------------------------------------------

No hay `POST`, ni `PUT`, ni `PATCH`, ni `DELETE`. Las invariantes 16 y 16b de
`data-model.md` siguen intactas: un `AuditEvent` **solo se crea y se lee**
(CONTENT_MODEL.md seccion 3.9), y crearlo sigue siendo competencia exclusiva de
los casos de uso de `Task/011` y `Task/012` a traves de `RegistroSqlDeAuditoria`.

Tampoco hay detalle `GET /{audit_event_id}`: el dashboard lista, no navega a un
evento suelto, y ninguna fuente lo pide. Ni filtros: seccion 3.3 pide *"los
ultimos"*, y un filtro anadido hoy seria superficie `v1` permanente
(api-contracts.md seccion 10, regla 2), mientras que anadirlo manana con un
consumidor real es compatible (regla 3).

**Leer el historial no lo modifica.** El endpoint no recibe `RegistroDeAuditoria`
ni ningun otro colaborador de escritura: *"las lecturas no se auditan"*
(CONTENT_MODEL.md seccion 3.9), y USER_FLOWS.md audita *"todo flujo
administrativo que **modifica** datos"*.

La postura de seguridad es la comun
------------------------------------

`router_administrativo()` aporta sesion obligatoria, validacion de `Origin`,
`Cache-Control: no-store` y rechazo de parametros de consulta desconocidos. **No
se anade ni se reimplementa ninguna.** La validacion de `Origin` no afecta a esta
operacion porque solo comprueba los metodos que cambian estado
(`app/shared/security/origen.py`), y un `GET` no lo es.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.admin import router_administrativo
from app.modules.audit.infrastructure.queries import (
    contar_eventos_de_auditoria,
    listar_eventos_de_auditoria,
)
from app.modules.audit.presentation.schemas_admin import EventoDeAuditoria
from app.modules.authentication.presentation import AdministradorRequerido
from app.shared.database import get_session
from app.shared.pagination import Pagina, ParametrosDePagina, parametros_de_pagina

router = router_administrativo(prefix="/admin/audit-events", tags=["administracion: auditoria"])

SesionDeBaseDeDatos = Annotated[Session, Depends(get_session)]


@router.get(
    "",
    response_model=Pagina[EventoDeAuditoria],
    summary="Historial de acciones administrativas",
    description=(
        "Coleccion paginada de los eventos de auditoria, del mas reciente al mas "
        "antiguo, con desempate estable por identificador.\n\n"
        "Es la **unica** exposicion del historial y es de **solo lectura**: un "
        "`AuditEvent` no se edita ni se elimina, y consultarlo no genera uno nuevo."
    ),
)
def listar_historial(
    sesion: SesionDeBaseDeDatos,
    administrador: AdministradorRequerido,
    parametros: Annotated[ParametrosDePagina, Depends(parametros_de_pagina)],
) -> Pagina[EventoDeAuditoria]:
    """Devuelve una pagina del historial (MVP_SCOPE.md seccion 3.3)."""
    total = contar_eventos_de_auditoria(sesion)
    eventos = listar_eventos_de_auditoria(sesion, parametros=parametros)
    return Pagina.crear(
        items=[EventoDeAuditoria.de_modelo(evento) for evento in eventos],
        parametros=parametros,
        total=total,
    )
