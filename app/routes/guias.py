"""Guias publicas: el topic cluster de contenidos de jemPOS.

La landing es la pagina pilar; cada guia ataca una busqueda concreta de dueños
de tiendas (cuadre de caja, inventario, contabilidad) y enlaza a las demas y a
la landing. Asi el enlazado interno forma el cluster.

Los metadatos viven aqui y el cuerpo en templates/guias/<clave>.html. La
plantilla base (guias/base_guia.html) pinta SIEMPRE, en este orden: el parrafo
que responde la busqueda (`intro`), el CTA y los 5 puntos clave (`puntos`).
Ninguna guia puede saltarse esa estructura porque no la escribe ella.

Reglas por guia (las verifica scripts/check_seo_activos.py):
  * `titulo` va al <title> y genera el slug; `h1` tiene que ser distinto.
  * Maximo 3 listas o tablas dentro del <article>, contando los 5 puntos.
  * `descripcion` unica, 120-160 caracteres.
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template, url_for

from app.security import cerrar_sesion_publica
from app.utils.helpers import slugify

guias_bp = Blueprint("guias_bp", __name__, url_prefix="/guias")

_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

GUIAS: list[dict] = [
    {
        "clave": "cuadre_caja",
        "titulo": "Cómo hacer el cuadre de caja diario de tu negocio",
        "h1": "Cuadre de caja: el paso a paso para cerrar el día sin faltantes",
        "descripcion": (
            "Aprende a hacer el cuadre de caja diario con una fórmula simple: base, "
            "ventas, abonos y gastos. Con ejemplo resuelto y causas de descuadre."
        ),
        "intro": (
            "Hacer el cuadre de caja es comparar el efectivo que cuentas al cerrar con "
            "el que debería haber según los movimientos del día. La cuenta es: base "
            "inicial + ventas en efectivo + abonos de fiados en efectivo − gastos "
            "pagados con plata de la caja. Si el resultado coincide con lo que "
            "cuentas, la caja está cuadrada; si no, la diferencia es un sobrante o "
            "un faltante que hay que explicar."
        ),
        "cta": "Cuadra tu caja automáticamente con jemPOS",
        "puntos": (
            "Cuadrar es comparar el efectivo contado con el efectivo esperado.",
            "Efectivo esperado = base + ventas en efectivo + abonos en efectivo − gastos de caja.",
            "Las ventas por Nequi, Daviplata o tarjeta no se cuentan con los billetes.",
            "Anota cada gasto en el momento: olvidarlo es de los descuadres más comunes.",
            "Cierra cada turno por separado y deja claro quién abrió y quién cerró.",
        ),
        "publicada": "2026-09-25",
        "actualizada": "2026-09-25",
    },
    {
        "clave": "inventario",
        "titulo": "Control de inventario para tiendas pequeñas: guía práctica",
        "h1": "Cómo controlar el inventario de tu tienda sin conteos eternos",
        "descripcion": (
            "Guía práctica de control de inventario para tiendas pequeñas: registra "
            "entradas y salidas, calcula el stock mínimo y no te quedes sin producto."
        ),
        "intro": (
            "Controlar el inventario de una tienda pequeña es saber en todo momento "
            "cuántas unidades tienes de cada producto, cuáles se están agotando y "
            "cuáles no se venden. Se logra con dos hábitos: registrar toda la "
            "mercancía que entra y descontar cada venta en el momento. Con esos "
            "datos defines un stock mínimo por producto y reaccionas antes de "
            "quedarte sin él."
        ),
        "cta": "Prueba jemPOS y controla tu inventario",
        "puntos": (
            "Registra toda la mercancía que entra, sin excepción.",
            "Descuenta las ventas en el momento, no al final del día.",
            "Define un stock mínimo para cada producto que vendes seguido.",
            "Revisa cada mes lo que no rota: es plata quieta en el estante.",
            "Haz conteos físicos por categoría, no de toda la tienda a la vez.",
        ),
        "publicada": "2026-09-25",
        "actualizada": "2026-09-25",
    },
    {
        "clave": "contabilidad",
        "titulo": "Contabilidad para tiendas pequeñas: guía básica",
        "h1": "Cómo llevar las cuentas de tu negocio sin ser contador",
        "descripcion": (
            "Contabilidad básica para tu tienda: registra ventas, gastos y fiados, "
            "calcula la ganancia real y separa la plata del negocio de la personal."
        ),
        "intro": (
            "La contabilidad básica de una tienda pequeña se resume en registrar "
            "todos los días tres cosas: lo que vendes, lo que gastas y lo que te "
            "quedan debiendo. Con esos datos calculas la ganancia real —ventas menos "
            "el costo de la mercancía menos los gastos— y sabes si el negocio gana o "
            "pierde plata. Para declarar impuestos sigues necesitando un contador, "
            "pero estas cuentas son justo la base que te va a pedir."
        ),
        "cta": "Lleva las cuentas de tu negocio con jemPOS",
        "puntos": (
            "Anota cada venta y cada gasto el mismo día.",
            "Ganancia neta = ventas − costo de la mercancía − gastos.",
            "Los fiados son plata tuya en la calle: regístralos con nombre y fecha.",
            "Separa la plata del negocio de la de la casa.",
            "Revisa ventas, gastos y cartera una vez por semana.",
        ),
        "publicada": "2026-09-25",
        "actualizada": "2026-09-25",
    },
]

for _g in GUIAS:
    # ponytail: el slug sale del titulo. Si cambias el titulo de una guia ya
    # indexada, cambia su URL: fija aqui el slug viejo o añade un redirect 301.
    _g["slug"] = slugify(_g["titulo"])
    _g["plantilla"] = f"guias/{_g['clave']}.html"

_POR_SLUG = {g["slug"]: g for g in GUIAS}
assert len(_POR_SLUG) == len(GUIAS), "dos guias generan el mismo slug"


def fecha_legible(iso: str) -> str:
    anio, mes, dia = (int(x) for x in iso.split("-"))
    return f"{dia} de {_MESES[mes - 1]} de {anio}"


_POR_CLAVE = {g["clave"]: g for g in GUIAS}


def url_guia(clave: str) -> str:
    """URL de una guia por su clave: los enlaces internos no dependen del slug."""
    return url_for("guias_bp.guia", slug=_POR_CLAVE[clave]["slug"])


@guias_bp.app_context_processor
def _inyectar_guias():
    # La landing (pagina pilar) enlaza a todas las guias desde su seccion propia.
    return {"guias": GUIAS, "url_guia": url_guia}


@guias_bp.get("/")
def indice():
    cerrar_sesion_publica()
    return render_template("guias/indice.html")


@guias_bp.get("/<slug>")
def guia(slug: str):
    g = _POR_SLUG.get(slug)
    if g is None:
        abort(404)
    cerrar_sesion_publica()
    url = url_for("guias_bp.guia", slug=slug, _external=True)
    landing = url_for("landing", _external=True)
    jsonld = [
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": g["h1"],
            "description": g["descripcion"],
            "datePublished": g["publicada"],
            "dateModified": g["actualizada"],
            "inLanguage": "es-CO",
            "mainEntityOfPage": url,
            "image": url_for("static", filename="img/punto-de-venta-jempos.jpg", _external=True),
            "author": {"@type": "Organization", "name": "jemPOS", "url": landing},
            "publisher": {
                "@type": "Organization",
                "name": "jemPOS",
                "logo": {
                    "@type": "ImageObject",
                    "url": url_for("static", filename="img/favicon-192.png", _external=True),
                },
            },
        },
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Inicio", "item": landing},
                {"@type": "ListItem", "position": 2, "name": "Guías",
                 "item": url_for("guias_bp.indice", _external=True)},
                {"@type": "ListItem", "position": 3, "name": g["titulo"], "item": url},
            ],
        },
    ]
    return render_template(
        g["plantilla"],
        guia=g,
        jsonld=jsonld,
        relacionadas=[x for x in GUIAS if x is not g],
        fecha=fecha_legible(g["actualizada"]),
    )
