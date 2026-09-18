"""Chequeo del flujo "Fiar" de Caja contra la BD configurada en .env.

Todo corre en UNA transaccion que se revierte al final: no deja datos.
Requiere la migracion migrations/2026-09-16_clientes_cedula.sql y una tienda
con turno abierto.

    python scripts/check_fiado_caja.py
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


from app.services import sales_service as svc  # noqa: E402

svc.get_db = lambda: _NoCommit()


def deuda(id_tienda, id_cliente):
    return next(c["debt"] for c in svc.get_fiados_clientes(id_tienda) if c["id"] == id_cliente)


try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT t.id_tienda, t.id_usuario_apertura AS id_usuario, t.monto_final_esperado, p.id_producto, p.precio_venta "
        "FROM turnos_caja t JOIN productos p ON p.id_tienda = t.id_tienda "
        "WHERE t.estado_turno = 'Abierto' AND p.estado_activo = 1 AND p.es_preparado = 0 LIMIT 1"
    )
    base = cur.fetchone()
    if not base:
        sys.exit("SKIP: no hay tienda con turno abierto y producto activo.")
    cur.execute("UPDATE productos SET stock_actual = stock_actual + 10 WHERE id_producto = %s", (base["id_producto"],))

    tienda, usuario, precio = base["id_tienda"], base["id_usuario"], float(base["precio_venta"])
    item = [{"id": base["id_producto"], "qty": 1, "price": precio}]
    tel, ced = "3999000111", "99887766"

    # 1) Cliente nuevo: la venta crea el cliente y queda como deuda.
    r1 = svc.registrar_venta(tienda, usuario, item, "fiado", None, precio, precio, 0,
                             {"nombre": "Check Fiado", "cedula": ced, "telefono": tel})
    assert r1["numero_venta"].startswith("F"), r1
    cid = r1["id_cliente"]
    assert deuda(tienda, cid) == precio

    # 2) Live search lo encuentra por nombre, cedula y telefono, con su deuda.
    for q in ("Check Fi", ced[:4], tel[-5:]):
        hits = [c for c in svc.buscar_clientes_fiado(tienda, q) if c["id"] == cid]
        assert hits and hits[0]["cedula"] == ced and hits[0]["debt"] == precio, (q, hits)
    assert svc.buscar_clientes_fiado(tienda, "C") == []  # < 2 caracteres

    # 3) Cliente existente seleccionado: la deuda se SUMA al saldo previo.
    svc.registrar_venta(tienda, usuario, item, "fiado", None, precio, precio, 0,
                        {"id": cid, "nombre": "Check Fiado", "cedula": "", "telefono": tel})
    assert deuda(tienda, cid) == precio * 2

    # 4) Sin seleccion pero telefono/cedula ya registrados: no carga la deuda a
    #    ese cliente en silencio (409) y la deuda no cambia.
    for datos in ({"nombre": "Otro", "cedula": "", "telefono": tel}, {"nombre": "Otro", "cedula": ced, "telefono": "3000000000"}):
        try:
            svc.registrar_venta(tienda, usuario, item, "fiado", None, precio, precio, 0, datos)
            raise AssertionError(f"debio fallar: {datos}")
        except svc.SalesConflictError:
            pass
    assert deuda(tienda, cid) == precio * 2

    # 5) Fiado no suma efectivo al turno.
    cur.execute("SELECT monto_final_esperado FROM turnos_caja WHERE id_tienda=%s AND estado_turno='Abierto'", (tienda,))
    assert cur.fetchone()["monto_final_esperado"] == base["monto_final_esperado"]

    # 6) Validaciones.
    for bad in (None, {"nombre": "X", "telefono": "12"}, {"id": 999999999, "nombre": "X", "telefono": tel}):
        try:
            svc.registrar_venta(tienda, usuario, item, "fiado", None, precio, precio, 0, bad)
            raise AssertionError(f"debio fallar: {bad}")
        except (svc.SalesValidationError, svc.SalesNotFoundError):
            pass

    print("OK: flujo fiar (cliente nuevo, live search, suma de deuda, dedupe, caja, validaciones)")
finally:
    _real_rollback()
    conn.close()
