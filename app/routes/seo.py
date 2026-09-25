"""Rutas de rastreo e indexacion: /robots.txt, /sitemap.xml y /sitemap.txt.

Blueprint propio y sin url_prefix, porque los rastreadores solo buscan estos dos
archivos en la raiz del dominio.

Las dos listas de abajo son la unica fuente de verdad: si una URL publica entra
al sitemap, no puede estar bloqueada en robots.txt y viceversa. El chequeo
scripts/check_seo_activos.py cruza ambas contra el mapa de rutas real de Flask
para que no se desincronicen al añadir pantallas.
"""

from __future__ import annotations

import json
import math
import os
import re

from flask import Blueprint, Response, current_app, send_from_directory, url_for

from app.routes.guias import GUIAS
from app.utils.helpers import fmt_money

seo_bp = Blueprint("seo_bp", __name__)

# Fecha que se publica como <lastmod>. Se sube a mano cuando cambia el contenido
# publico: usar la mtime de los archivos la movería en cada despliegue aunque no
# hubiera cambiado nada, y eso le enseña al rastreador a desconfiar del dato.
FECHA_ACTUALIZACION = "2026-09-25"

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
    ("guias_bp.indice", "0.7", "weekly"),
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

# Paginacion: /listado?page=2 es el mismo contenido que la pagina 1 con otro
# orden, contenido duplicado a ojos del rastreador. Hoy solo paginan las APIs
# privadas (ya bloqueadas); esto cubre cualquier listado publico futuro. El
# comodin * lo entienden Google y Bing. No tocan /static/: ningun CSS o JS
# lleva ?page=.
PATRONES_PAGINACION: tuple[str, ...] = ("/*?page=", "/*&page=", "/page/")


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
    lineas += [f"Disallow: {ruta}" for ruta in RUTAS_BLOQUEADAS + PATRONES_PAGINACION]
    lineas += [
        "",
        f"Sitemap: {url_for('seo_bp.sitemap_xml', _external=True)}",
        "",
    ]

    return Response("\n".join(lineas), mimetype="text/plain")


# Endpoints que solo entran al sitemap cuando su contenido esta completo.
# Las paginas legales se sirven noindex mientras falte identificar al
# responsable del tratamiento (ver EMPRESA en app/routes/legal.py), y anunciar
# en el sitemap una URL que lleva noindex es una contradiccion que Search
# Console reporta como error.
_ENDPOINTS_LEGALES = ("legal_bp.aviso_legal", "legal_bp.politica_privacidad")


def paginas_indexables() -> tuple[tuple[str, str, str], ...]:
    """PAGINAS_PUBLICAS sin las que de momento se sirven noindex.

    El import va dentro de la funcion a proposito: a nivel de modulo crearia un
    ciclo si legal.py llegara a necesitar algo de seo.py.
    """
    from app.routes.legal import empresa_incompleta

    if not empresa_incompleta():
        return PAGINAS_PUBLICAS
    return tuple(p for p in PAGINAS_PUBLICAS if p[0] not in _ENDPOINTS_LEGALES)


def urls_indexables() -> list[tuple[str, str, str, str]]:
    """(loc, lastmod, prioridad, frecuencia) de todo lo indexable.

    Unica fuente de los dos sitemaps. url_for escapa el valor y ProxyFix
    (app/security.py) garantiza el esquema https detras del proxy: nada de
    construir URLs a mano. Ninguna lleva query string (?page= incluido).
    """
    urls = [
        (url_for(endpoint, _external=True), FECHA_ACTUALIZACION, prioridad, frecuencia)
        for endpoint, prioridad, frecuencia in paginas_indexables()
    ]
    urls += [
        (url_for("guias_bp.guia", slug=g["slug"], _external=True), g["actualizada"], "0.7", "monthly")
        for g in GUIAS
    ]
    return urls


@seo_bp.get("/sitemap.xml")
def sitemap_xml():
    """sitemap.xml segun el protocolo sitemaps.org 0.9."""
    urls = []
    for loc, lastmod, prioridad, frecuencia in urls_indexables():
        urls.append(
            "  <url>\n"
            f"    <loc>{_escapar(loc)}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
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


@seo_bp.get("/sitemap.txt")
def sitemap_txt():
    """Respaldo en texto plano: una URL absoluta por linea, UTF-8 (formato que
    aceptan Google y Bing). No se declara en robots.txt para no anunciar dos
    veces las mismas URLs: se envia a mano en Search Console si hace falta."""
    return Response("\n".join(u[0] for u in urls_indexables()) + "\n", mimetype="text/plain")


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

# Datos de contacto reales. Fuente unica de verdad: los usan el JSON-LD de esta
# pagina y el footer del landing (via el context processor de abajo), asi que un
# cambio de numero o de correo se hace aqui una sola vez.
#
# El telefono va en formato E.164 (+57 y 10 digitos, sin espacios ni guiones):
# es lo que pide schema.org y lo que entiende wa.me. La version con espacios es
# solo para mostrar.
CONTACTO = {
    "telefono": "+573106152268",
    "telefono_visible": "+57 310 615 2268",
    "whatsapp": "https://wa.me/573106152268",
    "correo": "jemposoporte@gmail.com",
    "instagram": "https://www.instagram.com/jempos__/",
    "instagram_usuario": "@jempos__",
}


# Oferta comercial. Fuente unica: la seccion #precios del landing, el FAQ y
# las ofertas del JSON-LD leen estas constantes (Google sanciona los datos
# estructurados que no coinciden con lo visible). Precios en COP.
# La implementacion es obligatoria para todo cliente nuevo: se paga una vez.
MENSUALIDAD = 65000
IMPLEMENTACION: tuple[tuple[str, int], ...] = (
    ("Hasta 250 productos", 250000),
    ("De 251 a 400 productos", 350000),
    ("401 productos o más", 500000),
)
# "Menos de $2.200 al dia": la mensualidad entre 30, redondeada hacia arriba a
# la centena para que la frase siga siendo cierta.
MENSUALIDAD_POR_DIA = math.ceil(MENSUALIDAD / 30 / 100) * 100

# Horario de atencion (soporte por WhatsApp y correo), formato schema.org.
# Fuente unica: sale en el JSON-LD (contactPoint.hoursAvailable), en el footer
# y en la respuesta de soporte del FAQ, siempre derivado de esta cadena.
HORARIO_ATENCION = "Mo-Sa 09:00-21:00"

_DIAS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
_DIAS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_DIAS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _partes_horario(horario: str) -> tuple[list[int], str, str]:
    """"Mo-Sa 09:00-21:00" -> ([0..5], "09:00", "21:00")."""
    dias, horas = horario.split()
    desde, hasta = (_DIAS.index(d) for d in dias.split("-"))
    abre, cierra = horas.split("-")
    return list(range(desde, hasta + 1)), abre, cierra


def _hora_12(hhmm: str) -> str:
    hh, mm = (int(x) for x in hhmm.split(":"))
    # Espacios no separables: "9:00 a. m." nunca se parte en dos lineas.
    return f"{(hh - 1) % 12 + 1}:{mm:02d} {'a. m.' if hh < 12 else 'p. m.'}"


def horario_schema(horario: str) -> dict:
    dias, abre, cierra = _partes_horario(horario)
    return {
        "@type": "OpeningHoursSpecification",
        "dayOfWeek": [_DIAS_EN[d] for d in dias],
        "opens": abre,
        "closes": cierra,
    }


def horario_visible(horario: str) -> str:
    dias, abre, cierra = _partes_horario(horario)
    return f"{_DIAS_ES[dias[0]]} a {_DIAS_ES[dias[-1]]}, de {_hora_12(abre)} a {_hora_12(cierra)}"


CONTACTO["horario"] = horario_visible(HORARIO_ATENCION)

# Preguntas frecuentes del landing. Fuente unica: la seccion #faq se pinta con
# esta lista y el FAQPage del JSON-LD sale de la misma, asi que Google nunca ve
# una respuesta distinta a la visible. Texto plano (sin HTML): va igual al DOM
# y al JSON. Cada respuesta se apoya en algo que la app hace de verdad o que
# dicen los textos legales.
PREGUNTAS_FRECUENTES: tuple[dict, ...] = (
    {
        "pregunta": "¿Necesito internet para usar jemPOS?",
        "respuesta": (
            "Sí, jemPOS funciona en la nube. Pero si la conexión se cae en plena "
            "venta, la caja guarda la venta en tu celular y la sincroniza sola "
            "cuando vuelve la señal, así que no pierdes ventas por un corte."
        ),
    },
    {
        "pregunta": "¿Qué necesito para empezar?",
        "respuesta": (
            "Un celular, tablet o computador con navegador. No hay que instalar "
            "nada ni comprar equipos: la cámara del celular sirve como lector de "
            "código de barras."
        ),
    },
    {
        "pregunta": "¿Mis datos y los de mi negocio están seguros?",
        "respuesta": (
            "Las contraseñas se guardan cifradas con hash, todo viaja por HTTPS, "
            "la sesión se cierra por inactividad y cada negocio solo ve su propia "
            "información. Los accesos quedan registrados en una auditoría interna."
        ),
    },
    {
        "pregunta": "¿Puedo cancelar cuando quiera?",
        "respuesta": (
            f"Sí. Escríbenos a {CONTACTO['correo']} y cancelamos tu cuenta. Después "
            "tienes 30 días para pedir una copia de tu información antes de que "
            "se elimine."
        ),
    },
    {
        "pregunta": "¿Cuánto cuesta jemPOS?",
        "respuesta": (
            f"La mensualidad vale {fmt_money(MENSUALIDAD)} e incluye todo el sistema. "
            "Al empezar se paga una sola vez la implementación, en la que cargamos "
            f"tu inventario: {fmt_money(IMPLEMENTACION[0][1])} si tienes hasta 250 "
            f"productos, {fmt_money(IMPLEMENTACION[1][1])} de 251 a 400 y "
            f"{fmt_money(IMPLEMENTACION[2][1])} con 401 o más."
        ),
    },
    {
        "pregunta": "¿Por qué se paga la implementación?",
        "respuesta": (
            "Porque registramos por ti todos tus productos, con precio de compra y "
            "de venta, categoría y stock mínimo. Digitar cientos de productos a mano "
            "toma días y un error ahí descuadra el inventario desde el principio; "
            "así empiezas a vender con todo listo desde el primer día."
        ),
    },
    {
        "pregunta": "¿Cómo me dan soporte?",
        "respuesta": (
            f"Por WhatsApp al {CONTACTO['telefono_visible']} y por correo a "
            f"{CONTACTO['correo']}, de {CONTACTO['horario']}, y te ayudamos a "
            "configurar tu negocio desde el primer día."
        ),
    },
)

# Google Analytics 4 y Search Console. Vacios = no se inyecta nada.
_GA_ID_RE = re.compile(r"^G-[A-Z0-9]{4,20}$")

# CSP de las paginas publicas (landing, legales, guias). Con GA activo se abren
# solo los dominios que Google documenta para gtag.js; sin GA queda 'self'.
# Inter desde Google Fonts: la misma tipografia que las vistas del POS.
_CSP_BASE = (
    "default-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
    "; style-src 'self' https://fonts.googleapis.com"
    "; font-src 'self' https://fonts.gstatic.com"
)
_CSP_GA = (
    "; script-src 'self' https://*.googletagmanager.com"
    "; img-src 'self' https://*.google-analytics.com https://*.googletagmanager.com"
    "; connect-src 'self' https://*.google-analytics.com"
    " https://*.analytics.google.com https://*.googletagmanager.com"
)


def analitica() -> dict:
    """IDs de GA4 y Search Console desde el entorno. Un GA mal escrito se
    ignora: mejor sin analitica que con un <script> apuntando a basura."""
    ga = (os.getenv("GA_MEASUREMENT_ID") or "").strip().upper()
    return {
        "ga_id": ga if _GA_ID_RE.match(ga) else "",
        "gsc": (os.getenv("GOOGLE_SITE_VERIFICATION") or "").strip(),
    }


@seo_bp.app_context_processor
def _inyectar_jsonld():
    """Expone JSON-LD, contacto, FAQ, analitica y la CSP publica a las plantillas.

    El JSON-LD se inyecta como funcion, no como diccionario ya construido: asi
    solo se calcula en la plantilla que lo usa y no en cada render del area POS.
    `contacto` y `faq` si van tal cual porque son constantes del modulo.
    """
    datos_analitica = analitica()
    return {
        "jsonld_landing": datos_estructurados_landing,
        "contacto": CONTACTO,
        "faq": PREGUNTAS_FRECUENTES,
        "precios": {
            "mensualidad": MENSUALIDAD,
            "por_dia": MENSUALIDAD_POR_DIA,
            "implementacion": IMPLEMENTACION,
        },
        "cop": fmt_money,
        "analitica": datos_analitica,
        "csp_publica": _CSP_BASE + (_CSP_GA if datos_analitica["ga_id"] else ""),
    }


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
        # sameAs vincula los perfiles oficiales con esta ficha: es como Google
        # confirma que la cuenta de Instagram y el sitio son la misma entidad.
        "sameAs": [CONTACTO["instagram"]],
        "contactPoint": {
            "@type": "ContactPoint",
            "contactType": "customer support",
            "telephone": CONTACTO["telefono"],
            "email": CONTACTO["correo"],
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
        "screenshot": url_for("static", filename="img/punto-de-venta-jempos.jpg", _external=True),
        "publisher": {"@id": f"{url_landing}#organizacion"},
        # Los precios coinciden con la seccion #precios del landing: Google
        # exige que los datos estructurados reflejen el contenido visible.
        "offers": [
            {
                "@type": "Offer",
                "name": "Mensualidad jemPOS",
                "price": str(MENSUALIDAD),
                "priceCurrency": "COP",
                "availability": "https://schema.org/InStock",
                "priceSpecification": {
                    "@type": "UnitPriceSpecification",
                    "price": str(MENSUALIDAD),
                    "priceCurrency": "COP",
                    "referenceQuantity": {"@type": "QuantitativeValue", "value": 1, "unitCode": "MON"},
                },
            },
            *(
                {
                    "@type": "Offer",
                    "name": f"Implementación de inventario: {rango[0].lower() + rango[1:]} (pago único)",
                    "price": str(precio),
                    "priceCurrency": "COP",
                    "availability": "https://schema.org/InStock",
                }
                for rango, precio in IMPLEMENTACION
            ),
        ],
    }

    # Sin LocalBusiness a proposito: jemPOS opera 100% en la nube, y Google
    # exige una direccion fisica visitable para las fichas locales. El horario
    # es de atencion al cliente, asi que va en el ContactPoint, no en la
    # organizacion (openingHours es propiedad de LocalBusiness).
    organizacion["contactPoint"]["hoursAvailable"] = horario_schema(HORARIO_ATENCION)

    faq = {
        "@type": "FAQPage",
        "@id": f"{url_landing}#faq",
        "mainEntity": [
            {
                "@type": "Question",
                "name": p["pregunta"],
                "acceptedAnswer": {"@type": "Answer", "text": p["respuesta"]},
            }
            for p in PREGUNTAS_FRECUENTES
        ],
    }

    return [
        {"@context": "https://schema.org", **aplicacion},
        {"@context": "https://schema.org", **organizacion},
        {"@context": "https://schema.org", **faq},
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
