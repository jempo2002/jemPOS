"""check_rendimiento_ux.py — verifica los puntos 12 a 16 de la lista de produccion.

Ejecutar:  python scripts/check_rendimiento_ux.py

Seis bloques, uno por criterio. Todo se comprueba contra la app real (mismo
create_app que usa run.py) y contra los archivos en disco, nunca contra una
copia de lo que el codigo deberia decir.

  1) Compresion: negocia gzip/br, respeta los MIME que no deben comprimirse y
     no rompe el sitemap ni el manifest.
  2) defer: los scripts no criticos lo llevan, y los que romperian la pagina
     con defer siguen sin el.
  3) Contraste WCAG AA: calcula el ratio real de cada color de texto del CSS
     contra la superficie donde se pinta.
  4) Movil: viewport en todas las plantillas y tablas con scroll contenido.
  5) 404: codigo 404 de verdad, HTML para el navegador y JSON para la API.
  6) Enlaces: ningun ancla vacia y ninguna URL interna que devuelva 404.
"""

from __future__ import annotations

import gzip
import os
import re
import sys
import xml.etree.ElementTree as ET
from glob import glob

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

# Desarrollo: sin esto Talisman fuerza HTTPS y todo responde 301 en el test.
os.environ.setdefault("FLASK_ENV", "development")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import create_app  # noqa: E402

PLANTILLAS = sorted(glob("templates/**/*.html", recursive=True))


def _leer(ruta: str) -> str:
    with open(ruta, encoding="utf-8") as fh:
        return fh.read()


# Comentarios de Jinja {# ... #} y de HTML <!-- ... -->.
_COMENTARIOS = re.compile(r"\{#.*?#\}|<!--.*?-->", re.S)


def _leer_sin_comentarios(ruta: str) -> str:
    """Contenido de la plantilla con los comentarios sustituidos por saltos.

    Imprescindible para cualquier escaneo de etiquetas. Los comentarios de este
    proyecto DOCUMENTAN el markup, asi que mencionan las mismas etiquetas que se
    estan buscando (`<head>`, `<script>`, el ancla vacia...). Sin esto el chequeo
    se encuentra a si mismo y reporta un fallo que no existe.

    Se reemplaza por los saltos de linea que ocupaba el comentario para que los
    numeros de linea que se informan sigan siendo los del archivo real.
    """
    return _COMENTARIOS.sub(lambda m: "\n" * m.group(0).count("\n"), _leer(ruta))


_COMENTARIOS_CSS = re.compile(r"/\*.*?\*/", re.S)


def _leer_css(ruta: str) -> str:
    """CSS sin comentarios, para poder partirlo en reglas selector{cuerpo}.

    Mismo motivo que en las plantillas, y aqui ademas rompe el analisis: los
    comentarios de este proyecto citan reglas CSS, asi que contienen llaves
    (`body { overflow-x: hidden }`). Un `[^}]*` se corta en esa llave y la regla
    parece no declarar lo que si declara.
    """
    return _COMENTARIOS_CSS.sub(lambda m: "\n" * m.group(0).count("\n"), _leer(ruta))


def _cliente(app):
    app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    return app.test_client()


# ══════════════════════════════════════════════════════════════
# 1) COMPRESION
# ══════════════════════════════════════════════════════════════

def bloque_compresion(app) -> None:
    c = _cliente(app)
    acepta = {"Accept-Encoding": "gzip"}

    # El landing es la pagina publica mas grande: es la que tiene que comprimir.
    r = c.get("/landing", headers=acepta)
    assert r.status_code == 200, f"/landing devolvio {r.status_code}"
    assert r.headers.get("Content-Encoding") == "gzip", (
        "/landing no se comprimio: Content-Encoding="
        f"{r.headers.get('Content-Encoding')!r}"
    )
    # El cuerpo tiene que seguir siendo el HTML correcto despues de descomprimir.
    html = gzip.decompress(r.data).decode("utf-8")
    assert "<!DOCTYPE html>" in html, "el HTML comprimido no descomprime bien"
    comprimido, original = len(r.data), len(html.encode("utf-8"))
    ahorro = 100 - (comprimido * 100 // original)
    assert ahorro > 50, f"ahorro de solo {ahorro}% en /landing"

    # Vary: sin esta cabecera un proxy intermedio podria servir el cuerpo
    # comprimido a un cliente que no lo pidio.
    assert "Accept-Encoding" in (r.headers.get("Vary") or ""), (
        f"falta Accept-Encoding en Vary: {r.headers.get('Vary')!r}"
    )

    # Sin Accept-Encoding no se comprime nada: el cliente manda.
    r_plano = c.get("/landing")
    assert not r_plano.headers.get("Content-Encoding"), (
        "se comprimio sin que el cliente lo pidiera"
    )

    # El sitemap sigue siendo XML valido pasando por la compresion. Es el
    # criterio del checklist: application/xml no puede quedar corrupto.
    r = c.get("/sitemap.xml", headers=acepta)
    assert r.status_code == 200
    assert r.mimetype == "application/xml", f"MIME del sitemap: {r.mimetype}"
    cuerpo = gzip.decompress(r.data) if r.headers.get("Content-Encoding") == "gzip" else r.data
    ET.fromstring(cuerpo)  # revienta si la compresion corrompio el XML

    # robots.txt: MIME intacto y contenido legible.
    r = c.get("/robots.txt", headers=acepta)
    assert r.mimetype == "text/plain", f"MIME de robots.txt: {r.mimetype}"
    cuerpo = gzip.decompress(r.data) if r.headers.get("Content-Encoding") == "gzip" else r.data
    assert b"Sitemap:" in cuerpo, "robots.txt perdio la linea del sitemap"

    # El manifest tiene que seguir siendo JSON parseable.
    import json

    r = c.get("/site.webmanifest", headers=acepta)
    cuerpo = gzip.decompress(r.data) if r.headers.get("Content-Encoding") == "gzip" else r.data
    json.loads(cuerpo)

    # Los PNG ya estan comprimidos: volver a pasarlos por gzip gasta CPU y no
    # ahorra bytes. Tienen que salir en claro.
    r = c.get("/static/img/favicon-192.png", headers=acepta)
    assert r.status_code == 200
    assert not r.headers.get("Content-Encoding"), (
        "el PNG se comprimio; no deberia estar en COMPRESS_MIMETYPES"
    )

    # El CSS es el activo estatico mas grande. Se pide con el Accept-Encoding
    # que manda cualquier navegador real, no solo gzip: ver la nota de abajo.
    como_navegador = {"Accept-Encoding": "gzip, deflate, br"}
    r = c.get("/static/css/landing.css", headers=como_navegador)
    assert r.status_code == 200
    enc_css = r.headers.get("Content-Encoding")
    assert enc_css in ("br", "zstd", "deflate"), f"el CSS no se comprimio (enc={enc_css!r})"
    assert r.content_length < 15000, f"CSS comprimido en {r.content_length} bytes, se esperaba <15KB"

    # Limitacion conocida de Flask-Compress, fijada aqui para que nadie la
    # descubra en produccion: los archivos estaticos se sirven como respuesta
    # en streaming, y para esas la libreria NO ofrece gzip (su
    # COMPRESS_ALGORITHM_STREAMING trae zstd/br/deflate y anadir "gzip" a mano
    # no cambia nada, el filtro es interno). Consecuencia: un cliente que
    # anuncie SOLO gzip recibe el CSS y el JS sin comprimir. No afecta a ningun
    # navegador (todos mandan br y deflate desde 2013), si a algun cliente de
    # linea de comandos. El HTML no esta afectado porque no va en streaming.
    r_gzip = c.get("/static/css/landing.css", headers=acepta)
    assert not r_gzip.headers.get("Content-Encoding"), (
        "Flask-Compress ya comprime estaticos con gzip: se puede borrar esta nota"
    )

    print(f"OK 1: compresion activa (landing -{ahorro}%, CSS {enc_css}), XML/JSON/robots intactos, PNG sin tocar")


# ══════════════════════════════════════════════════════════════
# 2) DEFER
# ══════════════════════════════════════════════════════════════

# Scripts que NO deben llevar defer, con el motivo. Si alguien se lo anade, la
# pagina se rompe de una forma que no salta en una revision rapida.
SIN_DEFER = {
    "cdn.tailwindcss.com": "compila el CSS en el navegador: con defer la pagina se pinta sin estilos",
    ".tailwind.js": "lleva la config de Tailwind, acoplada al CDN",
    "cookies.js": "marca <html data-cookies-ok> antes del primer frame para que el aviso no parpadee",
}

ETIQUETA = re.compile(r'<script\s+src="([^"]+)"([^>]*)>', re.I)


def bloque_defer() -> None:
    con_defer, sin_defer_ok, fallos = 0, 0, []
    for ruta in PLANTILLAS:
        etiquetas = []
        for m in ETIQUETA.finditer(_leer_sin_comentarios(ruta)):
            src, resto = m.group(1), m.group(2)
            motivo = next((v for k, v in SIN_DEFER.items() if k in src), None)
            tiene = "defer" in resto or "async" in resto
            etiquetas.append((src, tiene))
            if motivo:
                if tiene:
                    fallos.append(f"{ruta}: {src} NO debe llevar defer ({motivo})")
                else:
                    sin_defer_ok += 1
            elif tiene:
                con_defer += 1
            else:
                fallos.append(f"{ruta}: {src} deberia llevar defer")

        # Inversion de orden: un script con defer espera al final del parseo,
        # uno sin defer se ejecuta al instante. Si el segundo aparece DESPUES
        # del primero en el documento, se ejecuta ANTES, y si dependia de el
        # (una libreria, un global) falla con un error que no se reproduce en
        # local si el archivo venia del cache. Todos los scripts sin defer
        # tienen que ir antes de los diferidos.
        primer_defer = next((i for i, (_, d) in enumerate(etiquetas) if d), None)
        if primer_defer is not None:
            for src, diferido in etiquetas[primer_defer + 1:]:
                if not diferido:
                    fallos.append(
                        f"{ruta}: {src} sin defer va despues de uno diferido "
                        "(el orden de ejecucion se invierte)"
                    )

    assert not fallos, "defer mal aplicado:\n  " + "\n  ".join(fallos)
    assert con_defer >= 60, f"solo {con_defer} scripts con defer, se esperaban 60+"
    print(f"OK 2: {con_defer} scripts con defer, {sin_defer_ok} render-criticos exentos, orden de ejecucion intacto")


# ══════════════════════════════════════════════════════════════
# 3) CONTRASTE WCAG AA
# ══════════════════════════════════════════════════════════════

def luminancia(hexa: str) -> float:
    h = hexa.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    canales = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4) for v in canales]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(fg: str, bg: str) -> float:
    a, b = luminancia(fg), luminancia(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# Unico contenedor oscuro del proyecto: el sidebar de escritorio (#1E293B).
# Estas reglas no declaran su propio fondo, asi que hay que decirle al medidor
# cual heredan; contra blanco darian un falso positivo.
SELECTORES_OSCUROS = {
    ".sidebar-logo .sub": "#1E293B",
    ".nav-link": "#1E293B",
    ".sidebar-footer .user-role": "#1E293B",
}

# Fondo por defecto cuando la regla no declara ninguno: blanco, que es la
# superficie de las tarjetas, modales y tablas del proyecto.
FONDO_DEFECTO = "#FFFFFF"

# Exencion de logotipo. WCAG 1.4.3 dice literalmente que el texto que forma
# parte de un logo o nombre comercial no tiene requisito de contraste.
# Es la "POS" azul del wordmark jemPOS.
ES_LOGO = re.compile(r"-logo\b|\.logo-text")

REGLA = re.compile(r"([^{}]*)\{([^{}]*)\}", re.S)
DECL_COLOR = re.compile(r"(?<!-)\bcolor\s*:\s*(#[0-9a-fA-F]{3,6})\s*(?:;|$)", re.I)
DECL_FONDO = re.compile(r"\bbackground(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,6})", re.I)
DECL_TAM = re.compile(r"\bfont-size\s*:\s*([\d.]+)rem")
DECL_PESO = re.compile(r"\bfont-weight\s*:\s*(\d+)")

MIN_AA = 4.5          # texto normal (WCAG 1.4.3)
MIN_AA_GRANDE = 3.0   # texto grande: >=24px, o >=18.66px en negrita


def bloque_contraste() -> None:
    fallos, medidos, exentos = [], 0, 0
    for ruta in sorted(glob("static/css/*.css")):
        txt = _leer_css(ruta)
        for m in REGLA.finditer(txt):
            crudo = m.group(1).strip()
            if not crudo or crudo.startswith("@"):
                continue
            sel = crudo.splitlines()[-1].strip().rstrip(",")
            cuerpo = m.group(2)
            col = DECL_COLOR.search(cuerpo)
            if not col:
                continue
            fg = col.group(1)
            # Texto claro: su fondo real es un relleno de color que esta en otra
            # regla (botones primarios), no deducible desde aqui.
            if luminancia(fg) > 0.7:
                continue
            if ES_LOGO.search(sel):
                exentos += 1
                continue

            fondo = DECL_FONDO.search(cuerpo)
            bg = SELECTORES_OSCUROS.get(sel) or (fondo.group(1) if fondo else FONDO_DEFECTO)

            tam = DECL_TAM.search(cuerpo)
            peso = DECL_PESO.search(cuerpo)
            px = float(tam.group(1)) * 16 if tam else None
            grande = px is not None and (
                px >= 24 or (px >= 18.66 and int(peso.group(1) if peso else 400) >= 700)
            )
            minimo = MIN_AA_GRANDE if grande else MIN_AA

            r = ratio(fg, bg)
            medidos += 1
            if r < minimo:
                linea = txt.count("\n", 0, m.start(2)) + 1
                fallos.append(
                    f"{ruta}:{linea} {sel} -> {fg} sobre {bg} = {r:.2f}:1 (min {minimo})"
                )
    assert not fallos, (
        f"colores por debajo del minimo WCAG AA:\n  " + "\n  ".join(fallos)
    )

    # Las utilidades Tailwind de las plantillas se revisan por nombre: slate-400
    # es #94a3b8, que da 2.56:1 sobre blanco.
    prohibidas = []
    for ruta in PLANTILLAS + sorted(glob("static/js/*.js")):
        txt = _leer_sin_comentarios(ruta)
        for clase in ("text-slate-400", "text-gray-400", "text-slate-300"):
            if re.search(rf"\b{clase}\b", txt):
                prohibidas.append(f"{ruta}: {clase}")
    assert not prohibidas, (
        "utilidades de texto por debajo de AA (usa -500 o mas oscuro):\n  "
        + "\n  ".join(prohibidas)
    )

    # El boton deshabilitado es el punto tipico de fallo: WCAG lo exime, pero
    # ilegible es ilegible. Se mide explicitamente contra su propio fondo.
    pares_disabled = [
        ("static/css/global.css", ".jem-pager-btn:disabled", "#F8FAFC"),
        ("static/css/caja.css", ".btn-fiar:disabled", "#F1F5F9"),
        ("static/css/perfil.css", ".perf-input-disabled .perf-input", "#F8FAFC"),
    ]
    for ruta, sel, fondo in pares_disabled:
        txt = _leer_css(ruta)
        # El selector puede aparecer en varias reglas (caja.css lo declara dos
        # veces); interesa la que fija el color, no la primera que aparezca.
        cuerpos = re.findall(re.escape(sel) + r"\s*\{([^}]*)\}", txt)
        assert cuerpos, f"no se encontro la regla {sel} en {ruta}"
        colores = [DECL_COLOR.search(c).group(1) for c in cuerpos if DECL_COLOR.search(c)]
        assert colores, f"{sel} no declara color en ninguna de sus {len(cuerpos)} reglas"
        for fg in colores:
            r = ratio(fg, fondo)
            assert r >= MIN_AA, f"{sel}: {fg} sobre {fondo} = {r:.2f}:1"

    print(
        f"OK 3: {medidos} colores de texto medidos contra su fondo real, todos en AA "
        f"({exentos} exentos por ser logotipo)"
    )


# ══════════════════════════════════════════════════════════════
# 4) MOVIL
# ══════════════════════════════════════════════════════════════

def bloque_movil(app) -> None:
    # 4a) viewport en toda plantilla que tenga <head> propio.
    # Ojo: buscar la subcadena "<head" da falsos positivos, porque tambien
    # aparece dentro de "<header". Hay que exigir el cierre de la etiqueta.
    ETIQUETA_HEAD = re.compile(r"<head[\s>]", re.I)
    sin_viewport, con_head = [], 0
    for ruta in PLANTILLAS:
        txt = _leer_sin_comentarios(ruta)
        if not ETIQUETA_HEAD.search(txt):
            continue   # parciales e hijas de un layout: heredan el <head>
        con_head += 1
        if not re.search(r'<meta\s+name="viewport"[^>]*width=device-width', txt):
            sin_viewport.append(ruta)
    assert not sin_viewport, "plantillas sin viewport:\n  " + "\n  ".join(sin_viewport)

    # 4b) Toda <table> vive dentro de un contenedor con scroll horizontal.
    # Se comprueba el ancestro real recorriendo el HTML hacia atras.
    envoltorios_con_scroll = (
        "fiad-table-wrap", "gast-table-wrap", "table-wrap",
        "offline-sync-table-wrap", "overflow-x-auto", "table-scroll",
    )
    sueltas = []
    for ruta in PLANTILLAS:
        txt = _leer(ruta)
        for m in re.finditer(r"<table\b", txt):
            # El div envolvente es el ultimo <div ...> abierto antes de la tabla.
            previo = txt[:m.start()]
            divs = re.findall(r"<div[^>]*>", previo)
            contexto = " ".join(divs[-3:])
            if not any(w in contexto for w in envoltorios_con_scroll):
                linea = txt.count("\n", 0, m.start()) + 1
                sueltas.append(f"{ruta}:{linea}")
    assert not sueltas, (
        "tablas sin contenedor de scroll horizontal:\n  " + "\n  ".join(sueltas)
    )

    # 4c) Los envoltorios de CSS propio declaran overflow-x auto, no hidden.
    # `hidden` recorta las ultimas columnas sin dejar forma de alcanzarlas.
    for ruta, sel in (
        ("static/css/fiados.css", ".fiad-table-wrap"),
        ("static/css/gastos.css", ".gast-table-wrap"),
        ("static/css/inventario.css", ".table-wrap"),
    ):
        txt = _leer_css(ruta)
        cuerpos = re.findall(re.escape(sel) + r"\s*\{([^}]*)\}", txt)
        assert any("overflow-x: auto" in c for c in cuerpos), (
            f"{sel} en {ruta} no declara overflow-x: auto"
        )
        assert not any(re.search(r"overflow:\s*hidden", c) for c in cuerpos), (
            f"{sel} en {ruta} sigue con overflow: hidden y recorta columnas"
        )

    # 4d) La pagina nunca scrollea en horizontal: la regla que impide que una
    # tabla ancha arrastre la navbar. Si esto se cae, el punto 4c no sirve.
    assert re.search(r"html,\s*\n?body\s*\{[^}]*overflow-x:\s*hidden", _leer("static/css/global.css"), re.S), (
        "global.css perdio el overflow-x: hidden de html/body"
    )

    print(f"OK 4: viewport en las {con_head} plantillas con <head> propio, tablas con scroll contenido")


# ══════════════════════════════════════════════════════════════
# 5) PAGINA 404
# ══════════════════════════════════════════════════════════════

def bloque_404(app) -> None:
    c = _cliente(app)

    r = c.get("/esta-ruta-no-existe-jamas")
    assert r.status_code == 404, f"se esperaba 404, llego {r.status_code} (soft 404)"
    assert r.mimetype == "text/html", f"MIME de la 404: {r.mimetype}"
    html = r.get_data(as_text=True)

    # Tiene que ser la pagina del sitio, no la de Werkzeug.
    assert "Werkzeug" not in html, "sigue saliendo la 404 por defecto de Werkzeug"
    for pieza, que in (
        ("Esta pagina no existe", "el titulo propio"),
        ('class="header', "el header heredado del layout"),
        ('class="footer', "el footer heredado del layout"),
        ("landing.css", "la hoja de estilos"),
        ("error404__acciones", "los botones de salida"),
        ("Volver al inicio", "el enlace al inicio"),
    ):
        assert pieza in html, f"la 404 no trae {que}"

    # noindex: aunque el 404 ya lo dice, la etiqueta lo deja explicito.
    assert re.search(r'<meta name="robots" content="noindex', html), (
        "la 404 no declara noindex"
    )
    # Y no puede heredar el aviso de borrador de las paginas legales.
    assert "Borrador" not in html, "la 404 heredo la banda de borrador legal"

    # Padding: la 404 usa el layout .legal, que reserva hueco para el header
    # fijo. Sin esa clase el titulo queda debajo de la barra.
    assert 'class="legal"' in html, "la 404 no usa el layout .legal (titulo tapado por el header)"

    # Una ruta de API inexistente tiene que seguir devolviendo JSON: el fetch
    # del frontend hace response.json() y con HTML reventaria.
    r = c.get("/pos/api/no-existe")
    assert r.status_code == 404
    assert r.is_json, f"una 404 de API devolvio {r.mimetype} en vez de JSON"
    assert r.get_json()["ok"] is False

    # Tambien por cabecera, que es como la manda fetch con Accept.
    r = c.get("/otra-ruta-inventada", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.is_json, "una peticion XHR recibio HTML en la 404"

    print("OK 5: /404 devuelve 404 real con el layout del sitio; las rutas de API siguen en JSON")


# ══════════════════════════════════════════════════════════════
# 6) ENLACES
# ══════════════════════════════════════════════════════════════

def bloque_enlaces(app) -> None:
    # 6a) Ningun ancla vacia. Nota: este archivo tampoco puede contener el
    # literal en un comentario, o se reportaria a si mismo.
    vacios = []
    patron = re.compile(r'href\s*=\s*(["\'])\s*#\s*\1')
    for ruta in PLANTILLAS:
        txt = _leer_sin_comentarios(ruta)
        for m in patron.finditer(txt):
            vacios.append(f"{ruta}:{txt.count(chr(10), 0, m.start()) + 1}")
    assert not vacios, "anclas vacias (no llevan a ninguna parte):\n  " + "\n  ".join(vacios)

    # 6b) Las URLs internas literales de las plantillas responden.
    c = _cliente(app)
    internas = set()
    for ruta in PLANTILLAS:
        for m in re.finditer(r'href="(/[^"{}#?]*)"', _leer_sin_comentarios(ruta)):
            internas.add(m.group(1))
    rotas = []
    for url in sorted(internas):
        r = c.get(url)
        # 302 = redirige al login (ruta privada, correcto sin sesion).
        if r.status_code not in (200, 302, 308):
            rotas.append(f"{url} -> {r.status_code}")
    assert not rotas, "enlaces internos rotos:\n  " + "\n  ".join(rotas)

    # 6c) Los anclas dentro de la landing tienen que existir como id.
    landing = _leer_sin_comentarios("templates/landing.html")
    ids = set(re.findall(r'id="([^"]+)"', landing))
    huerfanos = [
        a for a in set(re.findall(r'href="#([^"]+)"', landing))
        if a not in ids
    ]
    assert not huerfanos, f"anclas sin destino en la landing: {huerfanos}"

    print(f"OK 6: sin anclas vacias, {len(internas)} enlaces internos responden, anclas de la landing validas")


def main() -> int:
    app = create_app()
    with app.app_context():
        bloque_compresion(app)
        bloque_defer()
        bloque_contraste()
        bloque_movil(app)
        bloque_404(app)
        bloque_enlaces(app)
    print("\nTODO OK: puntos 12 a 16 verificados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
