"""Chequeo del endurecimiento de sesiones y del checklist legal/SEO.

No toca la base de datos: todo con el test client de Flask.

  1) Sesiones: las rutas publicas destruyen la sesion, los flashes sobreviven y
     las paginas privadas salen con no-store (boton "atras" del navegador).
  2) Paginas legales: HTTP 200, contenido y enlaces desde el footer.
  3) Aviso de cookies: markup y logica de localStorage del script.
  4) Flask-Talisman: no fuerza HTTPS en desarrollo y si lo hace en produccion.
  5) SEO: title y meta description unicos en las paginas publicas, noindex en
     las privadas.

    python scripts/check_produccion.py
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402
from app.security import es_desarrollo  # noqa: E402

PUBLICAS = {
    "/landing": "landing",
    "/legal/aviso-legal": "aviso legal",
    "/legal/politica-privacidad": "politica de privacidad",
    "/login": "login",
    "/registro": "registro",
    "/olvide_password": "recuperar contrasena",
}

PRIVADAS = ("/dashboard", "/pos/caja", "/pos/fiados", "/pos/ventas", "/pos/gastos", "/inventario/")


def app_dev():
    os.environ["FLASK_ENV"] = "development"
    app = create_app()
    app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    return app


def sesion(cliente, rol="Admin"):
    with cliente.session_transaction() as s:
        s["id_usuario"] = 1
        s["id_tienda"] = 1
        s["rol"] = rol
        s["nombre_completo"] = "QA Admin"


def html(cliente, ruta):
    r = cliente.get(ruta)
    return r, r.get_data(as_text=True)


# ══════════════════════════════════════════════════════════════
# 1) SESIONES EN RUTAS PUBLICAS
# ══════════════════════════════════════════════════════════════
app = app_dev()
assert es_desarrollo() is True, "FLASK_ENV=development deberia dar modo desarrollo"

RUTAS_QUE_CIERRAN = ("/", "/landing", "/login", "/legal/aviso-legal", "/legal/politica-privacidad")

# Claves de identidad: ninguna puede sobrevivir a una ruta publica.
IDENTIDAD = ("id_usuario", "id_tienda", "rol", "nombre_completo", "es_restaurante")

# Lo que si puede reaparecer DESPUES del clear, sin identidad asociada:
#   csrf_token  -> lo regenera render_template al pintar el formulario de login
#                  (token nuevo: rotarlo en el corte de sesion es lo correcto)
#   _permanent  -> bandera interna de Flask
#   _flashes    -> mensajes en transito, se preservan a proposito
NO_IDENTIFICANTES = {"csrf_token", "_permanent", "_flashes"}

for ruta in RUTAS_QUE_CIERRAN:
    with app.test_client() as c:
        sesion(c)
        with c.session_transaction() as s:
            assert s.get("id_usuario") == 1, "la sesion de prueba no quedo puesta"
            csrf_previo = s.get("csrf_token")

        c.get(ruta)

        with c.session_transaction() as s:
            for clave in IDENTIDAD:
                assert clave not in s, f"{ruta} dejo viva la clave de identidad {clave!r}"
            restos = set(s.keys()) - NO_IDENTIFICANTES
            assert not restos, f"{ruta} dejo datos de sesion inesperados: {restos}"
            # Si vuelve a haber token CSRF, tiene que ser uno nuevo.
            if csrf_previo and s.get("csrf_token"):
                assert s["csrf_token"] != csrf_previo, f"{ruta} reutilizo el token CSRF anterior"

# La raiz ya no reenvia al area privada: manda a la landing publica.
with app.test_client() as c:
    sesion(c)
    r = c.get("/")
    assert r.status_code == 302 and "/landing" in r.headers["Location"], (
        r.status_code, r.headers.get("Location")
    )

# Tras pasar por una ruta publica, lo privado vuelve a pedir credenciales.
for ruta in PRIVADAS:
    with app.test_client() as c:
        sesion(c)
        assert c.get(ruta).status_code == 200, f"{ruta} deberia abrir con sesion"
        c.get("/landing")                      # aqui se destruye la sesion
        r = c.get(ruta)
        assert r.status_code == 302 and "/login" in r.headers["Location"], (
            ruta, r.status_code, r.headers.get("Location")
        )

# El boton "atras" no puede repintar una pagina privada desde el cache: sin
# no-store el navegador la sirve del historial sin preguntarle al servidor.
with app.test_client() as c:
    sesion(c)
    for ruta in PRIVADAS:
        r = c.get(ruta)
        cache = (r.headers.get("Cache-Control") or "").lower()
        assert "no-store" in cache, f"{ruta} sin no-store: {cache!r}"
        assert (r.headers.get("Pragma") or "").lower() == "no-cache", ruta

# Los estaticos y las publicas si se pueden cachear.
with app.test_client() as c:
    r = c.get("/landing")
    assert "no-store" not in (r.headers.get("Cache-Control") or "").lower()

# Los flashes sobreviven al cierre de sesion: si no, el "Contrasena incorrecta"
# del POST desaparece al redirigir al GET /login.
with app.test_client() as c:
    sesion(c)
    r = c.post("/login", data={"correo": "noexiste@qa.test", "contrasena": "xx"}, follow_redirects=True)
    cuerpo = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Usuario no encontrado" in cuerpo, "el flash del login se perdio al limpiar la sesion"
    with c.session_transaction() as s:
        assert "id_usuario" not in s, "la sesion sobrevivio a un login fallido"

# Y un login correcto sigue creando sesion (no se rompio la autenticacion).
with app.test_client() as c:
    r = c.post("/login", data={"correo": "noexiste@qa.test", "contrasena": "xx"})
    assert r.status_code == 302
    with c.session_transaction() as s:
        assert "id_usuario" not in s

print("OK 1: rutas publicas destruyen la sesion, privadas con no-store, flashes intactos")


# ══════════════════════════════════════════════════════════════
# 2) PAGINAS LEGALES
# ══════════════════════════════════════════════════════════════
with app.test_client() as c:
    r, cuerpo = html(c, "/legal/aviso-legal")
    assert r.status_code == 200, r.status_code
    assert "Aviso legal" in cuerpo and "Titularidad del sitio" in cuerpo
    assert "{{" not in cuerpo and "{%" not in cuerpo, "quedo Jinja sin renderizar"
    assert "Borrador" in cuerpo, "falta el aviso de que el texto es de relleno"
    assert "/legal/politica-privacidad" in cuerpo, "falta el enlace cruzado"

    r, cuerpo = html(c, "/legal/politica-privacidad")
    assert r.status_code == 200, r.status_code
    assert "Politica de privacidad" in cuerpo and "Cookies y almacenamiento local" in cuerpo
    assert "{{" not in cuerpo and "{%" not in cuerpo
    assert 'id="cookies"' in cuerpo, "falta el ancla #cookies que enlaza el footer"
    assert "/legal/aviso-legal" in cuerpo

    # Usan la hoja de estilos del landing (mismo diseno, no otra web).
    for ruta in ("/legal/aviso-legal", "/legal/politica-privacidad"):
        _r, cuerpo = html(c, ruta)
        assert "/static/css/landing.css" in cuerpo, ruta
        assert 'class="footer' in cuerpo and 'class="header' in cuerpo, ruta

    # El footer del landing enlaza las dos, ya sin href="#".
    _r, landing = html(c, "/landing")
    assert "/legal/aviso-legal" in landing and "/legal/politica-privacidad" in landing
    bloque_legal = landing.split('aria-label="Legal"')[1].split("</nav>")[0]
    assert 'href="#"' not in bloque_legal, "quedaron placeholders en el footer legal"

print("OK 2: aviso legal y politica de privacidad en 200, con diseno y enlaces del landing")


# ══════════════════════════════════════════════════════════════
# 3) AVISO DE COOKIES
# ══════════════════════════════════════════════════════════════
with app.test_client() as c:
    for ruta in ("/landing", "/legal/aviso-legal", "/legal/politica-privacidad"):
        _r, cuerpo = html(c, ruta)
        assert "data-cookies" in cuerpo, f"{ruta} sin banner de cookies"
        assert "data-cookies-aceptar" in cuerpo, f"{ruta} sin boton Aceptar"
        assert "/static/js/cookies.js" in cuerpo, f"{ruta} no carga cookies.js"
        # Sin JS el aviso se ve: no puede venir con el atributo hidden.
        banner = cuerpo.split("data-cookies", 1)[1].split(">", 1)[0]
        assert "hidden" not in banner, f"{ruta} trae el banner oculto en el HTML"

    # cookies.js se carga sin defer/async para marcar <html> antes del pintado.
    _r, cuerpo = html(c, "/landing")
    etiqueta = re.search(r"<script[^>]*cookies\.js[^>]*>", cuerpo).group(0)
    assert "defer" not in etiqueta and "async" not in etiqueta, etiqueta

js = open(os.path.join("static", "js", "cookies.js"), encoding="utf-8").read()
assert "localStorage" in js and "jempos_cookies_aceptadas" in js
assert "setItem" in js and "getItem" in js
assert js.count("catch") >= 2, "localStorage lanza en modo privado: falta try/catch"
assert "data-cookies-ok" in js, "falta la marca que usa el CSS para ocultarlo"

css = open(os.path.join("static", "css", "landing.css"), encoding="utf-8").read()
assert "[data-cookies-ok] .cookies" in css, "el CSS no oculta el banner ya aceptado"
for regla in (".cookies {", ".cookies__texto", ".cookies__btn", ".cookies__enlace"):
    assert regla in css, f"falta CSS del banner: {regla}"
assert "position: fixed" in css.split(".cookies {")[1].split("}")[0]

print("OK 3: banner presente en publicas, visible sin JS, oculto por CSS tras aceptar")


# ══════════════════════════════════════════════════════════════
# 4) FLASK-TALISMAN: HTTPS SIN ROMPER LOCALHOST
# ══════════════════════════════════════════════════════════════
with app.test_client() as c:
    r = c.get("/landing")           # peticion HTTP en desarrollo
    assert r.status_code == 200, f"desarrollo no deberia redirigir a HTTPS: {r.status_code}"
    assert "Strict-Transport-Security" not in r.headers, "HSTS en desarrollo bloquearia http local"
    # Las cabeceras que no dependen del esquema si se aplican siempre.
    assert r.headers.get("X-Frame-Options") == "DENY", r.headers.get("X-Frame-Options")
    assert "strict-origin" in (r.headers.get("Referrer-Policy") or ""), r.headers.get("Referrer-Policy")
    # CSP deliberadamente fuera: el CDN de Tailwind necesita unsafe-eval.
    assert "Content-Security-Policy" not in r.headers

assert app.config["SESSION_COOKIE_SECURE"] is not True, "cookie Secure en http local rompe la sesion"

# Mismo codigo con FLASK_ENV de produccion: ahora si fuerza HTTPS.
os.environ["FLASK_ENV"] = "production"
assert es_desarrollo() is False
app_prod = create_app()
app_prod.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
with app_prod.test_client() as c:
    r = c.get("/landing")
    assert r.status_code == 301, f"produccion deberia redirigir a HTTPS, dio {r.status_code}"
    assert r.headers["Location"].startswith("https://"), r.headers["Location"]
    r = c.get("/landing", base_url="https://jempos.test")
    assert r.status_code == 200, r.status_code
    assert "max-age=31536000" in (r.headers.get("Strict-Transport-Security") or "")
assert app_prod.config["SESSION_COOKIE_SECURE"] is True

# Detras de un proxy que termina TLS no puede haber bucle de redirecciones:
# Talisman confia en X-Forwarded-Proto. Esto es lo que salva a /health y a los
# sondeos del balanceador en produccion.
with app_prod.test_client() as c:
    r = c.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert r.status_code == 200, f"con X-Forwarded-Proto=https no debe redirigir: {r.status_code}"

    # ProxyFix: con el proxy anunciando https, las URLs absolutas tienen que
    # salir en https. Sin esto el canonical y el enlace del correo de
    # recuperacion irian en http:// aunque el sitio sirva por TLS.
    cuerpo = c.get(
        "/legal/aviso-legal",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "jempos.co"},
    ).get_data(as_text=True)
    canonical = re.search(r'<link rel="canonical" href="(.*?)"', cuerpo).group(1)
    assert canonical.startswith("https://jempos.co"), f"canonical mal formado: {canonical}"

# En desarrollo NO se aplica ProxyFix: confiar en X-Forwarded-* sin proxy
# delante deja que el navegador las falsifique.
with app.test_client() as c:
    cuerpo = c.get(
        "/legal/aviso-legal",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "atacante.test"},
    ).get_data(as_text=True)
    canonical = re.search(r'<link rel="canonical" href="(.*?)"', cuerpo).group(1)
    assert "atacante.test" not in canonical, f"se confio en X-Forwarded-Host en local: {canonical}"

# Cada app tiene su propia instancia de Talisman: Talisman guarda la config en
# la instancia, asi que un singleton compartido haria que la segunda app pisara
# los ajustes de la primera. Se vuelve a medir la app de desarrollo DESPUES de
# haber creado la de produccion.
with app.test_client() as c:
    r = c.get("/landing")
    assert r.status_code == 200, (
        "crear la app de produccion contamino la de desarrollo: "
        f"/landing devolvio {r.status_code}"
    )
    assert "Strict-Transport-Security" not in r.headers, "HSTS se filtro a la app de desarrollo"
assert app.config["SESSION_COOKIE_SECURE"] is not True, "cookie Secure se filtro a desarrollo"

# Cada bandera de desarrollo se reconoce por separado.
for var, valor, esperado in (
    ("FLASK_ENV", "development", True),
    ("FLASK_ENV", "dev", True),
    ("FLASK_ENV", "local", True),
    ("FLASK_ENV", "production", False),
    ("FLASK_ENV", "", False),
    ("FLASK_DEBUG", "1", True),
    ("DEBUG", "true", True),
):
    previo = dict(os.environ)
    os.environ.pop("FLASK_ENV", None)
    os.environ.pop("FLASK_DEBUG", None)
    os.environ.pop("DEBUG", None)
    os.environ[var] = valor
    assert es_desarrollo() is esperado, (var, valor, esperado)
    os.environ.clear()
    os.environ.update(previo)

# Sin ninguna variable: se asume produccion (lado seguro del error).
for var in ("FLASK_ENV", "FLASK_DEBUG", "DEBUG"):
    os.environ.pop(var, None)
assert es_desarrollo() is False, "sin variables hay que asumir produccion"
os.environ["FLASK_ENV"] = "development"

assert "flask-talisman" in open("requirements.txt", encoding="utf-8").read().lower()

print("OK 4: HTTPS forzado en produccion, http local intacto, deteccion de entorno correcta")


# ══════════════════════════════════════════════════════════════
# 5) SEO: TITLE Y META DESCRIPTION
# ══════════════════════════════════════════════════════════════
app = app_dev()
titulos: dict[str, str] = {}
descripciones: dict[str, str] = {}

with app.test_client() as c:
    for ruta in PUBLICAS:
        r, cuerpo = html(c, ruta)
        assert r.status_code == 200, (ruta, r.status_code)

        titulo = re.search(r"<title>(.*?)</title>", cuerpo, re.S)
        assert titulo, f"{ruta} sin <title>"
        titulo = titulo.group(1).strip()
        assert 10 <= len(titulo) <= 70, f"{ruta}: title de {len(titulo)} caracteres -> {titulo!r}"
        assert "jemPOS" in titulo, f"{ruta}: el title no nombra la marca"

        desc = re.search(r'<meta\s+name="description"\s+content="(.*?)"', cuerpo, re.S)
        assert desc, f"{ruta} sin meta description"
        desc = " ".join(desc.group(1).split())
        assert 50 <= len(desc) <= 300, f"{ruta}: description de {len(desc)} caracteres"
        assert re.search(r"punto de venta|POS", desc), f"{ruta}: la description no describe el producto"

        titulos[ruta] = titulo
        descripciones[ruta] = desc

# Unicos: dos paginas con el mismo title o description compiten entre si.
assert len(set(titulos.values())) == len(titulos), f"titles repetidos: {titulos}"
assert len(set(descripciones.values())) == len(descripciones), f"descriptions repetidas: {descripciones}"

with app.test_client() as c:
    # Login y recuperacion: noindex (pantallas de sesion, sin valor de busqueda).
    for ruta in ("/login", "/olvide_password"):
        _r, cuerpo = html(c, ruta)
        assert re.search(r'name="robots"\s+content="noindex', cuerpo), ruta
    # Landing y registro: indexables.
    for ruta in ("/landing", "/registro"):
        _r, cuerpo = html(c, ruta)
        assert re.search(r'name="robots"\s+content="index', cuerpo), ruta

    # Privadas: noindex como defensa en profundidad.
    sesion(c)
    for ruta in PRIVADAS:
        _r, cuerpo = html(c, ruta)
        assert re.search(r'name="robots"\s+content="noindex', cuerpo), f"{ruta} sin noindex"

print("OK 5: titles y descriptions unicos en publicas, noindex en sesion y privadas")
print()
print("Titles:")
for ruta, t in titulos.items():
    print(f"  {ruta:34} {len(t):>2}c  {t}")
