"""Chequeo del Panel de Control, las tarjetas de Ventas y las pestanas Mayorista.

  1) Servicios + BD dentro de UNA transaccion que se revierte al final:
     cuadre por trabajador (en curso / cuadrada / descuadrada, con gasto
     sacado de la base), ventas de hoy con su descripcion, utilidad con
     empaque y totales de Ventas de hoy / del mes.
  2) Rutas HTTP con el test client de Flask.

Requiere una tienda con turno abierto (el turno se cierra y se reabre dentro
de la transaccion; nada queda escrito).

    python scripts/check_panel_control.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

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
    """La misma conexion para todo; commit/close no hacen nada."""

    def __getattr__(self, name):
        return getattr(conn, name)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


from app.routes import core  # noqa: E402
from app.services import cartera_service as cart  # noqa: E402
from app.services import inventory_service as inv  # noqa: E402
from app.services import sales_service as svc  # noqa: E402

for modulo in (svc, cart, inv, core):
    modulo.get_db = lambda: _NoCommit()


def fila(sql, params=()):
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    return cur.fetchone()


def tarjeta(tienda, uid):
    return next(p for p in svc.get_rendimiento_personal(tienda) if p["id"] == uid)


# ══════════════════════════════════════════════════════════════
# BLOQUE 1 — SERVICIOS Y BASE DE DATOS
# ══════════════════════════════════════════════════════════════
try:
    base = fila(
        "SELECT t.id_tienda, t.id_usuario_apertura AS id_usuario FROM turnos_caja t "
        "INNER JOIN usuarios u ON u.id_usuario = t.id_usuario_apertura AND u.estado_activo = 1 "
        "WHERE t.estado_turno = 'Abierto' LIMIT 1"
    )
    if not base:
        sys.exit("SKIP: no hay tienda con turno abierto.")
    tienda, usuario = base["id_tienda"], base["id_usuario"]
    cur = conn.cursor()
    # Turno propio y limpio para este chequeo (el real vuelve con el rollback).
    cur.execute("UPDATE turnos_caja SET estado_turno = 'Cerrado', fecha_cierre = NOW() "
                "WHERE id_tienda = %s AND estado_turno = 'Abierto'", (tienda,))

    totales_antes = svc.get_totales_ventas(tienda, "Admin", None)
    dash_antes = core._build_dashboard_data(tienda, "hoy")["finanzas"]

    # Rollo de 100 m: costo 500/m. Por metro a 1000, el rollo a 90000.
    cable = inv.create_producto(
        tienda, usuario, "QA Panel Cable", "QA", 500, 1000, 500, None, 5,
        unidad="Metro", empaque_nombre="Rollo", empaque_cantidad=100, precio_empaque=90000,
    )

    # ── 1) Turno en curso: base, ventas, gasto de la base ───
    svc.abrir_turno(tienda, usuario, 50000)
    v1 = svc.registrar_venta(tienda, usuario, [{"id": cable, "qty": 3, "pres": "unidad"}], "efectivo", None, 0, 0, 0)
    v2 = svc.registrar_venta(tienda, usuario, [{"id": cable, "qty": 1, "pres": "empaque"}], "nequi", None, 0, 0, 0)
    svc.crear_gasto(tienda, usuario, "QA", "hielo", "Efectivo", "Base", 2000)
    svc.crear_gasto(tienda, usuario, "QA", "caja fuerte", "Efectivo", "Caja Fuerte", 7000)  # no sale del cajon

    p = tarjeta(tienda, usuario)
    t = p["turno"]
    assert p["en_turno"] and t["abierto"] and t["estado"] == "En curso", t
    assert t["base"] == 50000 and t["apertura"], t
    # 50000 + 3000 efectivo - 2000 de la base; Nequi y Caja Fuerte no tocan el cajon.
    assert t["esperado"] == 51000 and t["gastos_de_base"] == 2000 and t["gastos_de_caja"] == 2000, t
    assert t["contado"] is None and t["diferencia"] is None, t
    assert p["ventas"]["efectivo"] >= 3000 and p["ventas"]["otros"] >= 90000, p["ventas"]
    assert p["gastos_hoy"] >= 9000, p["gastos_hoy"]
    detalle = {d["numero"]: d for d in p["detalle"]}
    n1 = fila("SELECT numero_venta FROM ventas WHERE id_venta = %s", (v1["id_venta"],))["numero_venta"]
    n2 = fila("SELECT numero_venta FROM ventas WHERE id_venta = %s", (v2["id_venta"],))["numero_venta"]
    assert detalle[n1]["items"] == "3 Metro x QA Panel Cable" and detalle[n1]["metodo"] == "Efectivo", detalle[n1]
    assert detalle[n2]["items"] == "1 Rollo x QA Panel Cable" and detalle[n2]["total"] == 90000, detalle[n2]
    assert p["detalle"][0]["numero"] == n2, "las ventas van de la mas reciente a la mas vieja"

    # ── 2) Cierre exacto: cuadrada ───────────────────────────
    svc.cerrar_turno(tienda, usuario, 51000)
    t = tarjeta(tienda, usuario)["turno"]
    assert not t["abierto"] and t["contado"] == 51000 and t["diferencia"] == 0 and t["estado"] == "Cuadrada", t
    assert not tarjeta(tienda, usuario)["en_turno"]

    # ── 3) Nuevo turno cerrado con faltante: descuadrada ────
    svc.abrir_turno(tienda, usuario, 20000)
    svc.registrar_venta(tienda, usuario, [{"id": cable, "qty": 5, "pres": "unidad"}], "efectivo", None, 0, 0, 0)
    svc.crear_gasto(tienda, usuario, "QA", "bolsas", "Efectivo", "Caja Menor", 1500)
    svc.cerrar_turno(tienda, usuario, 22000)   # esperado 20000 + 5000 - 1500 = 23500
    t = tarjeta(tienda, usuario)["turno"]
    assert t["esperado"] == 23500 and t["diferencia"] == -1500 and t["estado"] == "Descuadrada", t

    # ── 4) Finanzas del panel y tarjetas de Ventas ──────────
    dash = core._build_dashboard_data(tienda, "hoy")
    f = dash["finanzas"]
    assert round(f["ventas"] - dash_antes["ventas"], 2) == 3000 + 90000 + 5000, (f, dash_antes)
    # Utilidad: por metro (1000-500)*8 = 4000; el rollo 90000 - 500*100 = 40000.
    assert round(f["utilidad_bruta"] - dash_antes["utilidad_bruta"], 2) == 44000, f
    assert round(f["gastos"] - dash_antes["gastos"], 2) == 2000 + 7000 + 1500, f
    assert f["utilidad_neta"] == round(f["utilidad_bruta"] - f["gastos"], 2), f
    for clave in ("por_cobrar", "por_pagar", "deudores", "vencido", "ticket_promedio", "num_ventas"):
        assert clave in f, clave
    assert "chart" not in dash, "la grafica se elimino"
    assert any(x["id"] == usuario for x in dash["personal"])

    totales = svc.get_totales_ventas(tienda, "Admin", None)
    assert round(totales["hoy"] - totales_antes["hoy"], 2) == 98000, (totales, totales_antes)
    assert round(totales["mes"] - totales_antes["mes"], 2) == 98000, (totales, totales_antes)
    cajero = svc.get_totales_ventas(tienda, "Cajero", usuario)
    assert cajero["hoy"] <= totales["hoy"] and cajero["hoy"] >= 98000, cajero
    assert svc.get_totales_ventas(tienda, "Fantasma", usuario) == {"hoy": 0.0, "mes": 0.0}

    # Anular una venta la saca de las tarjetas.
    cur.execute("UPDATE ventas SET estado_venta = 'Anulada' WHERE id_venta = %s", (v2["id_venta"],))
    assert round(svc.get_totales_ventas(tienda, "Admin", None)["hoy"] - totales_antes["hoy"], 2) == 8000
    p = tarjeta(tienda, usuario)
    assert p["ventas"]["anuladas"] >= 1 and next(d for d in p["detalle"] if d["numero"] == n2)["estado"] == "Anulada"

    # ── 5) Deudas top, punto de equilibrio y modal del trabajador ──
    svc.abrir_turno(tienda, usuario, 1000)
    viejo = svc.crear_cliente_fiado(tienda, usuario, "QA Deudor Viejo", "3000000001", 1000)
    grande = svc.crear_cliente_fiado(tienda, usuario, "QA Deudor Grande", "3000000002", 987654321)
    cur.execute("UPDATE ventas SET fecha_creacion = '2000-01-01' WHERE id_cliente = %s", (viejo,))

    dash = core._build_dashboard_data(tienda, "hoy")
    antiguas, mayores = dash["deudas_antiguas"], dash["deudas_mayores"]
    assert antiguas[0]["id"] == viejo and antiguas[0]["dias"] > 9000, antiguas
    assert mayores[0]["id"] == grande and mayores[0]["saldo"] == 987654321, mayores
    assert [x["dias"] for x in antiguas] == sorted((x["dias"] for x in antiguas), reverse=True), antiguas
    assert [x["saldo"] for x in mayores] == sorted((x["saldo"] for x in mayores), reverse=True), mayores
    assert len(antiguas) <= 5 and len(mayores) <= 5
    try:
        cart.get_top_deudores(tienda, "saldo DESC; DROP TABLE ventas")
        raise AssertionError("orden fuera de la lista blanca")
    except KeyError:
        pass

    f = dash["finanzas"]
    assert f["gastos"] > 0 and f["utilidad_bruta"] > 0, f
    assert abs(f["punto_equilibrio"] - f["gastos"] * f["ventas"] / f["utilidad_bruta"]) < 0.01, f
    assert core._build_dashboard_data(tienda, "hoy", "2001-01-01")["finanzas"]["punto_equilibrio"] == 0.0

    # El resumen del modal cuadra con la tarjeta del panel (mismo reparto).
    p = tarjeta(tienda, usuario)
    r = svc.get_resumen_ventas_cajero(tienda, usuario, "hoy")
    for k in ("cantidad", "anuladas", "total", "efectivo", "otros", "fiado"):
        assert round(r[k], 2) == round(p["ventas"][k], 2), (k, r, p["ventas"])
    assert r["fiado"] >= 987654321 and r["ticket_promedio"] == round(r["total"] / r["cantidad"], 2), r
    lista, filtro, meta = svc.get_ventas(tienda, "Admin", None, "hoy", None, 1, 100, id_cajero=usuario)
    assert filtro == "hoy" and meta["total"] == r["cantidad"] + r["anuladas"], (meta, r)
    nombre = fila("SELECT nombre_completo FROM usuarios WHERE id_usuario = %s", (usuario,))["nombre_completo"]
    assert lista and all(v["nombre_cajero"] == nombre for v in lista)
    enero = datetime.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    assert svc.periodo_bounds("anio")[:2] == ("anio", enero)
    assert svc.get_resumen_ventas_cajero(tienda, usuario, "anio")["total"] >= r["total"]

    print("OK bloque 1: cuadre en curso/cuadrada/descuadrada, gastos de base, ventas descritas, utilidad con empaque, totales, deudas top, equilibrio, modal")
finally:
    _real_rollback()
    conn.close()


# ══════════════════════════════════════════════════════════════
# BLOQUE 2 — RUTAS
# ══════════════════════════════════════════════════════════════
for modulo in (svc, cart, inv, core):
    modulo.get_db = __import__("database").get_db

from app import create_app  # noqa: E402

app = create_app()
app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
XHR = {"X-Requested-With": "XMLHttpRequest"}
USUARIOS_QA = {"Cajero": (8, 4), "Admin": (2, 1)}


def sesion(cliente, rol):
    id_usuario, id_tienda = USUARIOS_QA[rol]
    with cliente.session_transaction() as s:
        s["id_usuario"] = id_usuario
        s["id_tienda"] = id_tienda
        s["rol"] = rol


with app.test_client() as c:
    sesion(c, "Admin")
    html = c.get("/dashboard").get_data(as_text=True)
    assert 'id="dash-finanzas"' in html and 'id="dash-personal"' in html
    assert "chart.js" not in html and "graficaFinanzas" not in html, "la grafica debe haber desaparecido"
    d = c.get("/api/dashboard?filter=mes", headers=XHR).get_json()
    assert d["ok"] and d["filtro"] == "mes" and {"finanzas", "personal", "stock_alertas", "top_vendidos"} <= set(d)
    assert c.get("/api/dashboard?fecha=2026-03-13'--", headers=XHR).get_json()["ok"]
    assert {"deudas_antiguas", "deudas_mayores"} <= set(d) and "punto_equilibrio" in d["finanzas"], d.keys()
    for marca in ('id="modal-personal"', 'data-jem-filters="personal"', 'data-periodo="anio"',
                  'id="modal-detalle"', "ventas-comun.js", "filtros-paginacion.js"):
        assert marca in html, marca

    # Modal del trabajador: misma API de Ventas acotada por id_cajero.
    m = c.get("/pos/api/ventas?filtro=anio&id_cajero=2&page=1&limit=5", headers=XHR).get_json()
    assert m["ok"] and m["filtro"] == "anio" and m["totales"] is None, m
    assert {"total", "cantidad", "ticket_promedio", "efectivo", "otros", "fiado", "anuladas"} <= set(m["resumen"]), m
    assert c.get("/pos/api/ventas?fecha=2026-09-25&id_cajero=2", headers=XHR).get_json()["filtro"] == "fecha"
    for malo in ("id_cajero=abc", "id_cajero=0", "id_cajero=2&fecha=2026-13-45",
                 "id_cajero=2&fecha=25/09/2026", "id_cajero=2&fecha=2026-09-25T00:00"):
        r = c.get("/pos/api/ventas?" + malo, headers=XHR)
        assert r.status_code == 400 and r.get_json()["ok"] is False and r.get_json()["msg"], malo

    v = c.get("/pos/api/ventas?filtro=mes&page=1&limit=5", headers=XHR).get_json()
    assert set(v["totales"]) == {"hoy", "mes"} and v["totales"]["mes"] >= v["totales"]["hoy"], v["totales"]
    ventas_html = c.get("/pos/ventas").get_data(as_text=True)
    assert 'id="stat-hoy"' in ventas_html and 'id="stat-mes"' in ventas_html
    assert 'id="modal-detalle"' in ventas_html and "ventas-comun.js" in ventas_html
    assert ventas_html.index('id="stat-hoy"') < ventas_html.index('data-jem-filters'), "tarjetas encima de las capsulas"

    # Mayorista: dos pestanas en las dos pantallas; el nav marca Mayorista en ambas.
    for ruta, activa in (("/pos/clientes-proveer", "Clientes mayoristas"), ("/pos/venta-mayorista", "Venta mayorista")):
        h = c.get(ruta).get_data(as_text=True)
        assert h.count('class="inv-tab"') + h.count('class="inv-tab is-active"') == 2, ruta
        assert 'aria-current="page"' in h.split(activa)[0].rsplit("<a", 1)[1], (ruta, activa)
        assert 'bottom-btn active" aria-current="page" aria-label="Mayorista"' in h, ruta
    nav = c.get("/pos/caja").get_data(as_text=True)
    assert "Venta Mayorista</span>" not in nav, "Venta Mayorista vive dentro de Mayorista"

with app.test_client() as c:
    sesion(c, "Cajero")
    assert c.get("/api/dashboard", headers=XHR).status_code == 403
    nav = c.get("/pos/caja").get_data(as_text=True)
    assert 'href="/pos/venta-mayorista"' in nav and "/pos/clientes-proveer" not in nav
    h = c.get("/pos/venta-mayorista").get_data(as_text=True)
    assert "inv-tab" not in h, "el cajero no tiene pestana de clientes"
    v = c.get("/pos/api/ventas", headers=XHR).get_json()
    assert set(v["totales"]) == {"hoy", "mes"}
    # El Cajero no puede pedir las ventas de otro: id_cajero se ignora.
    v = c.get("/pos/api/ventas?id_cajero=2", headers=XHR).get_json()
    assert v["ok"] and v["filtro"] == "24h" and v["resumen"] is None, v

print("OK bloque 2: panel sin grafica, API, tarjetas de Ventas, pestanas Mayorista por rol")
