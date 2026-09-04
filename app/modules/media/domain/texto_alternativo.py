"""Regla del texto alternativo al **usar** una imagen (`Task/012`, D-012-Y).

De donde sale
-------------

`data-model.md` seccion 4.1, fila `alt_text`, y la decision **D-010-N** de
`Task/010` dicen lo mismo con las mismas palabras: *"se escribe al **usar** la
imagen, no al cargarla"*, y *"exigirlo donde se usa es de `Task/012` y
`Task/014`"*.

**Comprobar que el texto ya existe no es escribirlo.** Si el unico momento
posible de escritura fuera la carga, aquella frase seria falsa y el
administrador tendria que anticipar el texto sin saber todavia en que contenido
va a aparecer la imagen — que es exactamente lo que `Task/010` rechazo. Por eso
el **primer uso** puede escribirlo.

Por que la regla vive en el modulo `media`
-------------------------------------------

`alt_text` es metadato **del asset**, no de la asociacion: vive en
`media_assets`, no en una columna por contenido. Quien es dueno de esa entidad
es el modulo `media` (software-architecture.md seccion 3.3), asi que la regla se
escribe una vez aqui y la usan los cinco sitios donde una imagen se referencia.
Es Python plano: no conoce persistencia ni HTTP.

La politica ante un texto distinto (D-012-Z)
--------------------------------------------

Que ocurre cuando la imagen **ya tiene** texto y se propone **otro distinto**.
Ninguna fuente vigente lo define; se comprobo una por una. Lo que si existe es
el riesgo, descrito por **D-010-J** para el caso analogo de la deduplicacion:
*"reutilizar en silencio haria que borrar un medio afectara a contenidos que
nunca lo subieron"*. Sobrescribir el texto tendria la misma forma — cambiaria lo
que ya usa otro contenido, que no ha pedido nada.

Rechazar tambien es una decision de comportamiento, no la ausencia de una: no
seria honesto presentarla como la unica salida posible. Ante la ausencia de una
semantica canonica previa, `Task/012` adopta para el MVP la politica
conservadora de rechazar una sobrescritura diferente. La revision externa acepta
**D-012-Z**. La politica es explicita, reversible y evita modificar en silencio
un `MediaAsset` que puede estar siendo utilizado por otro contenido.

**Poder corregir a proposito** un texto ya fijado es una mejora futura, sin
propietario y sin plazo. No contradice a D-012-Z: la relajaria de forma
deliberada el dia que alguien decida la semantica.
"""

from __future__ import annotations

from app.shared.errors.exceptions import ConflictError


class TextoAlternativoEnConflictoError(ConflictError):
    """Se propuso un texto alternativo distinto del que la imagen ya tiene.

    **No se sobrescribe.** El texto es del asset, y otro contenido puede estar
    usandolo ya.
    """

    code = "alt_text_conflict"

    def __init__(self, *, campo: str, actual: str, propuesto: str) -> None:
        super().__init__(
            "La imagen ya tiene un texto alternativo distinto. No se sobrescribe: "
            "podria estar en uso por otro contenido.",
            details={"campo": campo, "actual": actual, "propuesto": propuesto},
        )
        self.campo = campo
        self.actual = actual
        self.propuesto = propuesto


def _util(valor: str | None) -> str | None:
    """Texto util, o `None`. Un texto en blanco no describe nada."""
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None


def texto_a_escribir(*, actual: str | None, propuesto: str | None, campo: str) -> str | None:
    """Decide que texto alternativo hay que persistir, si es que hay alguno.

    | `actual` | `propuesto` | Resultado |
    | --- | --- | --- |
    | cualquiera | ausente o en blanco | `None`: no se escribe nada |
    | ausente o en blanco | con texto | **el propuesto**: es el primer uso |
    | con texto | **el mismo** | `None`: ya esta, no hay nada que hacer |
    | con texto | **distinto** | `TextoAlternativoEnConflictoError` |

    Que reenviar el mismo texto sea valido no es un detalle: un panel que
    muestra el texto que ya tiene la imagen lo devolvera tal cual al guardar, y
    eso no puede ser un error.
    """
    limpio = _util(propuesto)
    if limpio is None:
        return None

    vigente = _util(actual)
    if vigente is None:
        return limpio
    if vigente == limpio:
        return None
    raise TextoAlternativoEnConflictoError(campo=campo, actual=vigente, propuesto=limpio)
