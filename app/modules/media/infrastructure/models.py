"""Modelo ORM de los medios almacenados.

`Task/008` define **solo los datos**. La interfaz `ObjectStorage`, sus
implementaciones (`MinIOStorage`, `S3Storage`), la subida, las miniaturas y las
URL prefirmadas son de `Task/010`: aqui no hay ni SDK ni cliente de
almacenamiento.

La base de datos guarda **metadatos y la clave del objeto, nunca el binario**
(CONTENT_MODEL.md seccion 3.7). Y guarda la **clave**, nunca una URL prefirmada:
las prefirmadas caducan, asi que persistirlas produciria enlaces muertos
(ETAPA 03, regla de persistencia).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base
from app.shared.database.mixins import CreationTimestampMixin, UuidPrimaryKeyMixin

#: Las claves de objeto llevan prefijos y un componente no predecible.
LONGITUD_DE_CLAVE_DE_OBJETO = 512
#: Limite practico de un nombre de archivo en los sistemas de archivos comunes.
LONGITUD_DE_NOMBRE_DE_ARCHIVO = 255
#: Limite del tipo MIME segun RFC 4288 (127 + "/" + 127 excede lo razonable aqui).
LONGITUD_DE_TIPO_MIME = 127
LONGITUD_DE_TEXTO_ALTERNATIVO = 255
#: SHA-256 en hexadecimal.
LONGITUD_DE_CHECKSUM = 64


class MediaAsset(UuidPrimaryKeyMixin, CreationTimestampMixin, Base):
    """Imagen almacenada en el almacenamiento de objetos."""

    __tablename__ = "media_assets"

    #: Clave del objeto en el almacenamiento. Unica: dos filas no pueden
    #: reclamar el mismo objeto, y esa unicidad es lo que hace fiable la
    #: comprobacion de uso previa al borrado (USER_FLOWS.md B.5).
    object_key: Mapped[str] = mapped_column(
        String(LONGITUD_DE_CLAVE_DE_OBJETO), nullable=False, unique=True
    )
    original_filename: Mapped[str] = mapped_column(
        String(LONGITUD_DE_NOMBRE_DE_ARCHIVO), nullable=False
    )
    mime_type: Mapped[str] = mapped_column(String(LONGITUD_DE_TIPO_MIME), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    #: Necesario para accesibilidad (requisito A-04). Admite nulo porque se
    #: escribe al usar la imagen, no al subirla; exigirlo es de `Task/010`.
    alt_text: Mapped[str | None] = mapped_column(String(LONGITUD_DE_TEXTO_ALTERNATIVO))
    #: Opcional, para detectar duplicados. Indexado porque esa deteccion es una
    #: consulta prevista (CONTENT_MODEL.md seccion 3.7).
    checksum: Mapped[str | None] = mapped_column(String(LONGITUD_DE_CHECKSUM), index=True)

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="tamano_positivo"),
        CheckConstraint("width IS NULL OR width > 0", name="ancho_positivo"),
        CheckConstraint("height IS NULL OR height > 0", name="alto_positivo"),
    )
