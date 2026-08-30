"""Almacenamiento de objetos: interfaz `ObjectStorage` e implementaciones.

`software-architecture.md` seccion 3.4 asigna a este paquete la interfaz y sus
implementaciones. La estructura es la que ese documento dibuja:

```
ObjectStorage          (interfaz — contrato.py)
├── MinIOStorage       (implementacion local — minio.py)
└── S3Storage          (implementacion produccion — s3.py)
```

Importar el paquete **no** carga `boto3`: las implementaciones lo importan
dentro de `_crear_cliente`, cuando de verdad hace falta un cliente. Asi un caso
de uso que solo dependa del contrato sigue siendo barato de importar y de
probar.
"""

from app.shared.storage.contrato import (
    AccesoTemporal,
    ContenidoDeObjeto,
    ObjectStorage,
    ObjetoAlmacenado,
)
from app.shared.storage.errores import (
    ConfiguracionDeAlmacenamientoInvalidaError,
    ErrorDeAlmacenamiento,
    FalloDelProveedorDeAlmacenamientoError,
    ObjetoNoEncontradoError,
)
from app.shared.storage.minio import MinIOStorage
from app.shared.storage.s3 import S3Storage

__all__ = [
    "AccesoTemporal",
    "ConfiguracionDeAlmacenamientoInvalidaError",
    "ContenidoDeObjeto",
    "ErrorDeAlmacenamiento",
    "FalloDelProveedorDeAlmacenamientoError",
    "MinIOStorage",
    "ObjectStorage",
    "ObjetoAlmacenado",
    "ObjetoNoEncontradoError",
    "S3Storage",
]
