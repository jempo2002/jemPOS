"""Rutas de rastreo e indexacion: /robots.txt y /sitemap.xml.

Blueprint propio y sin url_prefix, porque los rastreadores solo buscan estos dos
archivos en la raiz del dominio.

Las dos listas de abajo son la unica fuente de verdad: si una URL publica entra
al sitemap, no puede estar bloqueada en robots.txt y viceversa. El chequeo
scripts/check_seo_activos.py cruza ambas contra el mapa de rutas real de Flask
para que no se desincronicen al añadir pantallas.
"""

from __future__ import annotations

import json
import os

from flask import Blueprint, Response, current_app, send_from_directory, url_for

seo_bp = Blueprint("seo_bp", __name__)

# Fecha que se publica como <lastmod>. Se sube a mano cuando cambia el contenido
# publico: usar la mtime de los archivos la movería en cada despliegue aunque no
# hubiera cambiado nada, y eso le enseña al rastreador a desconfiar del dato.
FECHA_ACTUALIZACION = "2026-09-22"

# URLs publicas indexables: endpoint -> (prioridad, frecuencia de cambio).
# La landing va primera y con prioridad 1.0; las legales son contenido estable.
#
# Se lista 'landing' (/landing) y NO la raiz '/': la raiz responde 302 hacia
# /landing, y meter una redireccion en el sitemap es un error de SEO (el
# rastreador gasta una peticion para nada y la senal se diluye). La URL
# canonica del <head> del landing apunta a /landing, asi que las dos coinciden.
# Si algun dia la landing pasa a servirse directamente en '/', hay que cambiar
# este endpoint y el canonical a la vez.
PAGINAS_PUBLICAS: tuple[tuple[str, str, str], ...] = (
    ("landing", "1.0", "weekly"),
    ("auth.registro", "0.8", "monthly"),
    ("legal_bp.aviso_legal", "0.3", "yearly"),
    ("legal_bp.politica_privacidad", "0.3", "yearly"),
)

# Prefijos que el rastreador no debe pedir: area privada, endpoints de API y
# pantallas de sesion. No aportan nada al indice y gastan presupuesto de rastreo.
RUTAS_BLOQUEADAS: tuple[str, ...] = (
    "/login",
    "/logout",
    "/olvide_password",
    "/olvide-password",
    "/reset_password/",
    "/reset-password/",
    "/dashboard",
    "/perfil",
    "/panel-master",
    "/servicio-suspendido",
    "/pos/",
    "/inventario/",
    "/api/",
    "/health",
)


@seo_bp.get("/robots.txt")
def robots_txt():
    """robots.txt como text/plain (si se sirve como HTML, Google lo ignora)."""
    # Solo ASCII: los analizadores de robots.txt son orientados a bytes y un
    # caracter no ASCII en un comentario no aporta nada y puede confundirlos.
    lineas = [
        "# robots.txt de jemPOS - punto de venta y gestion integral",
        "# El sitemap se declara al final de este archivo.",
        "User-agent: *",
        # /static/ se permite a proposito: si se bloquea, Google no puede
        # descargar el CSS ni el JS, renderiza la pagina rota y la penaliza.
        "Allow: /static/",
    ]
    lineas += [f"Disallow: {ruta}" for ruta in RUTAS_BLOQUEADAS]
    lineas += [
        "",
        f"Sitemap: {url_for('seo_bp.sitemap_xml', _external=True)}",
        "",
    ]

    return Response("\n".join(lineas), mimetype="text/plain")


@seo_bp.get("/sitemap.xml")
def sitemap_xml():
    """sitemap.xml segun el protocolo sitemaps.org 0.9."""
    urls = []
    for endpoint, prioridad, frecuencia in PAGINAS_PUBLICAS:
        # url_for escapa el valor y ProxyFix (app/security.py) garantiza el
        # esquema https detras del proxy: nada de construir URLs a mano.
        loc = url_for(endpoint, _external=True)
        urls.append(
            "  <url>\n"
            f"    <loc>{_escapar(loc)}</loc>\n"
            f"    <lastmod>{FECHA_ACTUALIZACION}</lastmod>\n"
            f"    <changefreq>{frecuencia}</changefreq>\n"
            f"    <priority>{prioridad}</priority>\n"
            "  </url>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    return Response(xml, mimetype="application/xml")


@seo_bp.get("/favicon.ico")
def favicon_ico():
    """Sirve el .ico desde la raiz.

    Los navegadores piden /favicon.ico por su cuenta, sin mirar el <link> del
    HTML. Sin esta ruta cada visita deja un 404 en el log y en la consola,
    aunque las etiquetas del <head> apunten bien a /static/img/.
    """
    return send_from_directory(
        os.path.join(current_app.static_folder, "img"),
        "favicon.ico",
        mimetype="image/x-icon",
        max_age=60 * 60 * 24 * 30,
    )


@seo_bp.get("/site.webmanifest")
def site_webmanifest():
    """Manifiesto minimo: da sentido al icono de 192 px al instalar en Android."""
    manifest = {
        "name": "jemPOS",
        "short_name": "jemPOS",
        "description": "Punto de venta y gestion integral para tu negocio.",
        "lang": "es",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f8fafc",
        "theme_color": "#3b82f6",
        "icons": [
            {"src": url_for("static", filename="img/favicon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="img/favicon.svg"), "sizes": "any", "type": "image/svg+xml"},
        ],
    }
    return Response(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        mimetype="application/manifest+json",
    )


# ══════════════════════════════════════════════════════════════
# DATOS ESTRUCTURADOS (JSON-LD)
# ══════════════════════════════════════════════════════════════

# TODO ANTES DE PUBLICAR: reemplazar por los datos reales de contacto.
# example.com esta reservado por IANA para documentacion y nunca podra ser un
# dominio real, y el telefono es un patron obviamente falso. Se usan a proposito:
# si Google llegara a mostrar la ficha antes del reemplazo, no expone a nadie a
# un numero o correo equivocado.
CONTACTO_PLACEHOLDER = {
    "telefono": "+57-000-0000000",
    "correo": "contacto@example.com",
}


@seo_bp.app_context_processor
def _inyectar_jsonld():
    """Expone `jsonld_landing()` a las plantillas.

    Se inyecta como funcion, no como diccionario ya construido: asi solo se
    calcula en la plantilla que lo usa y no en cada render del area POS.
    """
    return {"jsonld_landing": datos_estructurados_landing}


def datos_estructurados_landing() -> list[dict]:
    """Grafo JSON-LD del landing: la aplicacion y la organizacion que la publica.

    Se devuelve como estructura de Python y la plantilla lo serializa con el
    filtro `tojson` de Jinja. Nunca se escribe el JSON a mano en el HTML: tojson
    escapa `<`, `>`, `&` y las comillas, que es justo lo que evita que un
    apostrofo en un texto rompa el bloque <script>.

    Sin `aggregateRating` a proposito: inventar valoraciones que no existen
    incumple las politicas de Google y puede costar una accion manual.
    """
    url_landing = url_for("landing", _external=True)
    logo = url_for("static", filename="img/favicon-192.png", _external=True)

    organizacion = {
        "@type": "Organization",
        "@id": f"{url_landing}#organizacion",
        "name": "jemPOS",
        "url": url_landing,
        "logo": logo,
        "description": (
            "Desarrolladores de jemPOS, sistema de punto de venta y gestion "
            "integral en la nube para micro, pequenas y medianas empresas."
        ),
        "areaServed": {"@type": "Country", "name": "Colombia"},
        "contactPoint": {
            "@type": "ContactPoint",
            "contactType": "customer support",
            "telephone": CONTACTO_PLACEHOLDER["telefono"],
            "email": CONTACTO_PLACEHOLDER["correo"],
            "availableLanguage": ["es"],
        },
    }

    aplicacion = {
        "@type": "SoftwareApplication",
        "@id": f"{url_landing}#aplicacion",
        "name": "jemPOS",
        "url": url_landing,
        "applicationCategory": "BusinessApplication",
        "applicationSubCategory": "Point of Sale",
        "operatingSystem": "Web (cualquier navegador moderno)",
        "inLanguage": "es-CO",
        "description": (
            "Sistema de punto de venta y gestion integral: facturacion, control "
            "de inventario en tiempo real, cartera de fiados, cuentas por pagar, "
            "gastos, turnos de caja y reportes contables automaticos."
        ),
        "featureList": [
            "Punto de venta desde el celular",
            "Control de inventario con alertas de stock",
            "Cartera: cuentas por cobrar y por pagar",
            "Turnos de caja y control de personal",
            "Reportes contables automaticos",
            "Listas de precios mayoristas para clientes B2B",
        ],
        "screenshot": url_for("static", filename="img/og-cover.jpg", _external=True),
        "publisher": {"@id": f"{url_landing}#organizacion"},
        # Los precios coinciden con la seccion #precios del landing: Google
        # exige que los datos estructurados reflejen el contenido visible.
        "offers": {
            "@type": "AggregateOffer",
            "priceCurrency": "COP",
            "lowPrice": "49900",
            "highPrice": "99900",
            "offerCount": "2",
            "availability": "https://schema.org/InStock",
        },
    }

    return [
        {"@context": "https://schema.org", **aplicacion},
        {"@context": "https://schema.org", **organizacion},
    ]


def _escapar(valor: str) -> str:
    """Escapa los cinco caracteres que XML no admite dentro de un nodo.

    Una URL con '&' (por ejemplo con query string) rompe el XML si va cruda, y
    el sitemap entero queda invalido para el rastreador.
    """
    return (
        str(valor)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
