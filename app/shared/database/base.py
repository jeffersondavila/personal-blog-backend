"""Base declarativa de los modelos ORM.

`Task/005` no define ningun modelo: el modelo de datos del blog corresponde a
`Task/008`. Lo que se establece aqui es el punto unico del que colgaran esos
modelos y, con el, los metadatos que Alembic compara para detectar cambios.

La convencion de nombres es deliberada: sin ella, PostgreSQL asigna nombres
implicitos a indices y restricciones y las migraciones generadas resultan
irreversibles en la practica, porque el `downgrade` no sabe que nombre borrar
(requisito M-04: toda migracion aplica **y** revierte).

Solo se usa SQL estandar de PostgreSQL, sin extensiones ni tipos propietarios
(requisito T-02), para no atar el proyecto a un proveedor concreto.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

#: `ix` indice, `uq` unico, `ck` comprobacion, `fk` clave foranea, `pk` primaria.
NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Clase base de todos los modelos ORM del proyecto."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
