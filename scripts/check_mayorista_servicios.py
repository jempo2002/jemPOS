"""Chequeo de Venta Mayorista, servicios, unidades/empaque, factura y cartera.

Dos bloques, igual que check_cartera_b2b.py:
  1) Servicios + BD dentro de UNA transaccion que se revierte al final.
  2) Rutas HTTP con el test client de Flask.

Requiere migrations/2026-09-25_mayorista_servicios_unidades.sql aplicada y una
tienda con turno abierto.

    python scripts/check_mayorista_servicios.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
_real_rollback = conn.rollback


class _NoCommit:
    """La misma conexion para todo el servicio; commit/close no hacen nada."""

    def __getattr__(self, name):
        return getattr(conn, name)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


from app.services import cartera_service as cart  # noqa: E402
from app.services import inventory_service as inv  # noqa: E402
from app.services import sales_service as svc  # noqa: E402

_get_db_real = svc.get_db
for modulo in (svc, cart, inv):
    modulo.get_db = lambda: _NoCommit()

Validacion = svc.SalesValidationError
NoEncontrado = svc.SalesNotFoundError
Conflicto = svc.SalesConflictError


def espera(excs, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except excs:
        return
    raise AssertionError(f"{fn.__name__} debio fallar con {excs}: {args} {kwargs}")


def fila(sql, params=()):
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    return cur.fetchone()


def filas(sql, params=()):
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    return cur.fetchall()


# ══════════════════════════════════════════════════════════════
# BLOQUE 1 — SERVICIOS Y BASE DE DATOS
# ══════════════════════════════════════════════════════════════
try:
    base = fila(
        "SELECT id_tienda, id_usuario_apertura AS id_usuario FROM turnos_caja "
        "WHERE estado_turno = 'Abierto' LIMIT 1"
    )
    if not base:
        sys.exit("SKIP: no hay tienda con turno abierto.")
    tienda, usuario = base["id_tienda"], base["id_usuario"]

    # ── 1) Inventario: unidad, empaque, precio mayorista, servicio ──
    cable = inv.create_producto(
        tienda, usuario, "QA Cable", "QA", 500, 1000, 250, None, 5,
        unidad="Metro", mayorista=800, empaque_nombre="Rollo", empaque_cantidad=100, precio_empaque=90000,
    )
    tornillo = inv.create_producto(tienda, usuario, "QA Tornillo", "QA", 50, 100, 40, None)  # sin mayorista
    instalacion = inv.create_producto(
        tienda, usuario, "QA Instalacion", "QA", 0, 20000, 99, None, tipo="Servicio", mayorista=15000,
    )
    p = fila("SELECT * FROM productos WHERE id_producto = %s", (cable,))
    assert p["unidad_medida"] == "Metro" and p["tipo"] == "Producto", p
    assert float(p["precio_mayorista"]) == 800 and p["empaque_nombre"] == "Rollo", p
    assert float(p["empaque_cantidad"]) == 100 and float(p["precio_empaque"]) == 90000, p
    s = fila("SELECT tipo, stock_actual, stock_minimo_alerta, empaque_nombre FROM productos WHERE id_producto = %s",
             (instalacion,))
    assert s["tipo"] == "Servicio" and s["stock_actual"] is None and s["stock_minimo_alerta"] is None, s

    # Validaciones del modal (ValueError -> 400 en la ruta).
    espera(ValueError, inv.create_producto, tienda, usuario, "QA x", "QA", 1, 1, 1, None,
           empaque_nombre="Rollo")  # empaque sin cantidad ni precio
    espera(ValueError, inv.create_producto, tienda, usuario, "QA x", "QA", 1, 1, 1, None, unidad="Parsec")
    espera(ValueError, inv.create_producto, tienda, usuario, "QA x", "QA", 1, 1, 2.5, None)  # 2.5 unidades
    espera(ValueError, inv.create_producto, tienda, usuario, "QA x", "QA", 1, 1, 1, None, tipo="Otro")
    espera(ValueError, inv.create_producto, tienda, usuario, "QA x", "QA", 1, 1, 1, None, mayorista="NaN")
    # Fraccion valida en unidad fraccionable.
    arroz = inv.create_producto(tienda, usuario, "QA Arroz", "QA", 1000, 2000, 10.5, None, unidad="Libra",
                                mayorista=1700)

    listado = {x["id"]: x for x in inv.list_inventario_api(tienda)}
    assert listado[cable]["mayorista"] == 800.0 and listado[cable]["unidad"] == "Metro", listado[cable]
    assert listado[arroz]["stock"] == 10.5 and isinstance(listado[arroz]["stock"], float), listado[arroz]
    assert listado[instalacion]["tipo"] == "Servicio" and listado[tornillo]["mayorista"] is None

    # Cajero: no toca ningun precio (tampoco mayorista ni empaque); el resto si.
    editar = dict(nombre="QA Cable", categoria="QA", costo=500, venta=None, stock=250, proveedor_id=None,
                  stock_min=5, precio_bloqueado=True, unidad="Metro", empaque_nombre="Rollo",
                  empaque_cantidad=100, precio_empaque=90000)
    espera(PermissionError, inv.update_producto, tienda, usuario, cable, **{**editar, "mayorista": 1})
    espera(PermissionError, inv.update_producto, tienda, usuario, cable, **{**editar, "mayorista": 800,
                                                                          "precio_empaque": 1})
    inv.update_producto(tienda, usuario, cable, **{**editar, "mayorista": 800, "stock": 250})
    inv.update_producto(tienda, usuario, cable, **{**editar, "mayorista": 800, "precio_bloqueado": False})

    # Stock manual: fraccion en Metro si, en Unidad no, en servicio nunca.
    assert inv.add_stock(tienda, usuario, cable, 0.5) == 250.5
    espera(ValueError, inv.add_stock, tienda, usuario, tornillo, 1.5)
    espera(ValueError, inv.add_stock, tienda, usuario, instalacion, 1)
    mov = fila("SELECT motivo, stock_anterior, stock_posterior FROM movimientos_inventario "
               "WHERE id_producto = %s ORDER BY id_movimiento DESC LIMIT 1", (cable,))
    assert mov["motivo"] and float(mov["stock_posterior"]) == 250.5, mov

    # ── 2) Buscador de caja: detal vs mayorista ─────────────
    detal = {x["id"]: x for x in svc.get_caja_productos(tienda, "QA ")}
    assert detal[cable]["price"] == 1000 and detal[cable]["empaque"] == {
        "nombre": "Rollo", "cantidad": 100.0, "price": 90000.0}, detal[cable]
    assert detal[cable]["fraccionable"] and not detal[tornillo]["fraccionable"]
    assert detal[instalacion]["servicio"] and detal[instalacion]["stock"] is None
    mayor = {x["id"]: x for x in svc.get_caja_productos(tienda, "QA ", mayorista=True)}
    assert mayor[cable]["price"] == 800 and mayor[cable]["empaque"] is None, mayor[cable]
    assert tornillo not in mayor, "sin precio mayorista no se ofrece al por mayor"
    assert mayor[instalacion]["price"] == 15000

    # ── 3) Venta al detal: fraccion + empaque + servicio ────
    items = [
        {"id": cable, "qty": 2.5, "pres": "unidad", "price": 1},   # el price del navegador se ignora
        {"id": cable, "qty": 1, "pres": "empaque"},
        {"id": instalacion, "qty": 1},
    ]
    r = svc.registrar_venta(tienda, usuario, items, "nequi", None, 0, 0, 0)
    assert r["total_final"] == 2500 + 90000 + 20000, r
    assert "descuento_b2b" not in r, "sin descuento porcentual"
    stock = float(fila("SELECT stock_actual FROM productos WHERE id_producto = %s", (cable,))["stock_actual"])
    assert stock == 250.5 - 2.5 - 100, stock
    assert fila("SELECT stock_actual FROM productos WHERE id_producto = %s", (instalacion,))["stock_actual"] is None
    det = filas("SELECT cantidad, unidad_venta, precio_unitario_historico, subtotal_linea FROM detalle_ventas "
                "WHERE id_venta = %s ORDER BY id_detalle_venta", (r["id_venta"],))
    assert [(float(d["cantidad"]), d["unidad_venta"], float(d["subtotal_linea"])) for d in det] == [
        (2.5, "Metro", 2500.0), (1.0, "Rollo", 90000.0), (1.0, "Unidad", 20000.0)], det

    # Factura: metodo de pago, unidad y valor unitario por linea.
    factura = svc.get_detalle_venta(tienda, r["id_venta"])
    assert factura["metodo_pago"] == "Nequi/Daviplata", factura
    assert factura["items"][1] == {"producto": "QA Cable", "cantidad": 1.0, "unidad": "Rollo",
                                   "precio_unitario": 90000.0, "subtotal": 90000.0}, factura["items"]
    assert factura["cliente"] == "Mostrador" and factura["fecha"] and not factura["mayorista"]
    lista, _f, _m = svc.get_ventas(tienda, "Admin", usuario, "todas", None, 1, 5)
    assert next(v for v in lista if v["id_venta"] == r["id_venta"])["metodo_pago"] == "Nequi/Daviplata"

    # Enteros donde toca; stock acumulado entre lineas del mismo producto.
    espera(Validacion, svc.registrar_venta, tienda, usuario, [{"id": tornillo, "qty": 1.5}], "efectivo", None, 0, 0, 0)
    espera(Validacion, svc.registrar_venta, tienda, usuario, [{"id": cable, "qty": 0.5, "pres": "empaque"}],
           "efectivo", None, 0, 0, 0)
    espera(Validacion, svc.registrar_venta, tienda, usuario, [{"id": tornillo, "qty": 1, "pres": "empaque"}],
           "efectivo", None, 0, 0, 0)
    espera(Validacion, svc.registrar_venta, tienda, usuario, [{"id": cable, "qty": 1, "pres": "caja"}],
           "efectivo", None, 0, 0, 0)
    espera(Validacion, svc.registrar_venta, tienda, usuario, [{"id": cable, "qty": "NaN"}], "efectivo", None, 0, 0, 0)
    espera(Conflicto, svc.registrar_venta, tienda, usuario,
           [{"id": cable, "qty": 1, "pres": "empaque"}, {"id": cable, "qty": 50}], "efectivo", None, 0, 0, 0)
    assert float(fila("SELECT stock_actual FROM productos WHERE id_producto = %s", (cable,))["stock_actual"]) == 148.0

    # ── 4) Venta mayorista: precio fijo y cliente B2B obligatorio ──
    b2b = cart.upsert_cliente_b2b(tienda, usuario, "QA Ferreteria", "3990004455", "900555111-2")
    cur = conn.cursor()
    cur.execute("INSERT INTO clientes (id_tienda, nombre, telefono) VALUES (%s, 'QA Detal', '3990006677')", (tienda,))
    b2c = cur.lastrowid
    # Cliente con una lista porcentual heredada: ya no descuenta en ningun lado.
    cur.execute("INSERT INTO listas_precios (id_tienda, nombre, descuento_pct) VALUES (%s, 'QA Vieja 50', 50)",
                (tienda,))
    cur.execute("UPDATE clientes SET id_lista_precios = %s WHERE id_cliente = %s", (cur.lastrowid, b2b))

    linea = [{"id": cable, "qty": 10, "price": 1}]
    espera(Validacion, svc.registrar_venta, tienda, usuario, linea, "efectivo", None, 0, 0, 0, mayorista=True)
    espera(NoEncontrado, svc.registrar_venta, tienda, usuario, linea, "efectivo", b2c, 0, 0, 0, mayorista=True)
    espera(NoEncontrado, svc.registrar_venta, tienda, usuario, linea, "efectivo", 99999999, 0, 0, 0, mayorista=True)
    espera(Validacion, svc.registrar_venta, tienda, usuario, [{"id": tornillo, "qty": 1}], "efectivo", b2b,
           0, 0, 0, mayorista=True)
    espera(Validacion, svc.registrar_venta, tienda, usuario, [{"id": cable, "qty": 1, "pres": "empaque"}],
           "efectivo", b2b, 0, 0, 0, mayorista=True)

    m1 = svc.registrar_venta(tienda, usuario, linea, "efectivo", b2b, 0, 0, 0, mayorista=True)
    assert m1["total_final"] == 8000.0, m1  # 10 m x $800 fijo, no 10 x $1.000 ni -50%
    v = fila("SELECT id_cliente, tipo_descuento, descuento_aplicado, observaciones, estado_venta "
             "FROM ventas WHERE id_venta = %s", (m1["id_venta"],))
    assert v["id_cliente"] == b2b and v["tipo_descuento"] == "NINGUNO" and float(v["descuento_aplicado"]) == 0, v
    assert "Venta mayorista" in v["observaciones"], v
    assert svc.get_detalle_venta(tienda, m1["id_venta"])["mayorista"]

    # En Caja normal el mismo cliente paga precio de detal y sin porcentaje.
    d1 = svc.registrar_venta(tienda, usuario, linea, "efectivo", b2b, 0, 0, 0)
    assert d1["total_final"] == 10000.0, d1

    # Fiado mayorista: la deuda va al cliente B2B, sin el alta del modal Fiar.
    f1 = svc.registrar_venta(tienda, usuario, [{"id": instalacion, "qty": 2}], "fiado", b2b, 0, 0, 0,
                             None, mayorista=True)
    vf = fila("SELECT id_cliente, estado_venta, numero_venta, total_final FROM ventas WHERE id_venta = %s",
              (f1["id_venta"],))
    assert vf["id_cliente"] == b2b and vf["estado_venta"] == "Fiada/Pendiente", vf
    assert vf["numero_venta"].startswith("F") and float(vf["total_final"]) == 30000.0, vf
    assert svc.get_detalle_venta(tienda, f1["id_venta"])["metodo_pago"] == "Fiado"
    svc.abonar_fiado(tienda, usuario, b2b, 10000, "efectivo")
    assert svc.get_detalle_venta(tienda, f1["id_venta"])["metodo_pago"] == "Fiado (abonos: Efectivo)"

    # Dashboard Mayorista alimentado por las ventas mayoristas.
    dash = cart.get_cliente_b2b_dashboard(tienda, b2b)
    assert dash["pedidos"] == 3 and dash["comprado"] == 8000 + 10000 + 30000, dash
    assert dash["debt"] == 20000.0, dash
    assert "lista" not in dash, "las listas porcentuales ya no se exponen"
    minimos = cart.get_clientes_mayoristas_min(tienda)
    assert any(c["id"] == b2b for c in minimos) and all(c["id"] != b2c for c in minimos)
    assert set(minimos[0]) == {"id", "name", "nit"}, minimos[0]

    # ── 5) Cartera: el abono genera gasto "Cuentas por pagar" ──
    cur.execute("INSERT INTO proveedores (id_tienda, nombre_empresa, celular) VALUES (%s, 'QA Cables SAS', '3001112233')",
                (tienda,))
    prov = cur.lastrowid
    cta = cart.crear_cuenta_por_pagar(tienda, usuario, "Proveedor", "QA Factura 4312", None, 100000, None, prov)
    pago = cart.pagar_cuenta_por_pagar(tienda, usuario, cta, 40000, "transferencia")
    g = fila("SELECT concepto, descripcion, monto, fuente_dinero FROM gastos_caja WHERE id_gasto = %s",
             (pago["id_gasto"],))
    assert g["concepto"] == "Cuentas por pagar", g
    for parte in (f"#{cta}", "(Proveedor)", "Origen: Transferencia", "Pagado a: QA Cables SAS",
                  "Concepto: QA Factura 4312"):
        assert parte in g["descripcion"], (parte, g["descripcion"])
    assert float(g["monto"]) == 40000 and g["fuente_dinero"] == "Bancos", g
    # Sin proveedor: se le pago a lo que dice el concepto.
    cta2 = cart.crear_cuenta_por_pagar(tienda, usuario, "Nomina", "QA Nomina Ana", None, 5000, None, None)
    g2 = fila("SELECT concepto, descripcion FROM gastos_caja WHERE id_gasto = %s",
              (cart.pagar_cuenta_por_pagar(tienda, usuario, cta2, 5000, "caja fuerte")["id_gasto"],))
    assert g2["concepto"] == "Cuentas por pagar" and "Pagado a: QA Nomina Ana" in g2["descripcion"], g2
    assert "Cuentas por pagar" in svc.get_categorias_gastos(tienda)
    # Descripcion larga: se recorta a la columna sin perder cuenta ni origen.
    larga = cart._descripcion_gasto_cxp(7, {"categoria": "Otro", "concepto": "x" * 150}, "y" * 150, "Caja Menor")
    assert len(larga) == 255 and larga.startswith("Abono cuenta por pagar #7 (Otro) - Origen: Caja Menor"), larga

    print("OK bloque 1: unidades/empaque, servicios, precio mayorista fijo, factura con metodo, gasto de cartera")
finally:
    _real_rollback()
    conn.close()
    for modulo in (svc, cart, inv):
        modulo.get_db = _get_db_real


# ══════════════════════════════════════════════════════════════
# BLOQUE 2 — RUTAS
# ══════════════════════════════════════════════════════════════
from app import create_app  # noqa: E402

app = create_app()
app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
USUARIOS_QA = {"Cajero": (8, 4), "Admin": (2, 1)}
XHR = {"X-Requested-With": "XMLHttpRequest"}


def sesion(cliente, rol):
    id_usuario, id_tienda = USUARIOS_QA[rol]
    with cliente.session_transaction() as s:
        s["id_usuario"] = id_usuario
        s["id_tienda"] = id_tienda
        s["rol"] = rol


with app.test_client() as c:
    assert c.get("/pos/api/mayorista/clientes", headers=XHR).status_code == 401
    sesion(c, "Cajero")
    html = c.get("/pos/venta-mayorista").get_data(as_text=True)
    assert 'data-modo="mayorista"' in html and "mayorista-cliente" in html, "venta mayorista sin selector"
    assert 'data-modo="mayorista"' not in c.get("/pos/caja").get_data(as_text=True)
    r = c.get("/pos/api/mayorista/clientes", headers=XHR)
    assert r.status_code == 200 and r.get_json()["ok"], r.status_code
    # Proveedores y el modulo Mayorista siguen siendo de administracion.
    assert c.get("/inventario/proveedores").status_code == 302
    assert c.get("/pos/api/b2b/clientes", headers=XHR).status_code == 403
    nav = c.get("/pos/caja").get_data(as_text=True)
    # Venta Mayorista vive dentro de Mayorista: el cajero entra directo a la venta.
    assert 'href="/pos/venta-mayorista"' in nav and ">Proveedores<" not in nav and "Clientes a Proveer" not in nav

with app.test_client() as c:
    sesion(c, "Admin")
    assert c.get("/inventario/proveedores").status_code == 200
    nav = c.get("/pos/caja").get_data(as_text=True)
    for etiqueta in (">Proveedores<", ">Mayorista<"):
        assert etiqueta in nav, etiqueta
    inv_html = c.get("/inventario/").get_data(as_text=True)
    assert 'data-tab="servicios"' in inv_html and 'data-tab="proveedores"' not in inv_html
    assert 'id="f-unidad"' in inv_html and 'id="f-mayorista"' in inv_html and 'id="f-empaque"' in inv_html
    # Las listas porcentuales ya no existen como API.
    for metodo, ruta in (("GET", "/pos/api/b2b/listas"), ("POST", "/pos/api/b2b/listas"),
                         ("PUT", "/pos/api/b2b/clientes/1/lista")):
        assert c.open(ruta, method=metodo, json={}).status_code in (404, 405), ruta
    productos = c.get("/pos/api/caja/productos?mayorista=1", headers=XHR).get_json()["productos"]
    assert all(p["empaque"] is None for p in productos), productos[:1]

print("OK bloque 2: Venta Mayorista (dentro de Mayorista) para todo rol, Proveedores/Mayorista solo admin, listas retiradas")
