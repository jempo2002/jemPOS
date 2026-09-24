"""Chequeo del arqueo de caja: gastos con fuente "Base" y cuadre del cierre.

Todo corre en UNA transaccion que se revierte al final: no deja datos.
Requiere la migracion migrations/2026-09-23_gastos_fuente_base.sql y una
tienda con turno abierto y un producto activo.

Comprueba lo que la interfaz de Mi Turno promete al cajero:

  1) Un gasto con fuente "Base" baja el efectivo esperado peso a peso.
  2) Un gasto desde "Caja Fuerte" NO lo toca: ese dinero no esta en el cajon.
  3) Una venta en efectivo lo sube.
  4) El desglose que se pinta en pantalla cuadra con el total esperado.
  5) Cerrar con el efectivo exacto marca cuadrado; con otro, la diferencia
     tiene el signo correcto (positivo sobra, negativo falta).

    python scripts/check_turno_arqueo.py
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


def estado(tienda):
    t = svc.get_turno_estado(tienda)
    assert t, "el turno deberia seguir abierto"
    return t


def desfase(t):
    """Distancia entre el total esperado y la suma de sus componentes.

    Tiene que ser 0 siempre: la cifra grande de la pantalla se calcula con
    esos mismos sumandos, asi que si no cuadra es que el cajero esta viendo un
    desglose que no da el total que tiene al lado.

    El caso que lo rompia: un fiado se guarda con metodo_pago 'Efectivo' y al
    terminar de pagarse pasa a estado 'Pagada', asi que contaba como venta en
    efectivo ademas de contar sus abonos. El mismo dinero, dos veces.
    """
    componentes = (
        t["base"] + t["ventas_efectivo"] + t["abonos_efectivo"] - t["gastos_de_caja"]
    )
    return round(t["total_esperado"] - componentes, 2)


try:
    assert "Base" in svc.FUENTES_DINERO, svc.FUENTES_DINERO
    assert set(svc.FUENTES_QUE_SALEN_DE_CAJA) == {"Base", "Caja Menor"}, (
        svc.FUENTES_QUE_SALEN_DE_CAJA
    )

    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT t.id_tienda, t.id_usuario_apertura AS id_usuario, "
        "       p.id_producto, p.precio_venta "
        "FROM turnos_caja t JOIN productos p ON p.id_tienda = t.id_tienda "
        "WHERE t.estado_turno = 'Abierto' AND p.estado_activo = 1 "
        "AND p.es_preparado = 0 LIMIT 1"
    )
    fila = cur.fetchone()
    if not fila:
        sys.exit("SKIP: no hay tienda con turno abierto y producto activo.")

    tienda = fila["id_tienda"]
    usuario = fila["id_usuario"]
    precio = float(fila["precio_venta"])
    cur.execute(
        "UPDATE productos SET stock_actual = stock_actual + 10 WHERE id_producto = %s",
        (fila["id_producto"],),
    )

    t0 = estado(tienda)
    assert desfase(t0) == 0, f"el desglose no suma el total esperado: {t0}"
    desfase_inicial = 0
    print(f"   turno {t0['id_turno']} | base {t0['base']:.0f} | esperado {t0['total_esperado']:.0f}")

    # ── 1) Gasto pagado con la base ─────────────────────────
    svc.crear_gasto(tienda, usuario, "Chequeo arqueo", "gasto base", "Efectivo", "Base", 15000)
    t1 = estado(tienda)
    assert t1["total_esperado"] == t0["total_esperado"] - 15000, (
        t0["total_esperado"], t1["total_esperado"]
    )
    assert t1["gastos_de_base"] == t0["gastos_de_base"] + 15000
    assert t1["gastos_de_caja"] == t0["gastos_de_caja"] + 15000
    assert t1["gastos_total"] == t0["gastos_total"] + 15000
    assert t1["base"] == t0["base"], "la base de apertura no se reescribe, solo se descuenta al calcular"
    assert desfase(t1) == 0, (desfase(t1), t1)
    print("OK 1: un gasto con fuente 'Base' baja el esperado en su monto exacto")

    # ── 2) Gasto desde la caja fuerte: no toca el cajon ─────
    svc.crear_gasto(tienda, usuario, "Chequeo arqueo", "gasto fuerte", "Efectivo", "Caja Fuerte", 7000)
    t2 = estado(tienda)
    assert t2["total_esperado"] == t1["total_esperado"], "Caja Fuerte no debe mover el efectivo esperado"
    assert t2["gastos_de_caja"] == t1["gastos_de_caja"]
    assert t2["gastos_total"] == t1["gastos_total"] + 7000, "pero si cuenta como gasto del dia"
    assert desfase(t2) == 0
    print("OK 2: un gasto desde 'Caja Fuerte' cuenta como gasto pero no descuadra la caja")

    # ── 3) Venta en efectivo ────────────────────────────────
    item = [{"id": fila["id_producto"], "qty": 1, "price": precio}]
    svc.registrar_venta(tienda, usuario, item, "efectivo", None, precio, precio, 0)
    t3 = estado(tienda)
    assert t3["total_esperado"] == round(t2["total_esperado"] + precio, 2), (
        t2["total_esperado"], t3["total_esperado"], precio
    )
    assert t3["ventas_efectivo"] == round(t2["ventas_efectivo"] + precio, 2)
    assert t3["ventas_total"] == round(t2["ventas_total"] + precio, 2)
    assert desfase(t3) == 0
    print("OK 3: una venta en efectivo sube el esperado y el desglose sigue cuadrando")

    # ── 4) Un fiado pagado no entra dos veces ───────────────
    antes = estado(tienda)
    venta_fiada = svc.registrar_venta(
        tienda, usuario, item, "fiado", None, precio, precio, 0,
        {"nombre": "Check Arqueo", "cedula": "99001122", "telefono": "3999000222"},
    )
    con_fiado = estado(tienda)
    assert con_fiado["total_esperado"] == antes["total_esperado"], (
        "fiar no entrega dinero: no puede subir el efectivo esperado"
    )

    # abonar_fiado trabaja por cliente, no por venta: salda la deuda mas
    # antigua primero. El cliente se acaba de crear con esta unica venta.
    svc.abonar_fiado(tienda, usuario, venta_fiada["id_cliente"], precio, "efectivo")
    pagado = estado(tienda)
    assert pagado["total_esperado"] == round(antes["total_esperado"] + precio, 2), (
        "al cobrar el fiado entra su importe UNA vez",
        antes["total_esperado"], pagado["total_esperado"], precio,
    )
    assert desfase(pagado) == 0
    print("OK 4: un fiado que se termina de pagar suma una sola vez al arqueo")

    # ── 5) Cierre exacto: caja cuadrada ─────────────────────
    esperado = pagado["total_esperado"]
    arqueo = svc.cerrar_turno(tienda, usuario, esperado)
    assert arqueo["cuadrado"] is True, arqueo
    assert arqueo["diferencia"] == 0, arqueo
    assert arqueo["total_esperado"] == esperado
    assert arqueo["monto_reportado"] == esperado
    assert svc.get_turno_estado(tienda) is None, "el turno deberia quedar cerrado"
    print("OK 5: cerrar con el efectivo exacto marca la caja como cuadrada")

    # ── 6) Cierre con sobrante y con faltante ───────────────
    svc.abrir_turno(tienda, usuario, 50000)
    nuevo = estado(tienda)
    assert nuevo["base"] == 50000
    assert nuevo["total_esperado"] == 50000, "un turno recien abierto espera exactamente su base"
    assert nuevo["ventas_total"] == 0 and nuevo["gastos_total"] == 0, "el turno nuevo arranca limpio"
    assert desfase(nuevo) == 0, "un turno nuevo no puede nacer desfasado"

    sobra = svc.cerrar_turno(tienda, usuario, 53000)
    assert sobra["cuadrado"] is False and sobra["diferencia"] == 3000, sobra

    svc.abrir_turno(tienda, usuario, 50000)
    falta = svc.cerrar_turno(tienda, usuario, 48500)
    assert falta["cuadrado"] is False and falta["diferencia"] == -1500, falta
    print("OK 6: la diferencia sale positiva si sobra dinero y negativa si falta")

    print(
        "\nTODO OK: fuente 'Base' descontada del efectivo esperado, "
        "desglose que suma exactamente el total mostrado."
    )
finally:
    _real_rollback()
    conn.close()
