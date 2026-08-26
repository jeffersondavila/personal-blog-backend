"""Tipos de columna propios del proyecto.

Detalle **tecnico** de persistencia: como se guarda una enumeracion de Python en
PostgreSQL. La enumeracion en si —sus valores y su significado— pertenece al
dominio de cada modulo; aqui solo se decide su representacion fisica.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum

#: Holgura suficiente para los valores actuales (`published`, `completed`) y para
#: los que quepa anadir sin migrar el tipo.
LONGITUD_DE_ENUMERACION = 32


def enum_column(enumeracion: type[StrEnum], *, name: str) -> Enum:
    """Columna `VARCHAR` con *check constraint*, a partir de una enumeracion.

    Por que no un `ENUM` nativo de PostgreSQL
    -----------------------------------------

    Un tipo `ENUM` nativo es un objeto de esquema aparte: anadir un valor exige
    `ALTER TYPE ... ADD VALUE`, **quitar** uno no se puede sin recrear el tipo, y
    el `downgrade` de una migracion tiene que acordarse de soltarlo o deja basura
    en la base. Requisito M-04: toda migracion aplica **y** revierte, y el `ENUM`
    nativo es precisamente donde eso se rompe con mas facilidad.

    Un `VARCHAR` con `CHECK` da la misma garantia de integridad, se lee sin
    consultar el catalogo, se extiende cambiando una restriccion y desaparece con
    la tabla. Es ademas SQL corriente, sin objetos propietarios (requisito T-02).

    `values_callable` guarda el **valor** del miembro (`"draft"`), no su nombre
    (`"DRAFT"`): es lo que la API expone y lo que api-contracts.md declara
    contrato cerrado.

    `create_constraint=True` es obligatorio y no un adorno: desde SQLAlchemy 1.4
    el valor por defecto es `False`, asi que sin el la columna seria un `VARCHAR`
    **sin ninguna comprobacion** y aceptaria cualquier cadena.
    """
    return Enum(
        enumeracion,
        name=name,
        native_enum=False,
        length=LONGITUD_DE_ENUMERACION,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda tipo: [miembro.value for miembro in tipo],
    )
