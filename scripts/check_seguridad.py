"""Chequeo de seguridad: simula los ataques de la auditoria contra la BD de .env.

Todo corre en UNA transaccion que se revierte al final: no deja datos.
Usa el volcado base (Master id=1 en tienda 1, tienda 4 con Admin id=6 y
Cajero id=8) y necesita una tienda con turno abierto y un producto activo.

  1) Precio y total los pone el servidor, no el navegador.
  2) IDOR: ventas, clientes y productos de otra tienda -> 404.
  3) Sesion revocada al desactivar al usuario, rol releido de la base y
     suscripcion vencida bloqueando tambien las APIs.
  4) Fuerza bruta: limite por IP y por cuenta; login sin enumeracion.
  5) Token de reset inservible tras cambiar la contrasena.
  6) Error 500 sin traza; correo con HTML rechazado; cookie Secure/HttpOnly.
  7) El Cajero edita productos pero no su precio de venta (403 aunque lo
     mande por consola); el Admin si. NaN no pasa como precio.

    python scripts/check_seguridad.py
"""

from __future__ import annotations

import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import mysql.connector
from dotenv import load_dotenv

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT") or 3306),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    autocommit=False,
)


class _NoCommit:
    """La misma conexion para todo; commit/rollback/close no hacen nada."""

    def __getattr__(self, name):
        return getattr(conn, name)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


from app import create_app  # noqa: E402
from app.routes import auth, core  # noqa: E402
from app.services import auth_service, cartera_service, inventory_service  # noqa: E402
from app.services import sales_service as svc  # noqa: E402
from app.utils import decorators  # noqa: E402

for modulo in (auth, core, decorators, svc, cartera_service, inventory_service):
    modulo.get_db = lambda: _NoCommit()

app = create_app()
app.config.update(WTF_CSRF_ENABLED=False)


@app.get("/__boom")
def _boom():
    raise RuntimeError("SELECT clave_hash FROM usuarios -- detalle interno")


XHR = {"X-Requested-With": "XMLHttpRequest"}


def q(sql, params=()):
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    return cur.fetchall() if cur.with_rows else None


def sesion(c, id_usuario, id_tienda, rol):
    with c.session_transaction() as s:
        s.update(id_usuario=id_usuario, id_tienda=id_tienda, rol=rol, nombre_completo="QA")


def espera(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return
    raise AssertionError(f"{fn.__name__} debio fallar con {exc.__name__}")


try:
    base = q(
        "SELECT t.id_tienda, t.id_usuario_apertura AS id_usuario, p.id_producto, p.precio_venta "
        "FROM turnos_caja t JOIN productos p ON p.id_tienda = t.id_tienda "
        "WHERE t.estado_turno = 'Abierto' AND p.estado_activo = 1 AND p.es_preparado = 0 "
        "AND p.precio_venta > 0 LIMIT 1"
    )
    assert base, "hace falta un turno abierto con un producto activo"
    tienda, usuario, id_producto, precio = (
        base[0]["id_tienda"], base[0]["id_usuario"], base[0]["id_producto"], float(base[0]["precio_venta"])
    )
    q("UPDATE productos SET stock_actual = stock_actual + 10 WHERE id_producto = %s", (id_producto,))
    otra = 4 if tienda != 4 else 1

    # ── 1) Precio manipulado ────────────────────────────────
    r = svc.registrar_venta(tienda, usuario, [{"id": id_producto, "qty": 2, "price": 1}], "efectivo", None, 2, 2, 0)
    assert r["total_final"] == round(precio * 2, 2), r
    fila = q("SELECT total_final, subtotal FROM ventas WHERE id_venta=%s", (r["id_venta"],))[0]
    assert float(fila["total_final"]) == round(precio * 2, 2), fila
    linea = q("SELECT precio_unitario_historico FROM detalle_ventas WHERE id_venta=%s", (r["id_venta"],))[0]
    assert float(linea["precio_unitario_historico"]) == precio, linea
    # discount=subtotal no deja la venta en $0.
    r = svc.registrar_venta(tienda, usuario, [{"id": id_producto, "qty": 1, "price": precio}], "efectivo", None, precio, 0, precio)
    assert r["total_final"] == precio, r
    id_venta = r["id_venta"]

    # ── 2) IDOR ─────────────────────────────────────────────
    q("INSERT INTO clientes (id_tienda, nombre, telefono) VALUES (%s, 'QA Ajeno', '3990009999')", (otra,))
    cliente_ajeno = q("SELECT LAST_INSERT_ID() AS id")[0]["id"]
    espera(svc.SalesNotFoundError, svc.registrar_venta, tienda, usuario,
           [{"id": id_producto, "qty": 1}], "efectivo", cliente_ajeno, 0, 0, 0)
    espera(svc.SalesNotFoundError, svc.get_detalle_venta, otra, id_venta)

    admin_otra = q("SELECT id_usuario FROM usuarios WHERE id_tienda=%s AND rol='Admin' AND estado_activo=1 LIMIT 1", (otra,))
    assert admin_otra, f"hace falta un Admin activo en la tienda {otra}"
    admin_otra = admin_otra[0]["id_usuario"]
    with app.test_client() as c:
        sesion(c, admin_otra, otra, "Admin")
        assert c.get(f"/pos/api/ventas/detalle/{id_venta}", headers=XHR).status_code == 404
        assert c.put(f"/api/inventario/{id_producto}", json={"nombre": "x", "categoria": "x"}).status_code == 404
        assert c.post(f"/pos/api/fiados/{cliente_ajeno}/abonar", json={"monto": 1}).status_code in (404, 409)
    print("OK 1-2: precio del servidor e IDOR entre tiendas")

    # ── 3) Sesion, rol y suscripcion desde la base ──────────
    with app.test_client() as c:
        sesion(c, 8, 4, "Admin")  # 8 es Cajero: la sesion miente sobre el rol
        assert c.get("/pos/api/b2b/clientes", headers=XHR).status_code == 403
        sesion(c, 8, 1, "Cajero")  # tienda falsa
        assert c.get("/pos/api/turno/estado", headers=XHR).status_code == 401
        sesion(c, 8, 4, "Cajero")
        assert c.get("/pos/api/turno/estado", headers=XHR).status_code == 200
        q("UPDATE usuarios SET estado_activo = 0 WHERE id_usuario = 8")
        assert c.get("/pos/api/turno/estado", headers=XHR).status_code == 401
        q("UPDATE usuarios SET estado_activo = 1 WHERE id_usuario = 8")
    with app.test_client() as c:
        sesion(c, 8, 4, "Cajero")
        q("UPDATE tiendas SET fecha_fin_suscripcion = CURDATE() WHERE id_tienda = 4")
        assert c.get("/pos/api/turno/estado", headers=XHR).status_code == 402
        assert c.get("/pos/caja").headers["Location"].endswith("/servicio-suspendido")
        assert c.get("/servicio-suspendido").status_code == 200
    print("OK 3: sesion revocada, rol releido y suscripcion vencida aplicada a APIs")

    # ── 4) Fuerza bruta y enumeracion ───────────────────────
    correo_real = q("SELECT correo FROM usuarios WHERE id_usuario = 8")[0]["correo"]
    with app.test_client() as c:
        def intento(correo, ip):
            return c.post("/login", json={"correo": correo, "contrasena": "Mala#Clave1"},
                          environ_base={"REMOTE_ADDR": ip})
        a = intento("noexiste@qa.test", "10.0.0.1")
        b = intento(correo_real, "10.0.0.2")
        assert a.status_code == b.status_code == 401
        assert a.get_json() == b.get_json(), "el login delata que correos existen"
        codigos = [intento(f"qa{i}@qa.test", "10.0.1.1").status_code for i in range(6)]
        assert codigos[:5] == [401] * 5 and codigos[5] == 429, codigos
        # Distribuido: una IP por intento, mismo correo (ya lleva 1 fallo).
        codigos = [intento(correo_real, f"10.0.2.{i}").status_code for i in range(10)]
        assert codigos[:9] == [401] * 9 and codigos[9] == 429, codigos
    print("OK 4: limite por IP y por cuenta, mensaje de login generico")

    # ── 5) Token de reset de un solo uso ────────────────────
    hash_actual = q("SELECT clave_hash FROM usuarios WHERE id_usuario = 8")[0]["clave_hash"]
    token = auth_service.create_reset_token(app.secret_key, correo_real, hash_actual)
    with app.test_client() as c:
        assert c.get(f"/reset-password/{token}").status_code == 200
        q("UPDATE usuarios SET clave_hash = CONCAT(clave_hash, 'x') WHERE id_usuario = 8")
        assert c.get(f"/reset-password/{token}").status_code == 302, "el token sobrevivio al cambio"
        viejo = auth_service.URLSafeTimedSerializer(app.secret_key).dumps(correo_real, salt="password-reset-salt")
        assert c.get(f"/reset-password/{viejo}").status_code == 302, "token de formato viejo aceptado"
    print("OK 5: token de reset invalido tras cambiar la contrasena")

    # ── 6) Fugas y configuracion ────────────────────────────
    with app.test_client() as c:
        for h in ({}, XHR):
            r = c.get("/__boom", headers=h)
            cuerpo = r.get_data(as_text=True)
            assert r.status_code == 500 and "SELECT" not in cuerpo and "Traceback" not in cuerpo, cuerpo
    for malo in ("<img/src=x/onerror=alert(1)>@a.co", "a\"onmouseover=x@a.co", "x@a.co<script>"):
        assert not auth_service.is_valid_email(malo), malo
    assert auth_service.is_valid_email("juan.perez+pos@tienda-1.com.co")
    js = open(os.path.join(RAIZ, "static", "js", "panel_master.js"), encoding="utf-8").read()
    assert "(${a.correo})" not in js and "${esc(a.correo)}" in js
    prod = subprocess.run(
        [sys.executable, "-c",
         "from app import create_app; a = create_app(); "
         "print(a.config['SESSION_COOKIE_SECURE'], a.config['SESSION_COOKIE_HTTPONLY'], a.debug)"],
        cwd=RAIZ, capture_output=True, text=True, env={**os.environ, "FLASK_ENV": "production", "FLASK_DEBUG": ""},
    )
    assert prod.stdout.split() == ["True", "True", "False"], (prod.stdout, prod.stderr[-500:])
    print("OK 6: 500 generico, correo con HTML rechazado, cookie Secure+HttpOnly en produccion")

    # ── 7) Precio de venta bloqueado para el Cajero ─────────
    q("UPDATE tiendas SET fecha_fin_suscripcion = NULL WHERE id_tienda = 4")  # la vencio el paso 3
    pid = inventory_service.create_producto(4, 6, "QA Precio", "QA", 1000, 2500, 5, None)

    def precio_de(id_prod):
        return float(q("SELECT precio_venta FROM productos WHERE id_producto=%s", (id_prod,))[0]["precio_venta"])

    base_put = {"nombre": "QA Precio", "categoria": "QA", "costo": 1000, "stock": 7, "stock_min": 1}
    with app.test_client() as c:
        sesion(c, 8, 4, "Cajero")
        for url in (f"/api/inventario/{pid}", f"/inventario/api/productos/{pid}"):
            r = c.put(url, json={**base_put, "venta": 1})
            assert r.status_code == 403 and "administrador" in r.get_json()["msg"], (r.status_code, r.get_json())
        assert c.put(f"/api/inventario/{pid}", json={**base_put, "venta": "NaN"}).status_code == 400
        assert precio_de(pid) == 2500
        # Sin precio (lo que manda su formulario) o con el mismo: edita el resto.
        assert c.put(f"/api/inventario/{pid}", json=base_put).status_code == 200
        assert c.put(f"/api/inventario/{pid}", json={**base_put, "venta": 2500}).status_code == 200
        fila = q("SELECT precio_venta, stock_actual FROM productos WHERE id_producto=%s", (pid,))[0]
        assert float(fila["precio_venta"]) == 2500 and float(fila["stock_actual"]) == 7, fila
        sesion(c, 6, 4, "Admin")
        assert c.put(f"/api/inventario/{pid}", json={**base_put, "venta": 3000}).status_code == 200
        assert precio_de(pid) == 3000
    js = open(os.path.join(RAIZ, "static", "js", "inventario.js"), encoding="utf-8").read()
    assert "fSale.disabled = esCajero;" in js and "venta: fSale.disabled ? undefined : sale" in js
    print("OK 7: Cajero sin cambio de precio (403 por API), Admin si, NaN rechazado")
finally:
    conn.rollback()
    conn.close()
