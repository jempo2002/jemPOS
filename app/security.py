"""security.py — cabeceras de seguridad y HTTPS forzado.

Vive aparte porque el proyecto arranca por dos caminos (`app/__init__.py` con
create_app, que es el que usa run.py, y el `app.py` heredado): los dos llaman a
init_security(app) para no duplicar la configuracion.

Hace dos cosas:

  1) Flask-Talisman: redirige HTTP -> HTTPS, manda HSTS y marca la cookie de
     sesion como Secure. Todo esto se apaga en desarrollo local, porque con
     force_https activo el servidor de pruebas en http://127.0.0.1:5000 entra en
     un bucle de redirecciones y la cookie Secure nunca se guarda.

  2) Cabeceras anti-cache en las respuestas autenticadas. Hace falta para que
     cerrar sesion sea real: `session.clear()` invalida la sesion en el
     servidor, pero si la pagina protegida quedo en el cache del historial, el
     boton "atras" del navegador la vuelve a pintar sin pedir credenciales.
     Con `no-store` el navegador tiene que volver a pedirla y el servidor
     redirige al login.
"""

from __future__ import annotations

import os

from flask import request, session
from flask_talisman import Talisman
from werkzeug.middleware.proxy_fix import ProxyFix

# Valores de FLASK_ENV que significan "estoy en mi maquina".
_ENTORNOS_DEV = {"development", "dev", "local", "testing", "test"}

# Rutas publicas: su respuesta si se puede cachear (no depende de la sesion).
# Los cuatro archivos de la segunda linea son endpoints para maquinas: el
# navegador pide /favicon.ico en cada pagina, asi que marcarlo no-store lo
# obligaria a redescargarlo siempre y anularia su propio cache de 30 dias.
_PREFIJOS_PUBLICOS = (
    "/static/", "/landing", "/legal/", "/guias/",
    "/favicon.ico", "/robots.txt", "/sitemap.xml", "/sitemap.txt", "/site.webmanifest",
)


def cerrar_sesion_publica() -> None:
    """Destruye la sesion en una ruta publica, conservando los flashes.

    Flask guarda los mensajes flash DENTRO de la sesion, en la clave `_flashes`.
    Un `session.clear()` pelado en GET /login borraria el "Contrasena
    incorrecta" que acaba de poner el POST antes de redirigir, y el usuario
    veria el formulario en blanco sin saber que fallo. Igual con el
    "Cuenta creada exitosamente" de registro y con los avisos de permisos.

    Se conserva solo esa clave: nada de identidad (id_usuario, rol, id_tienda)
    sobrevive.
    """
    flashes = session.get("_flashes")
    session.clear()
    if flashes:
        session["_flashes"] = flashes


def es_desarrollo() -> bool:
    """True cuando corremos en local y NO hay que forzar HTTPS.

    Por defecto (sin variables) se asume produccion: es el lado seguro del
    error. Para desarrollo hay que declararlo con FLASK_ENV=development.
    """
    entorno = str(os.getenv("FLASK_ENV") or "").strip().lower()
    if entorno in _ENTORNOS_DEV:
        return True
    for bandera in ("FLASK_DEBUG", "DEBUG"):
        valor = str(os.getenv(bandera) or "").strip().lower()
        if valor in {"1", "true", "yes", "on"}:
            return True
    return False


def init_security(app) -> None:
    """Aplica Talisman y las cabeceras anti-cache sobre una app Flask."""
    desarrollo = es_desarrollo()

    if not desarrollo:
        # Detras de un proxy que termina TLS, Flask ve la peticion interna como
        # http y genera URLs absolutas con ese esquema. Sin esto quedarian mal:
        # el <link rel="canonical">, las etiquetas og:url y sobre todo el enlace
        # del correo de recuperacion de contrasena, que llegaria como http://.
        # ProxyFix reescribe el esquema y el host desde X-Forwarded-*.
        # Solo en produccion: en local no hay proxy y confiar en esas cabeceras
        # permitiria falsificarlas desde el navegador.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Una instancia de Talisman POR app, no un singleton de modulo: Talisman
    # guarda su configuracion (y `self.app`) en atributos de la instancia, asi
    # que un segundo init_app sobre el mismo objeto pisaria los ajustes de la
    # primera app. El proyecto arranca por dos caminos y ambos pueden quedar
    # importados en el mismo proceso.
    Talisman().init_app(
        app,
        # En produccion: HTTP -> HTTPS + HSTS + cookie Secure.
        force_https=not desarrollo,
        force_https_permanent=not desarrollo,
        strict_transport_security=not desarrollo,
        strict_transport_security_max_age=31536000,  # 1 anio
        strict_transport_security_include_subdomains=True,
        session_cookie_secure=not desarrollo,
        session_cookie_http_only=True,
        # Anti-clickjacking como cabecera HTTP real (el <meta> CSP del landing
        # no puede entregar frame-ancestors).
        frame_options="DENY",
        referrer_policy="strict-origin-when-cross-origin",
        # CSP deliberadamente en None: las vistas POS cargan Tailwind por CDN,
        # que necesita 'unsafe-eval' para compilar en el navegador, mas estilos
        # y scripts inline. Una CSP que los permita no aporta proteccion real
        # contra XSS y una que los bloquee rompe la aplicacion. Requisito previo
        # para activarla: sacar el CDN de Tailwind y compilar el CSS. El landing
        # mantiene su propia CSP restrictiva via <meta>.
        content_security_policy=None,
    )

    # Talisman solo pone Secure dentro de su before_request (perezoso). Se fija
    # aqui para que la config sea cierta desde el arranque.
    app.config["SESSION_COOKIE_SECURE"] = not desarrollo

    @app.after_request
    def _no_cachear_paginas_privadas(response):
        """Impide que el boton "atras" reviva una pagina de una sesion cerrada."""
        ruta = request.path or ""
        if ruta.startswith(_PREFIJOS_PUBLICOS):
            return response
        # Solo importa cuando la respuesta pudo depender de una sesion.
        if session or "id_usuario" in session:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    app.config["JEMPOS_DEV_MODE"] = desarrollo
