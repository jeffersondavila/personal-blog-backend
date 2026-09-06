"""Sitemap publico del sitio (`Task/016`, requisitos E-05 y E-08).

Modulo transversal de solo lectura, con la misma forma que `search`: no tiene
dominio ni casos de uso porque no orquesta nada ni protege ninguna invariante
propia. Lee el contenido publicado de `posts`, `book_reviews` y `projects`, y lo
serializa como el XML que define el protocolo de sitemaps.

`software-architecture.md` seccion 3.2 prohibe crear capas vacias: una capa
`application` seria aqui una funcion que reenvia sus argumentos.

La regla que importa —**solo aparece contenido `published`**, invariante 19 de
`data-model.md` y requisito **E-08**— vive dentro de la consulta, que es donde
nadie puede saltarsela.
"""
