"""performance.py — compresion de las respuestas HTTP.

Vive aparte por el mismo motivo que app/security.py: el proyecto arranca por
dos caminos (`app/__init__.py` con create_app, que es el que usa run.py, y el
`app.py` heredado) y los dos tienen que quedar configurados igual.

Que hace Flask-Compress: negocia con el navegador via Accept-Encoding y
devuelve el cuerpo en zstd / brotli / gzip. Sobre HTML, CSS, JS y JSON el
ahorro tipico ronda el 70-80%, que en una conexion movil colombiana es la
diferencia mas grande que se puede conseguir sin tocar una linea de la vista.

Lo que NO se comprime, a proposito:

  - PNG, JPEG, WebP y .ico: ya vienen comprimidos. Volver a pasarlos por gzip
    gasta CPU en cada peticion y suele dejar el archivo un poco mas grande.
    Estos tipos no estan en COMPRESS_MIMETYPES.
  - Respuestas por debajo de COMPRESS_MIN_SIZE (500 bytes). Con cuerpos tan
    pequenos la cabecera del formato se come el ahorro. Esto deja fuera a
    robots.txt, que pesa ~400 bytes, y esta bien: no hay nada que ganar.

Los tipos que si importan y que la lista por defecto de Flask-Compress ya
cubre: text/html, text/css, application/javascript, application/json,
application/xml (el sitemap), application/manifest+json (site.webmanifest) y
image/svg+xml (el favicon vectorial, que es texto plano y se reduce a la
mitad). No hace falta ampliar la lista.
"""

from __future__ import annotations

from flask_compress import Compress


def init_compresion(app) -> None:
    """Activa la compresion sobre una app Flask.

    Una instancia por app, no un singleton de modulo: es la misma trampa que
    documenta app/security.py con Talisman. Flask-Compress guarda el conjunto
    de mimetypes y los algoritmos habilitados en atributos de la instancia, asi
    que un segundo init_app sobre el mismo objeto pisaria la configuracion de
    la primera app. Los dos bootstraps pueden quedar importados en el mismo
    proceso (app.py importa de app/__init__.py).
    """
    # El proyecto no sirve descargas (as_attachment), ni streaming, ni Range:
    # el unico send_from_directory es /favicon.ico, cuyo image/x-icon queda
    # fuera del alcance util. Por eso no hay que excluir rutas a mano.
    #
    # Nota sobre BREACH: comprimir HTML que lleva el token CSRF es el escenario
    # clasico del ataque. Flask-WTF lo mitiga de origen porque vuelve a salar
    # el token en cada peticion, asi que el texto cifrado cambia y la longitud
    # comprimida no filtra el secreto.
    Compress(app)
