"""Chequeo de rastreo, datos estructurados e imagenes (auditoria 6-11).

No toca la base de datos: test client de Flask + lectura de archivos.

  1) /robots.txt: MIME, sitemap declarado, privado bloqueado, /static/ permitido.
  2) /sitemap.xml: MIME, XML valido, URLs reales y 200, coherencia con robots.
  3) JSON-LD del landing: JSON parseable, esquemas y precios que coinciden con
     el contenido visible.
  4) Favicons: etiquetas presentes, archivos servidos sin 404, apple-touch-icon.
  5) Imagenes: ninguna <img> sin alt en plantillas ni en el JS que genera HTML.
  6) Peso y dimensiones de static/img: detecta activos pesados o sobredimensionados.

    python scripts/check_seo_activos.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()
os.environ["FLASK_ENV"] = "development"

from PIL import Image  # noqa: E402

from app import create_app  # noqa: E402
from app.routes.seo import RUTAS_BLOQUEADAS, paginas_indexables  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = create_app()
app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)


# ══════════════════════════════════════════════════════════════
# 1) ROBOTS.TXT
# ══════════════════════════════════════════════════════════════
with app.test_client() as c:
    r = c.get("/robots.txt")
    assert r.status_code == 200, r.status_code
    # Servido como HTML, Google lo ignora por completo.
    assert r.mimetype == "text/plain", f"MIME incorrecto: {r.mimetype}"
    robots = r.get_data(as_text=True)

    assert "User-agent: *" in robots
    assert re.search(r"^Sitemap: https?://\S+/sitemap\.xml$", robots, re.M), "sitemap mal declarado"
    # Bloquear /static/ impide que Google renderice la pagina y la penaliza.
    assert "Allow: /static/" in robots
    assert "Disallow: /static/" not in robots, "bloquear /static/ rompe el renderizado en Google"
    # Un Disallow: / global dejaria el sitio entero fuera del indice.
    assert not re.search(r"^Disallow: /$", robots, re.M), "Disallow: / desindexa todo el sitio"

    for ruta in RUTAS_BLOQUEADAS:
        assert f"Disallow: {ruta}" in robots, f"falta bloquear {ruta}"

    # Las rutas privadas reales del mapa de Flask tienen que estar cubiertas.
    privadas = ("/dashboard", "/perfil", "/panel-master", "/pos/caja", "/inventario/", "/login")
    for ruta in privadas:
        cubierta = any(ruta.startswith(b.rstrip("/")) for b in RUTAS_BLOQUEADAS)
        assert cubierta, f"{ruta} no queda cubierta por ningun Disallow"

print("OK 1: robots.txt en text/plain, sitemap declarado, privado bloqueado, /static/ permitido")


# ══════════════════════════════════════════════════════════════
# 2) SITEMAP.XML
# ══════════════════════════════════════════════════════════════
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

with app.test_client() as c:
    r = c.get("/sitemap.xml")
    assert r.status_code == 200, r.status_code
    assert r.mimetype in ("application/xml", "text/xml"), f"MIME incorrecto: {r.mimetype}"
    xml = r.get_data(as_text=True)

    # Sintaxis: si no parsea, el rastreador descarta el sitemap entero.
    raiz = ET.fromstring(xml)
    assert raiz.tag == f"{NS}urlset", raiz.tag
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'), "falta la declaracion XML"

    entradas = raiz.findall(f"{NS}url")
    # paginas_indexables() y no PAGINAS_PUBLICAS: las legales salen del sitemap
    # mientras se sirvan noindex por datos del responsable sin completar.
    esperadas = paginas_indexables()
    assert len(entradas) == len(esperadas), (len(entradas), len(esperadas))

    locs = []
    for u in entradas:
        loc = u.find(f"{NS}loc").text
        lastmod = u.find(f"{NS}lastmod").text
        prioridad = u.find(f"{NS}priority").text
        frecuencia = u.find(f"{NS}changefreq").text

        assert loc and loc.startswith("http"), loc
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", lastmod), f"lastmod no es W3C date: {lastmod}"
        assert 0.0 <= float(prioridad) <= 1.0, prioridad
        assert frecuencia in {
            "always", "hourly", "daily", "weekly", "monthly", "yearly", "never",
        }, frecuencia
        locs.append(loc)

    assert len(set(locs)) == len(locs), f"URLs duplicadas en el sitemap: {locs}"

    # Cada URL listada tiene que existir y responder 200: un sitemap con 404 o
    # con redirecciones gasta presupuesto de rastreo y resta confianza.
    for loc in locs:
        ruta = "/" + loc.split("/", 3)[3] if loc.count("/") > 2 else "/"
        resp = c.get(ruta)
        assert resp.status_code == 200, f"{ruta} en el sitemap devuelve {resp.status_code}"

    # Coherencia: nada de anunciar en el sitemap lo que robots.txt bloquea.
    for loc in locs:
        ruta = "/" + loc.split("/", 3)[3] if loc.count("/") > 2 else "/"
        for bloqueada in RUTAS_BLOQUEADAS:
            assert not ruta.startswith(bloqueada.rstrip("/")) or ruta == "/", (
                f"{ruta} esta en el sitemap y bloqueada por '{bloqueada}'"
            )

    # Y las paginas del sitemap no pueden llevar noindex en su propio HTML.
    for loc in locs:
        ruta = "/" + loc.split("/", 3)[3] if loc.count("/") > 2 else "/"
        cuerpo = c.get(ruta).get_data(as_text=True)
        assert not re.search(r'name="robots"\s+content="noindex', cuerpo), (
            f"{ruta} esta en el sitemap pero su HTML dice noindex"
        )

print("OK 2: sitemap.xml en application/xml, XML valido, URLs en 200 y coherentes con robots")


# ══════════════════════════════════════════════════════════════
# 3) JSON-LD
# ══════════════════════════════════════════════════════════════
with app.test_client() as c:
    cuerpo = c.get("/landing").get_data(as_text=True)

bloques = re.findall(
    r'<script type="application/ld\+json">(.*?)</script>', cuerpo, re.S
)
assert len(bloques) == 1, f"se esperaba un bloque JSON-LD, hay {len(bloques)}"

# Si Jinja no escapa bien, aqui salta: es la prueba de "comillas rotas".
datos = json.loads(bloques[0])
assert isinstance(datos, list) and len(datos) == 2, type(datos)

por_tipo = {d["@type"]: d for d in datos}
assert set(por_tipo) == {"SoftwareApplication", "Organization"}, sorted(por_tipo)

for d in datos:
    assert d["@context"] == "https://schema.org", d.get("@context")

aplicacion = por_tipo["SoftwareApplication"]
organizacion = por_tipo["Organization"]

assert aplicacion["name"] == "jemPOS"
assert aplicacion["applicationCategory"] == "BusinessApplication"
assert aplicacion["url"].startswith("http")
assert len(aplicacion["featureList"]) >= 4
assert "punto de venta" in aplicacion["description"].lower()
# El publisher apunta al @id de la organizacion: el grafo tiene que cerrar.
assert aplicacion["publisher"]["@id"] == organizacion["@id"], (
    aplicacion["publisher"], organizacion["@id"]
)

# Los precios del JSON-LD deben coincidir con los visibles: Google sanciona
# los datos estructurados que no reflejan la pagina.
oferta = aplicacion["offers"]
assert oferta["priceCurrency"] == "COP", oferta
plantilla_landing = open(os.path.join(RAIZ, "templates", "landing.html"), encoding="utf-8").read()
for clave in ("lowPrice", "highPrice"):
    valor = int(oferta[clave])
    visible = f"{valor:,}".replace(",", ".")          # 49900 -> 49.900
    assert visible in plantilla_landing, f"{clave}={valor} no aparece como ${visible} en el landing"

# Sin valoraciones inventadas: incumple las politicas de Google.
assert "aggregateRating" not in aplicacion, "no se pueden declarar valoraciones inexistentes"
assert "review" not in aplicacion

assert organizacion["contactPoint"]["availableLanguage"] == ["es"]
assert organizacion["logo"].startswith("http")
# Contacto real, no placeholder: una ficha con example.com o un telefono de
# relleno indexada es peor que no tener ficha.
contacto_jsonld = organizacion["contactPoint"]
assert "example.com" not in contacto_jsonld["email"], contacto_jsonld["email"]
assert not re.fullmatch(r"\+?57-?0+", contacto_jsonld["telephone"].replace("-", "")), (
    contacto_jsonld["telephone"]
)
# E.164: schema.org y wa.me esperan el indicativo pegado, sin espacios ni guiones.
assert re.fullmatch(r"\+57\d{10}", contacto_jsonld["telephone"]), contacto_jsonld["telephone"]
assert organizacion["sameAs"], "falta sameAs con los perfiles oficiales"

print("OK 3: JSON-LD parseable, SoftwareApplication + Organization enlazados, precios coherentes")


# ══════════════════════════════════════════════════════════════
# 4) FAVICONS
# ══════════════════════════════════════════════════════════════
ICONOS = (
    "img/favicon.svg",
    "img/favicon-32.png",
    "img/favicon-192.png",
    "img/apple-touch-icon.png",
    "img/favicon.ico",
)
for rel in ICONOS:
    ruta = os.path.join(RAIZ, "static", *rel.split("/"))
    assert os.path.isfile(ruta), f"falta el archivo {rel}"
    assert os.path.getsize(ruta) > 0, f"{rel} esta vacio"

with app.test_client() as c:
    # Cada icono se sirve de verdad (esto es el 404 de la consola).
    for rel in ICONOS:
        r = c.get(f"/static/{rel}")
        assert r.status_code == 200, f"/static/{rel} -> {r.status_code}"

    # El navegador pide /favicon.ico por su cuenta, sin leer el <head>.
    r = c.get("/favicon.ico")
    assert r.status_code == 200, f"/favicon.ico -> {r.status_code}"
    assert "icon" in r.mimetype or "image" in r.mimetype, r.mimetype

    r = c.get("/site.webmanifest")
    assert r.status_code == 200, r.status_code
    manifest = json.loads(r.get_data(as_text=True))
    assert manifest["name"] == "jemPOS" and manifest["icons"], manifest

    # og:image: si apunta a un archivo que no existe, WhatsApp y X comparten el
    # enlace sin tarjeta. Es un 404 que no se ve en el navegador, solo al
    # compartir, asi que se comprueba aqui.
    for ruta_pagina in ("/landing", "/legal/aviso-legal", "/legal/politica-privacidad"):
        html_pagina = c.get(ruta_pagina).get_data(as_text=True)
        og = re.search(r'property="og:image" content="([^"]+)"', html_pagina)
        assert og, f"{ruta_pagina} sin og:image"
        ruta_img = "/" + og.group(1).split("/", 3)[3]
        assert c.get(ruta_img).status_code == 200, f"og:image de {ruta_pagina} da 404: {ruta_img}"

    # Open Graph pide 1200x630 para la tarjeta grande.
    portada = Image.open(os.path.join(RAIZ, "static", "img", "og-cover.jpg"))
    assert portada.size == (1200, 630), portada.size

# Estos endpoints son cacheables incluso con sesion abierta: el navegador pide
# /favicon.ico en cada pagina y marcarlo no-store lo hace redescargar siempre.
with app.test_client() as c:
    with c.session_transaction() as s:
        s.update(id_usuario=1, id_tienda=1, rol="Admin", nombre_completo="QA")
    for ruta in ("/favicon.ico", "/robots.txt", "/sitemap.xml", "/site.webmanifest"):
        cache = (c.get(ruta).headers.get("Cache-Control") or "").lower()
        assert "no-store" not in cache, f"{ruta} marcado no-store: {cache!r}"

    # Todas las plantillas con <head> propio declaran los iconos.
    PAGINAS = ["/landing", "/legal/aviso-legal", "/legal/politica-privacidad",
               "/login", "/registro", "/olvide_password"]
    for ruta in PAGINAS:
        cuerpo = c.get(ruta).get_data(as_text=True)
        assert 'rel="icon" type="image/svg+xml"' in cuerpo, f"{ruta} sin favicon SVG"
        assert 'rel="apple-touch-icon"' in cuerpo, f"{ruta} sin apple-touch-icon"
        assert 'rel="manifest"' in cuerpo, f"{ruta} sin manifest"

    # Tambien las privadas (mismo include compartido).
    with c.session_transaction() as s:
        s.update(id_usuario=1, id_tienda=1, rol="Admin", nombre_completo="QA")
    for ruta in ("/dashboard", "/pos/caja", "/pos/fiados", "/inventario/"):
        cuerpo = c.get(ruta).get_data(as_text=True)
        assert 'rel="apple-touch-icon"' in cuerpo, f"{ruta} sin apple-touch-icon"

# iOS pinta de negro la transparencia: el apple-touch-icon va sin canal alfa.
apple = Image.open(os.path.join(RAIZ, "static", "img", "apple-touch-icon.png"))
assert apple.mode == "RGB", f"apple-touch-icon con alfa ({apple.mode}): iOS lo pinta negro"
assert apple.size == (180, 180), apple.size

print("OK 4: los 5 iconos existen y se sirven, /favicon.ico responde, manifest valido")


# ══════════════════════════════════════════════════════════════
# 5) ALT EN TODAS LAS <img>
# ══════════════════════════════════════════════════════════════
# re.S es imprescindible: varias etiquetas del proyecto reparten sus atributos
# en tres lineas, y un escaneo linea a linea no las ve (ni para el alt ni para
# las dimensiones), dejando un hueco justo donde el revisor cree tener cobertura.
IMG = re.compile(r"<img\b[^>]*?>", re.I | re.S)
ALT = re.compile(r"\balt\s*=", re.I)

sin_alt: list[str] = []
decorativas = 0
descriptivas = 0


def revisar(ruta: str, contenido: str) -> None:
    global decorativas, descriptivas
    for m in IMG.finditer(contenido):
        tag = m.group(0)
        linea_num = contenido.count("\n", 0, m.start()) + 1
        resumen = " ".join(tag.split())[:90]
        if not ALT.search(tag):
            sin_alt.append(f"{ruta}:{linea_num}  {resumen}")
            continue
        if re.search(r'\balt\s*=\s*(""|\'\')', tag):
            decorativas += 1
            # Decorativa: tiene que quedar fuera del arbol de accesibilidad.
            assert 'aria-hidden="true"' in tag, (
                f'{ruta}:{linea_num} alt="" sin aria-hidden="true": {resumen}'
            )
        else:
            descriptivas += 1
            # Descriptiva: el texto tiene que aportar algo.
            texto = re.search(r'\balt\s*=\s*"([^"]*)"', tag)
            assert texto and len(texto.group(1).strip()) >= 3, (
                f"{ruta}:{linea_num} alt demasiado corto para ser descriptivo: {resumen}"
            )

for carpeta, patron in (("templates", "*.html"), ("static/js", "*.js")):
    base = os.path.join(RAIZ, *carpeta.split("/"))
    for dirpath, _dirs, files in os.walk(base):
        for nombre in files:
            if not nombre.endswith(patron.lstrip("*")):
                continue
            ruta = os.path.join(dirpath, nombre)
            rel = os.path.relpath(ruta, RAIZ).replace("\\", "/")
            revisar(rel, open(ruta, encoding="utf-8").read())

assert not sin_alt, "etiquetas <img> sin alt:\n  " + "\n  ".join(sin_alt)

# Ninguna etiqueta debe quedar sin dimensiones: sin width/height el navegador no
# reserva espacio y la pagina salta al cargar (CLS de Core Web Vitals).
sin_dimension: list[str] = []
for carpeta in ("templates", "static/js"):
    base = os.path.join(RAIZ, *carpeta.split("/"))
    for dirpath, _dirs, files in os.walk(base):
        for nombre in files:
            if not nombre.endswith((".html", ".js")):
                continue
            ruta = os.path.join(dirpath, nombre)
            rel = os.path.relpath(ruta, RAIZ).replace("\\", "/")
            for tag in IMG.findall(open(ruta, encoding="utf-8").read()):
                if not (re.search(r"\bwidth\s*=", tag) and re.search(r"\bheight\s*=", tag)):
                    sin_dimension.append(f"{rel}  {tag[:90]}")

assert not sin_dimension, "etiquetas <img> sin width/height (causan CLS):\n  " + "\n  ".join(sin_dimension)

print(f"OK 5: {decorativas + descriptivas} etiquetas <img> con alt "
      f"({decorativas} decorativas, {descriptivas} descriptivas) y todas con dimensiones")


# ══════════════════════════════════════════════════════════════
# 6) PESO Y DIMENSIONES DE LOS ACTIVOS
# ══════════════════════════════════════════════════════════════
# Umbrales: por encima de 150 KB conviene WebP; por encima de 1200 px de ancho
# para un icono de interfaz es sobredimension clara.
LIMITE_BYTES = 150 * 1024
LIMITE_ANCHO = 1200

pesadas: list[str] = []
enormes: list[str] = []
total = 0
contados = 0

base_img = os.path.join(RAIZ, "static", "img")
for dirpath, _dirs, files in os.walk(base_img):
    for nombre in files:
        ruta = os.path.join(dirpath, nombre)
        rel = os.path.relpath(ruta, RAIZ).replace("\\", "/")
        peso = os.path.getsize(ruta)
        total += peso
        contados += 1
        if peso > LIMITE_BYTES:
            pesadas.append(f"{rel} ({peso / 1024:.0f} KB)")
        if nombre.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            with Image.open(ruta) as im:
                if im.size[0] > LIMITE_ANCHO:
                    enormes.append(f"{rel} ({im.size[0]}x{im.size[1]})")

assert not pesadas, (
    "activos por encima de 150 KB: convertir a WebP o redimensionar:\n  " + "\n  ".join(pesadas)
)
assert not enormes, (
    f"activos por encima de {LIMITE_ANCHO} px de ancho:\n  " + "\n  ".join(enormes)
)

print(f"OK 6: {contados} activos en static/img, {total / 1024:.0f} KB en total, "
      f"ninguno supera {LIMITE_BYTES // 1024} KB ni {LIMITE_ANCHO} px")

# Activos que ya no referencia nadie: no rompen nada, pero pesan en el repo.
fuentes = []
for carpeta in ("templates", "static/js", "static/css"):
    base = os.path.join(RAIZ, *carpeta.split("/"))
    for dirpath, _dirs, files in os.walk(base):
        for nombre in files:
            fuentes.append(open(os.path.join(dirpath, nombre), encoding="utf-8", errors="ignore").read())
todo = "\n".join(fuentes)

huerfanos = []
for dirpath, _dirs, files in os.walk(base_img):
    for nombre in files:
        base_nombre = os.path.splitext(nombre)[0]
        # up/down se construyen con plantillas de cadena; los favicons se
        # referencian desde el include y desde seo.py.
        if base_nombre in {"up", "down", "favicon", "favicon-32", "favicon-192", "apple-touch-icon"}:
            continue
        if nombre not in todo:
            rel = os.path.relpath(os.path.join(dirpath, nombre), RAIZ).replace("\\", "/")
            huerfanos.append(f"{rel} ({os.path.getsize(os.path.join(dirpath, nombre)) / 1024:.0f} KB)")

if huerfanos:
    print("   AVISO: activos sin referencias en el codigo (candidatos a borrar):")
    for h in huerfanos:
        print(f"     {h}")
