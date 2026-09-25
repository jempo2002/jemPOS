"""Chequeo del modulo Cartera (por cobrar / por pagar) y B2B contra la BD de .env.

Dos bloques:
  1) Servicios + BD dentro de UNA transaccion que se revierte al final:
     no deja datos. Cubre descuento mayorista, dashboard B2B, pagos parciales,
     validaciones y ausencia de registros huerfanos.
  2) Rutas HTTP con el test client de Flask: autenticacion y rol por endpoint.

Requiere migrations/2026-09-22_cartera_b2b.sql aplicada y una tienda con turno
abierto y un producto activo no preparado.

    python scripts/check_cartera_b2b.py
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
from app.services import sales_service as svc  # noqa: E402

_get_db_real = svc.get_db
svc.get_db = lambda: _NoCommit()
cart.get_db = lambda: _NoCommit()

Validacion = svc.SalesValidationError
NoEncontrado = svc.SalesNotFoundError
Conflicto = svc.SalesConflictError


def espera(excs, fn, *args, **kwargs):
    """Afirma que fn(...) levanta una de las excepciones dadas."""
    try:
        fn(*args, **kwargs)
    except excs:
        return
    raise AssertionError(f"{fn.__name__} debio fallar con {excs}: {args} {kwargs}")


def venta_de(id_venta):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT subtotal, tipo_descuento, valor_descuento, descuento_aplicado, "
        "total_final, observaciones FROM ventas WHERE id_venta = %s",
        (id_venta,),
    )
    return cur.fetchone()


def cuenta_de(cuentas, id_cuenta):
    return next(c for c in cuentas if c["id"] == id_cuenta)


# ══════════════════════════════════════════════════════════════
# BLOQUE 1 — SERVICIOS Y BASE DE DATOS
# ══════════════════════════════════════════════════════════════
try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT t.id_tienda, t.id_usuario_apertura AS id_usuario, "
        "       p.id_producto, p.precio_venta "
        "FROM turnos_caja t "
        "JOIN productos p ON p.id_tienda = t.id_tienda "
        "WHERE t.estado_turno = 'Abierto' AND p.estado_activo = 1 AND p.es_preparado = 0 "
        "LIMIT 1"
    )
    base = cur.fetchone()
    if not base:
        sys.exit("SKIP: no hay tienda con turno abierto y producto activo.")

    tienda = base["id_tienda"]
    usuario = base["id_usuario"]
    precio = float(base["precio_venta"])
    producto = base["id_producto"]
    cur.execute("UPDATE productos SET stock_actual = stock_actual + 50 WHERE id_producto = %s", (producto,))
    item = [{"id": producto, "qty": 1, "price": precio}]

    # ── 1) Listas mayoristas ────────────────────────────────
    id_lista = cart.crear_lista_precios(tienda, usuario, "QA Mayorista 10", 10, 0)
    listas = cart.get_listas_precios(tienda)
    lista = next(l for l in listas if l["id"] == id_lista)
    assert lista["descuento_pct"] == 10.0 and lista["min_pedidos"] == 0, lista

    espera(Conflicto, cart.crear_lista_precios, tienda, usuario, "QA Mayorista 10", 5, 0)
    espera(Validacion, cart.crear_lista_precios, tienda, usuario, "QA Mala", 101, 0)
    espera(Validacion, cart.crear_lista_precios, tienda, usuario, "QA Mala", -1, 0)
    espera(Validacion, cart.crear_lista_precios, tienda, usuario, "QA Mala", "diez", 0)
    espera(Validacion, cart.crear_lista_precios, tienda, usuario, "", 10, 0)

    # ── 2) Cliente B2B con lista asignada ───────────────────
    cid = cart.upsert_cliente_b2b(tienda, usuario, "QA Distribuidora", "3990001122", "900123456-7", id_lista)
    clientes = cart.get_clientes_b2b(tienda)
    cliente = next(c for c in clientes if c["id"] == cid)
    assert cliente["lista"]["id"] == id_lista and cliente["pedidos"] == 0, cliente
    assert cliente["frecuencia_dias"] is None, "sin pedidos no hay frecuencia"
    # La respuesta solo trae lo que pinta la vista: nada de cedula ni direccion.
    assert set(cliente) == {
        "id", "name", "phone", "nit", "debt", "pedidos", "comprado",
        "ticket_promedio", "frecuencia_dias", "dias_sin_comprar", "lista",
    }, sorted(cliente)

    espera(Validacion, cart.upsert_cliente_b2b, tienda, usuario, "QA", "123", None, None)
    espera(Validacion, cart.upsert_cliente_b2b, tienda, usuario, "", "3990001133", None, None)
    espera(NoEncontrado, cart.upsert_cliente_b2b, tienda, usuario, "QA", "3990001144", None, 99999999)

    # ── 3) Descuento mayorista automatico al cobrar ─────────
    r1 = svc.registrar_venta(tienda, usuario, item, "efectivo", cid, precio, precio, 0)
    esperado = round(precio * 0.10, 2)
    assert r1["descuento_b2b"] == esperado, (r1["descuento_b2b"], esperado)
    assert r1["total_final"] == round(precio - esperado, 2), r1
    fila = venta_de(r1["id_venta"])
    assert fila["tipo_descuento"] == "PORCENTAJE", fila
    assert float(fila["valor_descuento"]) == 10.0, fila
    assert float(fila["descuento_aplicado"]) == esperado, fila
    assert float(fila["total_final"]) == round(precio - esperado, 2), fila
    assert "Mayorista" in (fila["observaciones"] or ""), fila

    # El porcentaje NO puede llegar del navegador: mandar otro no cambia nada.
    r2 = svc.registrar_venta(tienda, usuario, item, "efectivo", cid, precio, precio, 99999)
    assert r2["descuento_b2b"] == esperado, r2

    # ── 4) Recurrencia: la lista con minimo alto no aplica ──
    id_lista_alta = cart.crear_lista_precios(tienda, usuario, "QA Mayorista 99 pedidos", 20, 99)
    cart.asignar_lista_cliente(tienda, usuario, cid, id_lista_alta)
    r3 = svc.registrar_venta(tienda, usuario, item, "efectivo", cid, precio, precio, 0)
    assert r3["descuento_b2b"] == 0.0, r3
    assert venta_de(r3["id_venta"])["tipo_descuento"] == "NINGUNO"

    # "Desde el pedido N": un cliente nuevo con N=2 no descuenta en su primera
    # compra y si en la segunda.
    id_lista_2 = cart.crear_lista_precios(tienda, usuario, "QA Desde el 2", 15, 2)
    cid2 = cart.upsert_cliente_b2b(tienda, usuario, "QA Segundo Pedido", "3990002255", None, id_lista_2)
    p1 = svc.registrar_venta(tienda, usuario, item, "efectivo", cid2, precio, precio, 0)
    assert p1["descuento_b2b"] == 0.0, p1
    p2 = svc.registrar_venta(tienda, usuario, item, "efectivo", cid2, precio, precio, 0)
    assert p2["descuento_b2b"] == round(precio * 0.15, 2), p2

    # Y con N=1 descuenta desde la primera compra, igual que N=0.
    id_lista_1 = cart.crear_lista_precios(tienda, usuario, "QA Desde el 1", 5, 1)
    cid3 = cart.upsert_cliente_b2b(tienda, usuario, "QA Primer Pedido", "3990003366", None, id_lista_1)
    p3 = svc.registrar_venta(tienda, usuario, item, "efectivo", cid3, precio, precio, 0)
    assert p3["descuento_b2b"] == round(precio * 0.05, 2), p3

    # Cliente sin lista: tampoco descuenta.
    cart.asignar_lista_cliente(tienda, usuario, cid, None)
    r4 = svc.registrar_venta(tienda, usuario, item, "efectivo", cid, precio, precio, 0)
    assert r4["descuento_b2b"] == 0.0, r4
    cart.asignar_lista_cliente(tienda, usuario, cid, id_lista)

    espera(NoEncontrado, cart.asignar_lista_cliente, tienda, usuario, cid, 99999999)
    espera(NoEncontrado, cart.asignar_lista_cliente, tienda, usuario, 99999999, id_lista)

    # ── 5) Dashboard del cliente comercial ──────────────────
    dash = cart.get_cliente_b2b_dashboard(tienda, cid)
    assert dash["pedidos"] == 4, dash["pedidos"]
    assert dash["ticket_promedio"] > 0, dash
    assert round(dash["ticket_promedio"], 2) == round(dash["comprado"] / dash["pedidos"], 2), dash
    assert dash["frecuencia_dias"] == 0.0, dash["frecuencia_dias"]  # 4 pedidos el mismo dia
    top = dash["top_productos"]
    assert top and top[0]["unidades"] == 4.0, top
    espera(NoEncontrado, cart.get_cliente_b2b_dashboard, tienda, 99999999)

    # Aislamiento por tienda: el id de otra tienda no se puede leer.
    cur.execute("SELECT id_cliente FROM clientes WHERE id_tienda <> %s LIMIT 1", (tienda,))
    otro = cur.fetchone()
    if otro:
        espera(NoEncontrado, cart.get_cliente_b2b_dashboard, tienda, otro["id_cliente"])

    # ── 6) Cuentas por cobrar: mora y tipo ──────────────────
    svc.registrar_venta(tienda, usuario, item, "fiado", None, precio, precio,
                        0, {"id": cid, "nombre": "QA Distribuidora", "telefono": "3990001122"})
    cobrar = next(c for c in svc.get_fiados_clientes(tienda) if c["id"] == cid)
    assert cobrar["tipo"] == "B2B", cobrar
    assert cobrar["debt"] > 0 and cobrar["dias_mora"] == 0, cobrar

    # ── 7) Cuentas por pagar ────────────────────────────────
    id_cta = cart.crear_cuenta_por_pagar(
        tienda, usuario, "Nomina", "QA Nomina quincena", "detalle qa", 100000, "2026-10-05", None
    )
    cta = cuenta_de(cart.get_cuentas_por_pagar(tienda), id_cta)
    assert cta["total"] == 100000.0 and cta["saldo"] == 100000.0 and cta["estado"] == "Pendiente", cta

    # Pago parcial -> sigue pendiente con el saldo correcto, y genera su gasto.
    res = cart.pagar_cuenta_por_pagar(tienda, usuario, id_cta, 40000, "transferencia")
    assert res["saldo"] == 60000.0 and res["estado"] == "Pendiente", res
    assert cuenta_de(cart.get_cuentas_por_pagar(tienda), id_cta)["saldo"] == 60000.0

    # El gasto automatico: monto exacto, concepto con deuda y origen, fuente OK.
    cur.execute(
        "SELECT concepto, descripcion, monto, fuente_dinero FROM gastos_caja WHERE id_gasto = %s",
        (res["id_gasto"],),
    )
    gasto = cur.fetchone()
    assert gasto is not None, "el pago no genero gasto"
    assert float(gasto["monto"]) == 40000.0, gasto
    assert gasto["concepto"] == "Abono a deuda de QA Nomina quincena - Origen: Transferencia", gasto
    assert gasto["fuente_dinero"] == "Bancos", gasto
    assert f"#{id_cta}" in (gasto["descripcion"] or ""), gasto

    # Origen fuera de la lista estricta: 400, y NADA se toca (ni deuda ni gasto).
    cur.execute("SELECT COUNT(*) AS n FROM gastos_caja WHERE id_tienda = %s", (tienda,))
    gastos_antes = cur.fetchone()["n"]
    for malo in (None, "", "bancos", "efectivo", "CAJA CHICA", "'; DROP TABLE gastos_caja;--", 123):
        espera(Validacion, cart.pagar_cuenta_por_pagar, tienda, usuario, id_cta, 1000, malo)
    assert cuenta_de(cart.get_cuentas_por_pagar(tienda), id_cta)["saldo"] == 60000.0
    cur.execute("SELECT COUNT(*) AS n FROM gastos_caja WHERE id_tienda = %s", (tienda,))
    assert cur.fetchone()["n"] == gastos_antes, "un origen invalido dejo gasto"

    # Mayusculas/espacios si se aceptan (la lista se compara normalizada).
    assert cart._resolver_origen("  Caja Fuerte ")["fuente_dinero"] == "Caja Fuerte"

    # No se puede pagar mas que el saldo, y el gasto tampoco queda.
    espera(Validacion, cart.pagar_cuenta_por_pagar, tienda, usuario, id_cta, 60001, "transferencia")
    espera(Validacion, cart.pagar_cuenta_por_pagar, tienda, usuario, id_cta, 0, "transferencia")
    espera(Validacion, cart.pagar_cuenta_por_pagar, tienda, usuario, id_cta, "mil", "transferencia")
    cur.execute("SELECT COUNT(*) AS n FROM gastos_caja WHERE id_tienda = %s", (tienda,))
    assert cur.fetchone()["n"] == gastos_antes, "un pago rechazado dejo gasto"

    # Pago desde Caja Menor: descuenta del turno abierto (atomico con el abono).
    cur.execute(
        "SELECT id_turno, COALESCE(monto_final_esperado, monto_inicial, 0) AS esperado "
        "FROM turnos_caja WHERE id_tienda = %s AND estado_turno = 'Abierto' LIMIT 1",
        (tienda,),
    )
    turno = cur.fetchone()
    res = cart.pagar_cuenta_por_pagar(tienda, usuario, id_cta, 10000, "caja menor")
    cur.execute(
        "SELECT COALESCE(monto_final_esperado, 0) AS esperado FROM turnos_caja WHERE id_turno = %s",
        (turno["id_turno"],),
    )
    assert float(cur.fetchone()["esperado"]) == float(turno["esperado"]) - 10000, "no descontó de la caja"
    cur.execute("SELECT fuente_dinero FROM gastos_caja WHERE id_gasto = %s", (res["id_gasto"],))
    assert cur.fetchone()["fuente_dinero"] == "Caja Menor"

    # Pago final -> Pagada, y no se puede volver a pagar.
    res = cart.pagar_cuenta_por_pagar(tienda, usuario, id_cta, 50000, "caja fuerte")
    assert res["saldo"] == 0.0 and res["estado"] == "Pagada", res
    espera(Conflicto, cart.pagar_cuenta_por_pagar, tienda, usuario, id_cta, 1, "transferencia")
    espera(NoEncontrado, cart.anular_cuenta_por_pagar, tienda, usuario, id_cta)
    espera(NoEncontrado, cart.pagar_cuenta_por_pagar, tienda, usuario, 99999999, 100, "transferencia")

    # Anular una pendiente: desaparece del listado, la fila se conserva.
    id_anular = cart.crear_cuenta_por_pagar(tienda, usuario, "Servicios", "QA Energia", None, 50000, None, None)
    cart.anular_cuenta_por_pagar(tienda, usuario, id_anular)
    assert all(c["id"] != id_anular for c in cart.get_cuentas_por_pagar(tienda))
    cur.execute("SELECT estado FROM cuentas_por_pagar WHERE id_cuenta = %s", (id_anular,))
    assert cur.fetchone()["estado"] == "Anulada"
    espera(NoEncontrado, cart.anular_cuenta_por_pagar, tienda, usuario, id_anular)

    # Validaciones de entrada (letras en monto, categoria fuera del enum, fechas).
    espera(Validacion, cart.crear_cuenta_por_pagar, tienda, usuario, "Nomina", "QA", None, "abc", None, None)
    espera(Validacion, cart.crear_cuenta_por_pagar, tienda, usuario, "Nomina", "QA", None, 0, None, None)
    espera(Validacion, cart.crear_cuenta_por_pagar, tienda, usuario, "Nomina", "QA", None, -5, None, None)
    espera(Validacion, cart.crear_cuenta_por_pagar, tienda, usuario, "Hackeo", "QA", None, 1000, None, None)
    espera(Validacion, cart.crear_cuenta_por_pagar, tienda, usuario, "Nomina", "", None, 1000, None, None)
    espera(Validacion, cart.crear_cuenta_por_pagar, tienda, usuario, "Nomina", "QA", None, 1000, "2026-13-40", None)
    espera(NoEncontrado, cart.crear_cuenta_por_pagar, tienda, usuario, "Proveedor", "QA", None, 1000, None, 99999999)

    # ── 8) Resumen de las dos pestanas ──────────────────────
    resumen = cart.get_resumen_cartera(tienda)
    assert resumen["por_cobrar"] > 0 and resumen["deudores"] >= 1, resumen
    assert resumen["por_pagar"] >= 0 and resumen["vencido"] >= 0, resumen
    # El encabezado cuadra con las filas: la suma de deudas listadas nunca
    # supera el total (un cliente dado de baja sale de las dos cifras).
    listado = sum(c["debt"] for c in svc.get_fiados_clientes(tienda))
    assert round(listado, 2) == round(resumen["por_cobrar"], 2), (listado, resumen["por_cobrar"])

    # Borrar un cliente saca su deuda del listado Y del total.
    svc.delete_cliente_fiado(tienda, usuario, cid)
    assert all(c["id"] != cid for c in svc.get_fiados_clientes(tienda))
    resumen2 = cart.get_resumen_cartera(tienda)
    assert round(resumen2["por_cobrar"], 2) == round(resumen["por_cobrar"] - cobrar["debt"], 2), (
        resumen2["por_cobrar"], resumen["por_cobrar"], cobrar["debt"]
    )
    cur.execute("UPDATE clientes SET estado_activo = 1 WHERE id_cliente = %s", (cid,))

    # ── 9) Sin datos huerfanos al eliminar ──────────────────
    # Proveedor borrado: la obligacion sobrevive sin proveedor (ON DELETE SET NULL).
    cur.execute(
        "INSERT INTO proveedores (id_tienda, nombre_empresa, celular) VALUES (%s, 'QA Prov', '3001112233')",
        (tienda,),
    )
    id_prov = cur.lastrowid
    id_cta_prov = cart.crear_cuenta_por_pagar(
        tienda, usuario, "Proveedor", "QA Factura", None, 30000, None, id_prov
    )
    cur.execute("DELETE FROM proveedores WHERE id_proveedor = %s", (id_prov,))
    cur.execute("SELECT id_proveedor, estado FROM cuentas_por_pagar WHERE id_cuenta = %s", (id_cta_prov,))
    fila_cta = cur.fetchone()
    assert fila_cta is not None and fila_cta["id_proveedor"] is None, fila_cta
    assert cuenta_de(cart.get_cuentas_por_pagar(tienda), id_cta_prov)["proveedor"] == ""

    # Lista eliminada (soft): el cliente queda sin lista y sin descuento.
    cart.eliminar_lista_precios(tienda, usuario, id_lista)
    cur.execute("SELECT id_lista_precios FROM clientes WHERE id_cliente = %s", (cid,))
    assert cur.fetchone()["id_lista_precios"] is None, "el cliente quedo apuntando a una lista inactiva"
    r5 = svc.registrar_venta(tienda, usuario, item, "efectivo", cid, precio, precio, 0)
    assert r5["descuento_b2b"] == 0.0, r5
    espera(NoEncontrado, cart.eliminar_lista_precios, tienda, usuario, id_lista)

    # Lista borrada fisicamente: la FK limpia la referencia del cliente.
    cart.asignar_lista_cliente(tienda, usuario, cid, id_lista_alta)
    cur.execute("DELETE FROM listas_precios WHERE id_lista = %s", (id_lista_alta,))
    cur.execute("SELECT id_lista_precios FROM clientes WHERE id_cliente = %s", (cid,))
    assert cur.fetchone()["id_lista_precios"] is None, "FK sin ON DELETE SET NULL"

    print("OK bloque 1: descuento mayorista, dashboard B2B, cuentas por pagar, validaciones, sin huerfanos")
finally:
    _real_rollback()
    conn.close()
    # El bloque 2 usa la BD de verdad: se devuelve el get_db real.
    svc.get_db = _get_db_real
    cart.get_db = _get_db_real


# ══════════════════════════════════════════════════════════════
# BLOQUE 2 — RUTAS: AUTENTICACION Y ROLES
# ══════════════════════════════════════════════════════════════
from app import create_app  # noqa: E402

app = create_app()
app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)


# login_required relee rol y tienda de la base: usuarios reales del volcado.
USUARIOS_QA = {"Cajero": (8, 4), "Admin": (2, 1)}


def sesion(cliente, rol):
    id_usuario, id_tienda = USUARIOS_QA[rol]
    with cliente.session_transaction() as s:
        s["id_usuario"] = id_usuario
        s["id_tienda"] = id_tienda
        s["rol"] = rol


# Rutas que exigen perfil administrativo.
SOLO_ADMIN = [
    ("GET", "/pos/clientes-proveer"),
    ("GET", "/pos/api/cartera/por-pagar"),
    ("POST", "/pos/api/cartera/por-pagar"),
    ("POST", "/pos/api/cartera/por-pagar/1/pagar"),
    ("DELETE", "/pos/api/cartera/por-pagar/1"),
    ("GET", "/pos/api/b2b/listas"),
    ("POST", "/pos/api/b2b/listas"),
    ("PUT", "/pos/api/b2b/listas/1"),
    ("DELETE", "/pos/api/b2b/listas/1"),
    ("GET", "/pos/api/b2b/clientes"),
    ("POST", "/pos/api/b2b/clientes"),
    ("GET", "/pos/api/b2b/clientes/1"),
    ("PUT", "/pos/api/b2b/clientes/1/lista"),
    ("DELETE", "/pos/api/fiados/1"),
]

with app.test_client() as c:
    # Sin sesion: HTML redirige al login, API responde 401.
    assert c.get("/pos/clientes-proveer").status_code == 302
    for metodo, ruta in SOLO_ADMIN:
        if ruta.startswith("/pos/api"):
            r = c.open(ruta, method=metodo, json={})
            assert r.status_code == 401, (metodo, ruta, r.status_code)

with app.test_client() as c:
    sesion(c, "Cajero")
    for metodo, ruta in SOLO_ADMIN:
        es_api = ruta.startswith("/pos/api")
        # El body JSON solo va en las APIs: enviarlo en una vista HTML la haria
        # pasar por API y devolver 403 en vez del redirect al login.
        r = c.open(ruta, method=metodo, json={}) if es_api else c.open(ruta, method=metodo)
        esperado = 403 if es_api else 302
        assert r.status_code == esperado, (metodo, ruta, r.status_code)

    # El cajero si ve la pestana por cobrar, pero el resumen no le expone
    # los totales de obligaciones del negocio.
    assert c.get("/pos/fiados").status_code == 200
    resumen = c.get("/pos/api/cartera/resumen").get_json()["resumen"]
    assert set(resumen) == {"por_cobrar", "deudores"}, resumen

with app.test_client() as c:
    sesion(c, "Admin")
    assert c.get("/pos/clientes-proveer").status_code == 200
    for ruta in ("/pos/api/cartera/por-pagar", "/pos/api/b2b/listas", "/pos/api/b2b/clientes"):
        assert c.get(ruta).status_code == 200, ruta
    resumen = c.get("/pos/api/cartera/resumen").get_json()["resumen"]
    assert set(resumen) == {"por_cobrar", "deudores", "por_pagar", "obligaciones", "vencido"}, resumen

print("OK bloque 2: rutas protegidas por autenticacion y rol, resumen filtrado por perfil")
