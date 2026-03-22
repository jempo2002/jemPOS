from __future__ import annotations

import calendar
import os
import re
import uuid
from datetime import date, datetime, timedelta
from io import BytesIO

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from PIL import Image
from werkzeug.security import generate_password_hash

from app.services.auth_service import (
    first_password_policy_error,
    get_profile_for_user,
    is_valid_email,
    update_profile_basic,
)
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import avatar_iniciales, fmt_money, normalize_phone
from database import get_db

core_bp = Blueprint("core_bp", __name__)

_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "static",
    "uploads",
    "perfiles",
)


def _get_dias_restantes(id_tienda: int) -> int:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT fecha_fin_suscripcion FROM tiendas WHERE id_tienda = %s LIMIT 1",
            (id_tienda,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if not row or not row["fecha_fin_suscripcion"]:
        return 999
    return (row["fecha_fin_suscripcion"] - date.today()).days


def _render_protected(template: str, **kwargs):
    dias = _get_dias_restantes(session["id_tienda"])
    if dias <= 0:
        return redirect(url_for("core_bp.servicio_suspendido"))

    nombre = session.get("nombre_completo", "")
    kwargs.setdefault("rol", session.get("rol", ""))
    kwargs.setdefault("nombre_completo", nombre)
    kwargs.setdefault("foto_perfil", session.get("foto_perfil"))
    kwargs.setdefault("avatar_iniciales", avatar_iniciales(nombre))
    kwargs["dias_restantes"] = dias
    kwargs["mostrar_alerta_suscripcion"] = (0 < dias <= 5)
    return render_template(template, **kwargs)


def _add_months(base_date: date, months: int) -> date:
    m = base_date.month - 1 + months
    year = base_date.year + m // 12
    month = m % 12 + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _get_master_tiendas() -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT t.id_tienda, t.nombre_negocio, t.nit, t.telefono,
                   t.fecha_fin_suscripcion, t.estado_suscripcion,
                   u.id_usuario AS owner_id, u.nombre_completo AS owner_name
            FROM tiendas t
            LEFT JOIN usuarios u
              ON u.id_tienda = t.id_tienda AND u.rol = 'Admin' AND u.estado_activo = 1
            ORDER BY t.nombre_negocio
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    tiendas = []
    seen = set()
    for r in rows:
        tid = r["id_tienda"]
        if tid in seen:
            continue
        seen.add(tid)
        tiendas.append(
            {
                "id_tienda": tid,
                "nombre_negocio": r["nombre_negocio"],
                "nit": r.get("nit") or "-",
                "telefono": r.get("telefono") or "-",
                "fecha_fin_suscripcion": r.get("fecha_fin_suscripcion"),
                "estado_suscripcion": r.get("estado_suscripcion") or "suspendida",
                "owner_id": r.get("owner_id"),
                "owner_name": r.get("owner_name") or "Sin dueno",
            }
        )
    return tiendas


def _get_master_proximos_vencer() -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT t.id_tienda, t.nombre_negocio, t.telefono, t.fecha_fin_suscripcion,
                   DATEDIFF(t.fecha_fin_suscripcion, CURDATE()) AS dias_restantes
            FROM tiendas t
            WHERE t.fecha_fin_suscripcion IS NOT NULL
              AND t.fecha_fin_suscripcion <= DATE_ADD(CURDATE(), INTERVAL 5 DAY)
              AND COALESCE(t.estado_suscripcion, '') <> 'eliminada'
            ORDER BY t.fecha_fin_suscripcion ASC
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    data = []
    for r in rows:
        phone = (r.get("telefono") or "").strip()
        digits = re.sub(r"\D", "", phone)
        data.append(
            {
                "id_tienda": r["id_tienda"],
                "nombre_negocio": r["nombre_negocio"],
                "telefono": phone or "-",
                "fecha_fin_suscripcion": r.get("fecha_fin_suscripcion"),
                "dias_restantes": int(r.get("dias_restantes") or 0),
                "wa_url": f"https://wa.me/57{digits}" if digits else None,
            }
        )
    return data


def _registrar_auditoria(id_tienda, id_usuario, accion, detalles) -> None:
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auditoria (id_tienda, id_usuario, accion, detalles) "
            "VALUES (%s, %s, %s, %s)",
            (id_tienda, id_usuario, accion, detalles),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _dashboard_period_bounds(raw_filter: str):
    filtro = (raw_filter or "dia").strip().lower()
    aliases = {
        "hoy": "dia",
        "ano": "anio",
        "ano": "anio",
    }
    filtro = aliases.get(filtro, filtro)
    if filtro not in ("dia", "semana", "mes", "semestre", "anio"):
        filtro = "dia"

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if filtro == "dia":
        since = today_start
        until = now
        prev_since = since - timedelta(days=1)
        prev_until = since
        badge_label = "ayer"
    elif filtro == "semana":
        since = today_start - timedelta(days=today_start.weekday())
        until = now
        span = max(until - since, timedelta(days=1))
        prev_since = since - span
        prev_until = since
        badge_label = "periodo anterior"
    elif filtro == "mes":
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        until = now
        span = max(until - since, timedelta(days=1))
        prev_since = since - span
        prev_until = since
        badge_label = "periodo anterior"
    elif filtro == "semestre":
        month = 1 if now.month <= 6 else 7
        since = now.replace(month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        until = now
        span = max(until - since, timedelta(days=1))
        prev_since = since - span
        prev_until = since
        badge_label = "periodo anterior"
    else:
        since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        until = now
        span = max(until - since, timedelta(days=1))
        prev_since = since - span
        prev_until = since
        badge_label = "periodo anterior"

    return filtro, since, until, prev_since, prev_until, badge_label


def _build_dashboard_data(id_tienda: int, raw_filter: str) -> dict:
    filtro, since, until, prev_since, prev_until, badge_label = _dashboard_period_bounds(raw_filter)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        def scalar(sql: str, params: tuple) -> float:
            cur.execute(sql, params)
            row = cur.fetchone() or {}
            return float(row.get("v") or 0)

        ventas = scalar(
            "SELECT COALESCE(SUM(v.total_final),0) AS v "
            "FROM ventas v "
            "WHERE v.id_tienda=%s AND v.estado_venta='Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s",
            (id_tienda, since, until),
        )

        ventas_prev = scalar(
            "SELECT COALESCE(SUM(v.total_final),0) AS v "
            "FROM ventas v "
            "WHERE v.id_tienda=%s AND v.estado_venta='Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s",
            (id_tienda, prev_since, prev_until),
        )

        gastos = scalar(
            "SELECT COALESCE(SUM(g.monto),0) AS v "
            "FROM gastos_caja g "
            "WHERE g.id_tienda=%s AND g.fecha_creacion >= %s AND g.fecha_creacion < %s",
            (id_tienda, since, until),
        )

        ganancia_bruta = scalar(
            "SELECT COALESCE(SUM((dv.precio_unitario_historico - p.precio_costo) * dv.cantidad),0) AS v "
            "FROM detalle_ventas dv "
            "INNER JOIN ventas v ON dv.id_venta = v.id_venta "
            "INNER JOIN productos p ON dv.id_producto = p.id_producto "
            "WHERE v.id_tienda=%s AND v.estado_venta='Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s",
            (id_tienda, since, until),
        )
        ganancia_neta = ganancia_bruta - gastos

        fiado_total = scalar(
            "SELECT COALESCE(SUM(v.total_final),0) AS v "
            "FROM ventas v "
            "WHERE v.id_tienda=%s AND v.estado_venta='Fiada/Pendiente' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s",
            (id_tienda, since, until),
        )
        abonos = scalar(
            "SELECT COALESCE(SUM(ab.monto_abonado),0) AS v "
            "FROM abonos_fiados ab "
            "INNER JOIN ventas v ON ab.id_venta = v.id_venta "
            "WHERE ab.id_tienda=%s AND ab.fecha_creacion >= %s AND ab.fecha_creacion < %s",
            (id_tienda, since, until),
        )
        cuentas_por_cobrar = max(0.0, fiado_total - abonos)

        if ventas_prev > 0:
            pct = ((ventas - ventas_prev) / ventas_prev) * 100
            ventas_badge = {
                "up": pct >= 0,
                "text": f"{'+' if pct >= 0 else ''}{pct:.0f}% vs {badge_label}",
            }
        else:
            ventas_badge = {"up": True, "text": "Sin datos anteriores"}

        cur.execute(
            "SELECT p.nombre, SUM(dv.cantidad) AS total_qty "
            "FROM detalle_ventas dv "
            "INNER JOIN ventas v ON dv.id_venta = v.id_venta "
            "INNER JOIN productos p ON dv.id_producto = p.id_producto "
            "WHERE v.id_tienda=%s AND v.estado_venta='Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s "
            "GROUP BY dv.id_producto, p.nombre "
            "ORDER BY total_qty DESC LIMIT 5",
            (id_tienda, since, until),
        )
        top_vendidos = [
            {
                "name": r["nombre"],
                "value": f"{int(float(r['total_qty'] or 0))} und",
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT p.nombre, "
            "SUM((dv.precio_unitario_historico - p.precio_costo) * dv.cantidad) AS rent "
            "FROM detalle_ventas dv "
            "INNER JOIN ventas v ON dv.id_venta = v.id_venta "
            "INNER JOIN productos p ON dv.id_producto = p.id_producto "
            "WHERE v.id_tienda=%s AND v.estado_venta='Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s "
            "GROUP BY dv.id_producto, p.nombre "
            "ORDER BY rent DESC LIMIT 5",
            (id_tienda, since, until),
        )
        top_rentables = [
            {
                "name": r["nombre"],
                "value": fmt_money(float(r["rent"] or 0)),
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT DATE(v.fecha_creacion) AS d, COALESCE(SUM(v.total_final),0) AS total "
            "FROM ventas v "
            "WHERE v.id_tienda=%s AND v.estado_venta='Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s "
            "GROUP BY DATE(v.fecha_creacion) "
            "ORDER BY DATE(v.fecha_creacion)",
            (id_tienda, since, until),
        )
        ingresos_por_dia = {r["d"]: float(r["total"] or 0) for r in cur.fetchall()}

        cur.execute(
            "SELECT DATE(g.fecha_creacion) AS d, COALESCE(SUM(g.monto),0) AS total "
            "FROM gastos_caja g "
            "WHERE g.id_tienda=%s "
            "AND g.fecha_creacion >= %s AND g.fecha_creacion < %s "
            "GROUP BY DATE(g.fecha_creacion) "
            "ORDER BY DATE(g.fecha_creacion)",
            (id_tienda, since, until),
        )
        gastos_por_dia = {r["d"]: float(r["total"] or 0) for r in cur.fetchall()}

        chart_labels = []
        chart_ingresos = []
        chart_gastos = []
        d = since.date()
        end_day = until.date()
        while d <= end_day:
            chart_labels.append(d.strftime("%d/%m"))
            chart_ingresos.append(ingresos_por_dia.get(d, 0.0))
            chart_gastos.append(gastos_por_dia.get(d, 0.0))
            d += timedelta(days=1)

        cur.execute(
            "SELECT c.id_cliente, c.nombre, c.telefono, "
            "COALESCE((SELECT SUM(GREATEST(v.total_final - COALESCE((SELECT SUM(ab.monto_abonado) FROM abonos_fiados ab WHERE ab.id_venta = v.id_venta),0),0)) FROM ventas v "
            "         WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda "
            "           AND v.estado_venta = 'Fiada/Pendiente'),0) AS deuda_total, "
            "(SELECT MIN(v.fecha_creacion) FROM ventas v "
            "  WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda "
            "    AND v.estado_venta = 'Fiada/Pendiente') AS primera_deuda "
            "FROM clientes c "
            "WHERE c.id_tienda = %s AND c.estado_activo = 1 "
            "ORDER BY deuda_total DESC "
            "LIMIT 12",
            (id_tienda,),
        )
        deudores = []
        today = datetime.now().date()
        for r in cur.fetchall():
            deuda = float(r["deuda_total"] or 0)
            if deuda <= 0:
                continue
            fecha_deuda = r.get("primera_deuda")
            dias = (today - fecha_deuda.date()).days if fecha_deuda else 0
            deudores.append(
                {
                    "name": r["nombre"],
                    "phone": r.get("telefono") or "-",
                    "debt": deuda,
                    "debt_fmt": fmt_money(deuda),
                    "days_overdue": max(0, int(dias)),
                }
            )

        cur.execute(
            "SELECT t.id_turno, u.nombre_completo, t.monto_inicial, "
            "COALESCE((SELECT SUM(v.total_final) FROM ventas v "
            "         WHERE v.id_turno=t.id_turno AND v.id_tienda=t.id_tienda "
            "           AND v.estado_venta='Pagada' AND v.metodo_pago='Efectivo'),0) AS ventas_efectivo, "
            "COALESCE((SELECT SUM(g.monto) FROM gastos_caja g "
            "         WHERE g.id_turno=t.id_turno AND g.id_tienda=t.id_tienda),0) AS gastos_turno "
            "FROM turnos_caja t "
            "INNER JOIN usuarios u ON u.id_usuario=t.id_usuario_apertura "
            "WHERE t.id_tienda=%s AND t.estado_turno='Abierto' "
            "ORDER BY t.fecha_apertura DESC LIMIT 5",
            (id_tienda,),
        )
        cajeros_abiertos = []
        for r in cur.fetchall():
            total_turno = float(r["monto_inicial"] or 0) + float(r["ventas_efectivo"] or 0) - float(r["gastos_turno"] or 0)
            cajeros_abiertos.append(
                {
                    "name": r["nombre_completo"],
                    "value": fmt_money(total_turno),
                    "id_turno": r["id_turno"],
                }
            )
    finally:
        conn.close()

    return {
        "filtro": filtro,
        "kpis": {
            "ventas": ventas,
            "ventas_fmt": fmt_money(ventas),
            "ganancia": ganancia_neta,
            "ganancia_fmt": fmt_money(ganancia_neta),
            "gastos": gastos,
            "gastos_fmt": fmt_money(gastos),
            "fiados": cuentas_por_cobrar,
            "fiados_fmt": fmt_money(cuentas_por_cobrar),
            "ventas_badge": ventas_badge,
        },
        "chart": {
            "labels": chart_labels,
            "ingresos": chart_ingresos,
            "gastos": chart_gastos,
            "values": chart_ingresos,
        },
        "top_vendidos": top_vendidos,
        "top_rentables": top_rentables,
        "cajeros_abiertos": cajeros_abiertos,
        "deudores": deudores,
    }


@core_bp.route("/servicio-suspendido")
def servicio_suspendido():
    nombre_negocio = ""
    if "id_tienda" in session:
        try:
            conn = get_db()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT nombre_negocio FROM tiendas WHERE id_tienda = %s LIMIT 1",
                    (session["id_tienda"],),
                )
                row = cur.fetchone()
                if row:
                    nombre_negocio = row["nombre_negocio"]
            finally:
                conn.close()
        except Exception:
            pass
    return render_template("auth/suspendido.html", nombre_negocio=nombre_negocio)


@core_bp.route("/dashboard")
@login_required
@roles_required("Admin", "Master")
def dashboard_page():
    filtro = request.args.get("filtro", "hoy")
    dashboard = _build_dashboard_data(session["id_tienda"], filtro)
    insumos_criticos = []

    if bool(session.get("es_restaurante")):
        conn = get_db()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT nombre, stock_actual, stock_minimo_alerta, unidad_medida "
                "FROM insumos "
                "WHERE stock_actual <= stock_minimo_alerta "
                "AND stock_minimo_alerta > 0 "
                "AND id_tienda = %s "
                "ORDER BY stock_actual ASC",
                (session["id_tienda"],),
            )
            insumos_criticos = [
                {
                    "nombre": r.get("nombre") or "Insumo",
                    "stock_actual": float(r.get("stock_actual") or 0),
                    "stock_minimo_alerta": float(r.get("stock_minimo_alerta") or 0),
                    "unidad_medida": (r.get("unidad_medida") or "Un").strip() or "Un",
                }
                for r in (cur.fetchall() or [])
            ]
        except Exception:
            insumos_criticos = []
        finally:
            conn.close()

    return _render_protected(
        "pos/dashboard.html",
        filtro_activo=dashboard["filtro"],
        dashboard=dashboard,
        insumos_criticos=insumos_criticos,
    )


@core_bp.route("/perfil")
@login_required
@roles_required("Admin")
def perfil_page():
    return _render_protected("pos/perfil.html")


@core_bp.route("/onboarding")
@login_required
@roles_required("Admin", "Master")
def onboarding_page():
    return _render_protected("pos/onboarding.html")


@core_bp.route("/panel-master")
@login_required
@roles_required("Admin", "Master")
def panel_master_page():
    return render_template(
        "auth/panel_master.html",
        rol=session.get("rol", ""),
        nombre_completo=session.get("nombre_completo", ""),
        tiendas=_get_master_tiendas(),
        proximos_vencer=_get_master_proximos_vencer(),
        hoy=date.today(),
    )


@core_bp.route("/api/onboarding", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_onboarding():
    data = request.get_json(silent=True) or {}
    category = str(data.get("category", "")).strip()
    product = str(data.get("product", "")).strip()
    cost = data.get("cost")
    sale = data.get("sale")
    stock = data.get("stock", 0)

    if not category:
        return jsonify({"ok": False, "msg": "El nombre de la categoria es requerido."}), 400
    if not product:
        return jsonify({"ok": False, "msg": "El nombre del producto es requerido."}), 400

    try:
        cost = float(cost) if cost not in (None, "") else 0.0
        sale = float(sale) if sale not in (None, "") else 0.0
        stock = int(stock) if stock not in (None, "") else 0
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Valores de precio o stock invalidos."}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO categorias (id_tienda, nombre) VALUES (%s, %s)",
            (session["id_tienda"], category),
        )
        id_cat = cur.lastrowid
        cur.execute(
            "INSERT INTO productos "
            "(id_tienda, id_categoria, nombre, precio_costo, precio_venta, stock_actual) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (session["id_tienda"], id_cat, product, cost, sale, stock),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "redirect": "/dashboard"})


@core_bp.route("/api/tiendas", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_tiendas():
    q = request.args.get("q", "").strip()
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if q:
            cur.execute(
                "SELECT id_tienda, nombre_negocio FROM tiendas "
                "WHERE nombre_negocio LIKE %s ORDER BY nombre_negocio LIMIT 20",
                (f"%{q}%",),
            )
        else:
            cur.execute(
                "SELECT id_tienda, nombre_negocio FROM tiendas "
                "ORDER BY nombre_negocio LIMIT 20"
            )
        tiendas = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"ok": True, "tiendas": tiendas})


@core_bp.route("/api/master/admins", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_master_admins_search():
    q = request.args.get("q", "").strip()
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if q:
            cur.execute(
                "SELECT id_usuario, nombre_completo, correo, cc, id_tienda "
                "FROM usuarios "
                "WHERE rol='Admin' AND estado_activo=1 "
                "AND (nombre_completo LIKE %s OR correo LIKE %s) "
                "ORDER BY nombre_completo LIMIT 20",
                (f"%{q}%", f"%{q}%"),
            )
        else:
            cur.execute(
                "SELECT id_usuario, nombre_completo, correo, cc, id_tienda "
                "FROM usuarios "
                "WHERE rol='Admin' AND estado_activo=1 "
                "ORDER BY nombre_completo LIMIT 20"
            )
        admins = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"ok": True, "admins": admins})


@core_bp.route("/api/master/tiendas", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_master_tiendas_create():
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre_negocio", "")).strip()
    nit = str(data.get("nit", "")).strip() or None
    telefono = normalize_phone(data.get("telefono"), max_len=10)
    owner_id = data.get("owner_id")
    es_restaurante = bool(data.get("es_restaurante"))

    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Debes seleccionar un Admin dueno."}), 400

    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre del negocio es requerido."}), 400
    if telefono and len(telefono) > 10:
        return jsonify({"ok": False, "msg": "El telefono debe tener maximo 10 digitos."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        cur.execute(
            "SELECT id_usuario, cc FROM usuarios WHERE id_usuario = %s AND rol='Admin' LIMIT 1",
            (owner_id,),
        )
        owner = cur.fetchone()
        if not owner:
            return jsonify({"ok": False, "msg": "El Admin seleccionado no existe."}), 404

        if not nit and owner.get("cc"):
            nit = owner.get("cc")

        cur.execute(
            "INSERT INTO tiendas (nombre_negocio, nit, telefono, estado_suscripcion, es_restaurante) "
            "VALUES (%s, %s, %s, 'activa', %s)",
            (nombre, nit, telefono, 1 if es_restaurante else 0),
        )
        id_tienda = cur.lastrowid

        cur.execute(
            "UPDATE usuarios SET id_tienda = %s WHERE id_usuario = %s",
            (id_tienda, owner_id),
        )

        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "id_tienda": id_tienda, "msg": "Tienda creada y dueno asignado."})


@core_bp.route("/api/master/tiendas/<int:id_tienda>", methods=["PUT"])
@login_required
@roles_required("Admin", "Master")
def api_master_tiendas_update(id_tienda):
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre_negocio", "")).strip()
    nit = str(data.get("nit", "")).strip() or None
    telefono = normalize_phone(data.get("telefono"), max_len=10)
    owner_id = data.get("owner_id")

    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre del negocio es requerido."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id_tienda FROM tiendas WHERE id_tienda=%s LIMIT 1", (id_tienda,))
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Tienda no encontrada."}), 404

        if owner_id not in (None, ""):
            try:
                owner_id = int(owner_id)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "msg": "Dueno invalido."}), 400

            cur.execute(
                "SELECT id_usuario, cc FROM usuarios WHERE id_usuario = %s AND rol='Admin' LIMIT 1",
                (owner_id,),
            )
            owner = cur.fetchone()
            if not owner:
                return jsonify({"ok": False, "msg": "Admin no encontrado."}), 404

            if not nit and owner.get("cc"):
                nit = owner.get("cc")

            cur.execute("UPDATE usuarios SET id_tienda = %s WHERE id_usuario = %s", (id_tienda, owner_id))

        cur.execute(
            "UPDATE tiendas SET nombre_negocio=%s, nit=%s, telefono=%s WHERE id_tienda=%s",
            (nombre, nit, telefono, id_tienda),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "msg": "Tienda actualizada correctamente."})


@core_bp.route("/api/master/tiendas/<int:id_tienda>", methods=["DELETE"])
@login_required
@roles_required("Admin", "Master")
def api_master_tiendas_delete(id_tienda):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM tiendas WHERE id_tienda = %s", (id_tienda,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"ok": False, "msg": "Tienda no encontrada."}), 404
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "eliminar_tienda",
        f"Se elimino tienda id={id_tienda}",
    )
    return jsonify({"ok": True, "msg": "Tienda eliminada."})


@core_bp.route("/api/master/suscripciones", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_master_suscripcion_renovar():
    data = request.get_json(silent=True) or {}
    id_tienda = data.get("id_tienda")
    meses = data.get("meses")
    fecha_manual_raw = str(data.get("fecha_manual", "")).strip()

    try:
        id_tienda = int(id_tienda)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Tienda invalida."}), 400

    fecha_inicio = date.today()

    if fecha_manual_raw:
        try:
            fecha_fin = date.fromisoformat(fecha_manual_raw)
        except ValueError:
            return jsonify({"ok": False, "msg": "Fecha manual invalida."}), 400
    else:
        try:
            meses = int(meses)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "msg": "Selecciona un periodo valido."}), 400
        if meses not in (1, 3, 6):
            return jsonify({"ok": False, "msg": "Periodo de suscripcion no permitido."}), 400
        fecha_fin = _add_months(fecha_inicio, meses)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tiendas SET fecha_inicio_suscripcion=%s, fecha_fin_suscripcion=%s, estado_suscripcion='activa' "
            "WHERE id_tienda=%s",
            (fecha_inicio, fecha_fin, id_tienda),
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"ok": False, "msg": "Tienda no encontrada."}), 404
    finally:
        conn.close()

    return jsonify({"ok": True, "msg": "Suscripcion actualizada correctamente."})


@core_bp.route("/api/crear_usuario", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_crear_usuario():
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    correo = str(data.get("correo", "")).strip().lower()
    password = str(data.get("password", ""))
    confirm = str(data.get("confirm_password", ""))
    cedula = str(data.get("cedula", "") or "").strip()
    telefono = str(data.get("telefono", "") or "").strip()
    rol_sesion = session["rol"]

    if rol_sesion == "Admin":
        nuevo_rol = "Cajero"
        id_tienda = session["id_tienda"]
    else:
        nuevo_rol = str(data.get("rol", "Cajero"))
        if nuevo_rol not in ("Master", "Admin", "Cajero"):
            return jsonify({"ok": False, "msg": "Rol invalido."}), 400
        nombre_negocio = None
        id_tienda = None
        if nuevo_rol == "Admin":
            nombre_negocio = str(data.get("nombre_negocio", "")).strip()
        elif nuevo_rol == "Cajero":
            try:
                id_tienda = int(data.get("id_tienda"))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "msg": "Debes seleccionar una tienda valida."}), 400
        else:
            try:
                id_tienda = int(data.get("id_tienda", session["id_tienda"]))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "msg": "ID de tienda invalido."}), 400

    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre completo es requerido."}), 400
    if not correo or not is_valid_email(correo):
        return jsonify({"ok": False, "msg": "El correo no es valido."}), 400
    if password != confirm:
        return jsonify({"ok": False, "msg": "Las contrasenas no coinciden."}), 400

    pwd_error = first_password_policy_error(password)
    if pwd_error:
        return jsonify({"ok": False, "msg": pwd_error}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_usuario FROM usuarios WHERE correo = %s LIMIT 1",
            (correo,),
        )
        if cur.fetchone():
            return jsonify({"ok": False, "msg": "Ya existe un usuario con ese correo."}), 409

        if rol_sesion == "Master" and nuevo_rol == "Admin" and nombre_negocio:
            cur.execute(
                "INSERT INTO tiendas (nombre_negocio, estado_suscripcion) VALUES (%s, 'activa')",
                (nombre_negocio,),
            )
            id_tienda = cur.lastrowid

        clave_hash = generate_password_hash(password)
        import mysql.connector.errors as _mc_err

        try:
            cur.execute(
                "INSERT INTO usuarios (id_tienda, nombre_completo, correo, clave_hash, rol, cedula, telefono) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (id_tienda, nombre, correo, clave_hash, nuevo_rol, cedula or None, telefono or None),
            )
        except _mc_err.ProgrammingError:
            cur.execute(
                "INSERT INTO usuarios (id_tienda, nombre_completo, correo, clave_hash, rol) "
                "VALUES (%s, %s, %s, %s, %s)",
                (id_tienda, nombre, correo, clave_hash, nuevo_rol),
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "msg": "Usuario creado exitosamente."})


@core_bp.route("/api/dashboard", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_dashboard():
    filtro = request.args.get("filtro") or request.args.get("period") or "hoy"
    data = _build_dashboard_data(session["id_tienda"], filtro)

    return jsonify(
        {
            "ok": True,
            "filtro": data["filtro"],
            "ventas": data["kpis"]["ventas"],
            "ganancia": data["kpis"]["ganancia"],
            "gastos": data["kpis"]["gastos"],
            "fiados": data["kpis"]["fiados"],
            "ventasBadge": data["kpis"]["ventas_badge"],
            "vendidos": data["top_vendidos"],
            "rentables": data["top_rentables"],
            "cajeros": data["cajeros_abiertos"],
            "deudores": data["deudores"],
            "chart": data["chart"],
        }
    )


@core_bp.route("/api/perfil", methods=["GET"])
@login_required
@roles_required("Admin")
def api_perfil_get():
    perfil = get_profile_for_user(int(session["id_usuario"]))
    if not perfil:
        return jsonify({"ok": False, "msg": "Usuario no encontrado."}), 404
    return jsonify({"ok": True, "perfil": perfil})


@core_bp.route("/api/perfil", methods=["PUT"])
@login_required
@roles_required("Admin")
def api_perfil_update():
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre_completo", "")).strip()
    negocio = str(data.get("nombre_negocio", "")).strip()
    telefono = normalize_phone(data.get("telefono"), max_len=10)

    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre no puede estar vacio."}), 400
    if telefono and len(telefono) < 7:
        return jsonify({"ok": False, "msg": "Telefono invalido."}), 400

    update_profile_basic(
        id_usuario=int(session["id_usuario"]),
        id_tienda=int(session["id_tienda"]),
        nombre=nombre,
        negocio=negocio,
    )
    session["nombre_completo"] = nombre
    return jsonify({"ok": True, "msg": "Perfil actualizado."})


@core_bp.route("/api/perfil/foto", methods=["POST"])
@login_required
@roles_required("Admin")
def api_perfil_foto():
    if "foto" not in request.files:
        return jsonify({"ok": False, "msg": "No se recibio archivo."}), 400
    f = request.files["foto"]
    if not f.filename:
        return jsonify({"ok": False, "msg": "Nombre de archivo invalido."}), 400

    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in {"jpg", "jpeg", "png"}:
        return jsonify({"ok": False, "msg": "Solo se permiten JPG o PNG."}), 400

    content = f.read()
    if len(content) > 5 * 1024 * 1024:
        return jsonify({"ok": False, "msg": "El archivo supera los 5 MB."}), 400

    try:
        img = Image.open(BytesIO(content))
        img = img.convert("RGB")
        img.thumbnail((500, 500))
    except Exception:
        return jsonify({"ok": False, "msg": "Imagen invalida o corrupta."}), 400

    id_usuario = session["id_usuario"]

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT foto_perfil FROM usuarios WHERE id_usuario = %s LIMIT 1",
            (id_usuario,),
        )
        old_row = cur.fetchone()
    finally:
        conn.close()

    if old_row and old_row.get("foto_perfil"):
        old_path = os.path.join(_UPLOAD_DIR, old_row["foto_perfil"])
        if os.path.exists(old_path):
            os.remove(old_path)

    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.jpg"
    save_path = os.path.join(_UPLOAD_DIR, filename)
    img.save(save_path, format="JPEG", quality=85, optimize=True)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE usuarios SET foto_perfil = %s WHERE id_usuario = %s",
            (filename, id_usuario),
        )
        conn.commit()
    finally:
        conn.close()

    session["foto_perfil"] = filename
    return jsonify({"ok": True, "url": f"/static/uploads/perfiles/{filename}"})


@core_bp.route("/api/perfil/foto", methods=["DELETE"])
@login_required
@roles_required("Admin")
def api_perfil_foto_delete():
    id_usuario = session["id_usuario"]
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT foto_perfil FROM usuarios WHERE id_usuario = %s LIMIT 1",
            (id_usuario,),
        )
        row = cur.fetchone()
        if row and row.get("foto_perfil"):
            old_path = os.path.join(_UPLOAD_DIR, row["foto_perfil"])
            if os.path.exists(old_path):
                os.remove(old_path)

        cur2 = conn.cursor()
        cur2.execute(
            "UPDATE usuarios SET foto_perfil = NULL WHERE id_usuario = %s",
            (id_usuario,),
        )
        conn.commit()
    finally:
        conn.close()

    session["foto_perfil"] = None
    return jsonify({"ok": True})
