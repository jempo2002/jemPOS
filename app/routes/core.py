from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from mysql.connector import Error as MySQLError, IntegrityError
from werkzeug.security import generate_password_hash

from app.services.auth_service import (
    first_password_policy_error,
    get_profile_for_user,
    is_valid_email,
    liberar_datos_inactivos,
    LIBERAR_USUARIO_SQL,
    update_profile_basic,
)
from app.routes.seo import MENSUALIDAD
from app.services.sales_service import (
    _meta_paginacion,
    get_money_flow_summary,
    get_rendimiento_personal,
    get_stock_alerts,
    get_top_vendidos,
    paginacion,
)
from app.services.cartera_service import get_resumen_cartera, get_top_deudores
from app.utils.decorators import _is_api_request, login_required, roles_required
from app.utils.helpers import avatar_iniciales, fmt_money, only_digits
from app.utils.validation import parse_int, sanitize_optional_text, sanitize_text
from database import get_db

core_bp = Blueprint("core_bp", __name__)


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


# Tamano de pagina de cada listado del Panel Master.
POR_PAGINA_TIENDAS = 10
POR_PAGINA_VENCER = 5
POR_PAGINA_MOVIMIENTOS = 8


def _get_master_tiendas(page) -> tuple[list, dict]:
    page, limit = paginacion(page, POR_PAGINA_TIENDAS, defecto=POR_PAGINA_TIENDAS)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) AS n FROM tiendas WHERE estado <> 'Eliminado'")
        meta = _meta_paginacion(cur.fetchone()["n"], page, limit)
        # Dueno = el Admin activo mas antiguo: un JOIN directo repetia la tienda
        # por cada Admin y descuadraba el LIMIT.
        cur.execute(
            """
            SELECT t.id_tienda, t.nombre_negocio, t.nit, t.telefono,
                   t.fecha_fin_suscripcion, t.estado_suscripcion,
                   u.id_usuario AS owner_id, u.nombre_completo AS owner_name
            FROM tiendas t
            LEFT JOIN usuarios u ON u.id_usuario = (
                SELECT MIN(a.id_usuario) FROM usuarios a
                WHERE a.id_tienda = t.id_tienda AND a.rol = 'Admin' AND a.estado_activo = 1
            )
            WHERE t.estado <> 'Eliminado'
            ORDER BY t.nombre_negocio, t.id_tienda
            LIMIT %s OFFSET %s
            """,
            (limit, meta["offset"]),
        )
        tiendas = cur.fetchall()
    finally:
        conn.close()
    # Valores crudos (None si faltan): la plantilla pone los guiones. Antes el
    # "-" viajaba al modal de edicion y se guardaba como NIT.
    return tiendas, meta


def _get_master_proximos_vencer(page) -> tuple[list, dict]:
    page, limit = paginacion(page, POR_PAGINA_VENCER, defecto=POR_PAGINA_VENCER)
    filtro = (
        "FROM tiendas t "
        "WHERE t.fecha_fin_suscripcion IS NOT NULL "
        "AND t.fecha_fin_suscripcion <= DATE_ADD(CURDATE(), INTERVAL 5 DAY) "
        "AND t.estado <> 'Eliminado' "
    )
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) AS n " + filtro)
        meta = _meta_paginacion(cur.fetchone()["n"], page, limit)
        cur.execute(
            "SELECT t.id_tienda, t.nombre_negocio, t.telefono, t.fecha_fin_suscripcion, "
            "DATEDIFF(t.fecha_fin_suscripcion, CURDATE()) AS dias_restantes "
            + filtro +
            "ORDER BY t.fecha_fin_suscripcion ASC, t.id_tienda LIMIT %s OFFSET %s",
            (limit, meta["offset"]),
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
    return data, meta


def _get_master_resumen() -> dict:
    """Tarjetas del Panel Master: tiendas, usuarios e ingresos del SaaS."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        # "Al dia" = suscripcion con fecha de fin futura. Las tiendas sin fecha
        # (registro libre, la tienda del propio Master) no pagan: no suman.
        cur.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(fecha_fin_suscripcion > CURDATE()), 0) AS al_dia "
            "FROM tiendas WHERE estado <> 'Eliminado'"
        )
        tiendas = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n FROM usuarios WHERE estado_activo = 1")
        usuarios = cur.fetchone()["n"]
        inicio_mes = date.today().replace(day=1)
        cur.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN tipo = 'Ingreso' THEN monto END), 0) AS ingresos, "
            "COALESCE(SUM(CASE WHEN tipo = 'Gasto' THEN monto END), 0) AS gastos "
            "FROM master_movimientos WHERE fecha >= %s AND fecha < %s",
            (inicio_mes, _add_months(inicio_mes, 1)),
        )
        mes = cur.fetchone()
    finally:
        conn.close()

    al_dia = int(tiendas["al_dia"])
    ingresos, gastos = float(mes["ingresos"]), float(mes["gastos"])
    return {
        "tiendas": int(tiendas["total"]),
        "tiendas_al_dia": al_dia,
        "usuarios": int(usuarios),
        "ingresos_estimados": fmt_money(al_dia * MENSUALIDAD),
        "mensualidad": fmt_money(MENSUALIDAD),
        "ingresos_mes": fmt_money(ingresos),
        "gastos_mes": fmt_money(gastos),
        "balance_mes": fmt_money(abs(ingresos - gastos)),
        "balance_negativo": ingresos < gastos,
    }


def _get_master_movimientos(page) -> tuple[list, dict]:
    page, limit = paginacion(page, POR_PAGINA_MOVIMIENTOS, defecto=POR_PAGINA_MOVIMIENTOS)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) AS n FROM master_movimientos")
        meta = _meta_paginacion(cur.fetchone()["n"], page, limit)
        cur.execute(
            "SELECT id_movimiento, tipo, concepto, monto, fecha FROM master_movimientos "
            "ORDER BY fecha DESC, id_movimiento DESC LIMIT %s OFFSET %s",
            (limit, meta["offset"]),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    for r in rows:
        r["monto_fmt"] = fmt_money(float(r["monto"]))
    return rows, meta


def _tienda_opcional(cur, raw) -> int | None:
    """id de una tienda viva, o None si no se eligio ninguna."""
    if raw in (None, ""):
        return None
    id_tienda = parse_int(raw, "Tienda", min_value=1)
    cur.execute(
        "SELECT 1 FROM tiendas WHERE id_tienda = %s AND estado <> 'Eliminado' LIMIT 1",
        (id_tienda,),
    )
    if not cur.fetchone():
        raise ValueError("La tienda seleccionada no existe.")
    return id_tienda


_CC_DUPLICADA = "Ya existe un usuario con esa cedula."



def _parse_cc(raw) -> str:
    cc = only_digits(raw)
    if not cc:
        raise ValueError("La cedula es requerida.")
    if not 5 <= len(cc) <= 15:
        raise ValueError("La cedula debe tener entre 5 y 15 digitos.")
    return cc


def _cc_en_uso(cur, cc: str, excluir_id: int | None = None) -> bool:
    # Incluye inactivos: uq_usuarios_cc aplica a toda la tabla.
    cur.execute(
        "SELECT 1 FROM usuarios WHERE cc = %s AND id_usuario <> %s LIMIT 1",
        (cc, excluir_id or 0),
    )
    return cur.fetchone() is not None


def _es_ultimo_admin(cur, usuario: dict) -> bool:
    if usuario["rol"] != "Admin" or not usuario["id_tienda"]:
        return False
    cur.execute(
        "SELECT COUNT(*) AS n FROM usuarios "
        "WHERE id_tienda = %s AND rol = 'Admin' AND estado_activo = 1 AND id_usuario <> %s",
        (usuario["id_tienda"], usuario["id_usuario"]),
    )
    return cur.fetchone()["n"] == 0


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


def _dashboard_period_bounds(raw_filter: str, fecha: str | None = None):
    filtro = (raw_filter or "hoy").strip().lower()
    aliases = {
        "hoy": "dia",
        "day": "dia",
        "ano": "anio",
        "anio": "anio",
        "año": "anio",
        "year": "anio",
        "3_meses": "tres_meses",
        "6_meses": "seis_meses",
        "semestre": "seis_meses",
    }
    filtro = aliases.get(filtro, filtro)
    if filtro not in ("dia", "ayer", "semana", "mes", "tres_meses", "seis_meses", "anio", "todas"):
        filtro = "dia"

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Fecha concreta (input date): ignora el rango y muestra ese dia
    if fecha:
        try:
            day = datetime.strptime(fecha, "%Y-%m-%d")
        except ValueError:
            day = None
        if day is not None:
            since = day.replace(hour=0, minute=0, second=0, microsecond=0)
            until = since + timedelta(days=1)
            return "fecha", since, until, since - timedelta(days=1), since, "dia anterior"

    if filtro == "dia":
        since = today_start
        until = now
        prev_since = since - timedelta(days=1)
        prev_until = since
        badge_label = "ayer"
    elif filtro == "ayer":
        since = today_start - timedelta(days=1)
        until = today_start
        prev_since = since - timedelta(days=1)
        prev_until = since
        badge_label = "dia anterior"
    elif filtro == "tres_meses":
        since = today_start - timedelta(days=90)
        until = now
        prev_since = since - timedelta(days=90)
        prev_until = since
        badge_label = "periodo anterior"
    elif filtro == "seis_meses":
        since = today_start - timedelta(days=180)
        until = now
        prev_since = since - timedelta(days=180)
        prev_until = since
        badge_label = "periodo anterior"
    elif filtro == "todas":
        # ponytail: 'todas' acotado a 2 años de barras diarias; pasar a rollup mensual si las tiendas envejecen
        since = today_start - timedelta(days=730)
        until = now
        prev_since = since
        prev_until = since
        badge_label = "historico"
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
    else:
        since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        until = now
        span = max(until - since, timedelta(days=1))
        prev_since = since - span
        prev_until = since
        badge_label = "periodo anterior"

    return filtro, since, until, prev_since, prev_until, badge_label


def _build_dashboard_data(id_tienda: int, raw_filter: str, fecha: str | None = None) -> dict:
    """Todo el Panel de Control en una respuesta.

    Finanzas: del periodo elegido. Cartera y personal: siempre al momento
    (lo que se debe hoy y como va cada turno no dependen de la capsula).
    """
    filtro, since, until, prev_since, prev_until, badge_label = _dashboard_period_bounds(raw_filter, fecha)

    flujo = get_money_flow_summary(id_tienda, since, until)
    ventas = float(flujo["entradas"])
    gastos = float(flujo["salidas"])

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT COALESCE(SUM(v.total_final), 0) AS v FROM ventas v "
            "WHERE v.id_tienda = %s AND v.estado_venta = 'Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s",
            (id_tienda, prev_since, prev_until),
        )
        ventas_prev = float((cur.fetchone() or {}).get("v") or 0)

        cur.execute(
            "SELECT COUNT(*) AS n FROM ventas v "
            "WHERE v.id_tienda = %s AND v.estado_venta = 'Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s",
            (id_tienda, since, until),
        )
        num_ventas = int((cur.fetchone() or {}).get("n") or 0)

        # Costo por unidad base: una linea vendida por empaque (rollo x100)
        # consume empaque_cantidad unidades de costo por cada empaque.
        # ponytail: se reconoce el empaque por su nombre en unidad_venta; si un
        # dia se renombra el empaque, las ventas viejas se costean por unidad.
        cur.execute(
            "SELECT COALESCE(SUM(dv.subtotal_linea - p.precio_costo * dv.cantidad * "
            "  CASE WHEN dv.unidad_venta = p.empaque_nombre AND p.empaque_cantidad > 0 "
            "       THEN p.empaque_cantidad ELSE 1 END), 0) AS v "
            "FROM detalle_ventas dv "
            "INNER JOIN ventas v ON dv.id_venta = v.id_venta "
            "INNER JOIN productos p ON dv.id_producto = p.id_producto "
            "WHERE v.id_tienda = %s AND v.estado_venta = 'Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s",
            (id_tienda, since, until),
        )
        utilidad_bruta = float((cur.fetchone() or {}).get("v") or 0)
    finally:
        conn.close()

    if ventas_prev > 0:
        pct = (ventas - ventas_prev) / ventas_prev * 100
        tendencia = {"up": pct >= 0, "text": f"{'+' if pct >= 0 else ''}{pct:.0f}% vs {badge_label}"}
    elif filtro == "todas":
        tendencia = None
    else:
        tendencia = {"up": True, "text": "Sin comparativo"}

    cartera = get_resumen_cartera(id_tienda)
    utilidad_neta = utilidad_bruta - gastos

    # Punto de equilibrio: ventas con las que la utilidad bruta iguala a los
    # gastos del periodo = gastos / margen bruto. Sin margen positivo no hay
    # volumen de ventas que cubra los gastos: se devuelve None.
    # ponytail: todos los gastos del periodo se tratan como fijos; separar
    # fijos/variables cuando gastos_caja tenga esa clasificacion.
    margen_ratio = utilidad_bruta / ventas if ventas > 0 else 0.0
    if gastos <= 0:
        punto_equilibrio = 0.0
    elif margen_ratio > 0:
        punto_equilibrio = round(gastos / margen_ratio, 2)
    else:
        punto_equilibrio = None
    return {
        "filtro": filtro,
        "finanzas": {
            "ventas": ventas,
            "tendencia": tendencia,
            "num_ventas": num_ventas,
            "ticket_promedio": round(ventas / num_ventas, 2) if num_ventas else 0.0,
            "utilidad_bruta": round(utilidad_bruta, 2),
            "margen": round(utilidad_bruta / ventas * 100, 1) if ventas > 0 else None,
            "gastos": gastos,
            "utilidad_neta": round(utilidad_neta, 2),
            "punto_equilibrio": punto_equilibrio,
            **cartera,
        },
        "deudas_antiguas": get_top_deudores(id_tienda, "antiguas"),
        "deudas_mayores": get_top_deudores(id_tienda, "monto"),
        "top_vendidos": [
            {"name": r["name"], "total": r["total"]} for r in get_top_vendidos(id_tienda, since, until, limit=5)
        ],
        "stock_alertas": get_stock_alerts(id_tienda, limit=5),
        "personal": get_rendimiento_personal(id_tienda),
        "actualizado": datetime.now().strftime("%I:%M %p"),
    }


@core_bp.route("/servicio-suspendido")
@login_required
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
    # Los datos los pide dashboard.js a /api/dashboard (y los refresca solo).
    return _render_protected("pos/dashboard.html")


@core_bp.route("/perfil")
@login_required
@roles_required("Admin")
def perfil_page():
    return _render_protected("pos/perfil.html")


@core_bp.route("/panel-master")
@login_required
@roles_required("Master")
def panel_master_page():
    # Cada listado pagina con su propio parametro (?pt, ?pv, ?pm): moverse en
    # uno no reinicia los otros.
    tiendas, meta_tiendas = _get_master_tiendas(request.args.get("pt"))
    proximos, meta_proximos = _get_master_proximos_vencer(request.args.get("pv"))
    movimientos, meta_movimientos = _get_master_movimientos(request.args.get("pm"))
    return render_template(
        "auth/panel_master.html",
        rol=session.get("rol", ""),
        nombre_completo=session.get("nombre_completo", ""),
        resumen=_get_master_resumen(),
        tiendas=tiendas,
        meta_tiendas=meta_tiendas,
        proximos_vencer=proximos,
        meta_proximos=meta_proximos,
        movimientos=movimientos,
        meta_movimientos=meta_movimientos,
        paginas={"pt": meta_tiendas["page"], "pv": meta_proximos["page"], "pm": meta_movimientos["page"]},
        hoy=date.today(),
    )


@core_bp.route("/api/tiendas", methods=["GET"])
@login_required
@roles_required("Master")
def api_tiendas():
    q = request.args.get("q", "").strip()
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if q:
            cur.execute(
                "SELECT id_tienda, nombre_negocio FROM tiendas "
                "WHERE estado <> 'Eliminado' AND nombre_negocio LIKE %s "
                "ORDER BY nombre_negocio LIMIT 20",
                (f"%{q}%",),
            )
        else:
            cur.execute(
                "SELECT id_tienda, nombre_negocio FROM tiendas "
                "WHERE estado <> 'Eliminado' ORDER BY nombre_negocio LIMIT 20"
            )
        tiendas = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"ok": True, "tiendas": tiendas})


@core_bp.route("/api/master/admins", methods=["GET"])
@login_required
@roles_required("Master")
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
@roles_required("Master")
def api_master_tiendas_create():
    data = request.get_json(silent=True) or {}
    try:
        nombre = sanitize_text(data.get("nombre_negocio"), "El nombre del negocio", max_len=150)
        nit = sanitize_optional_text(data.get("nit"), "NIT", max_len=30)
        telefono_raw = data.get("telefono")
        telefono_digits = only_digits(telefono_raw)
        if telefono_raw and not telefono_digits:
            raise ValueError("El telefono es invalido.")
        if telefono_digits and len(telefono_digits) > 25:
            raise ValueError("El telefono no puede superar 25 digitos.")
        telefono = telefono_digits or None
        owner_id = parse_int(data.get("owner_id"), "Admin dueno", min_value=1)
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400

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
            "INSERT INTO tiendas (nombre_negocio, nit, telefono, estado_suscripcion) "
            "VALUES (%s, %s, %s, 'activa')",
            (nombre, nit, telefono),
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
@roles_required("Master")
def api_master_tiendas_update(id_tienda):
    data = request.get_json(silent=True) or {}
    try:
        nombre = sanitize_text(data.get("nombre_negocio"), "El nombre del negocio", max_len=150)
        nit = sanitize_optional_text(data.get("nit"), "NIT", max_len=30)
        telefono_raw = data.get("telefono")
        telefono_digits = only_digits(telefono_raw)
        if telefono_raw and not telefono_digits:
            raise ValueError("El telefono es invalido.")
        if telefono_digits and len(telefono_digits) > 25:
            raise ValueError("El telefono no puede superar 25 digitos.")
        telefono = telefono_digits or None
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_tienda FROM tiendas WHERE id_tienda=%s AND estado <> 'Eliminado' LIMIT 1",
            (id_tienda,),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Tienda no encontrada."}), 404

        owner_id = data.get("owner_id")
        if owner_id not in (None, ""):
            try:
                owner_id = parse_int(owner_id, "Dueno", min_value=1)
            except ValueError as exc:
                return jsonify({"ok": False, "msg": str(exc)}), 400

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
@roles_required("Master")
def api_master_tiendas_delete(id_tienda):
    if id_tienda == session.get("id_tienda"):
        return jsonify({"ok": False, "msg": "No puedes eliminar la tienda de tu propia cuenta."}), 400

    # Soft delete: un DELETE real choca con FKs RESTRICT (ventas, turnos, detalle)
    # y borraria el historial contable. Ver migrations/2026-09-23_tiendas_estado_eliminado.sql
    conn = get_db()
    try:
        cur = conn.cursor()
        # fecha_fin = hoy: _render_protected ve 0 dias y saca a las sesiones abiertas.
        cur.execute(
            "UPDATE tiendas SET estado='Eliminado', estado_suscripcion='suspendida', "
            "fecha_fin_suscripcion=CURDATE(), nit=CONCAT('deleted_', UNIX_TIMESTAMP(), '_', nit) "
            "WHERE id_tienda=%s AND estado <> 'Eliminado'",
            (id_tienda,),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return jsonify({"ok": False, "msg": "Tienda no encontrada."}), 404
        cur.execute(
            # estado_activo = 1: no volver a prefijar a los ya eliminados.
            "UPDATE usuarios SET " + LIBERAR_USUARIO_SQL +
            " WHERE id_tienda=%s AND rol <> 'Master' AND estado_activo = 1",
            (id_tienda,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo eliminar la tienda."}), 500
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
@roles_required("Master")
def api_master_suscripcion_renovar():
    data = request.get_json(silent=True) or {}
    id_tienda = data.get("id_tienda")
    meses = data.get("meses")
    fecha_manual_raw = str(data.get("fecha_manual", "")).strip()

    try:
        id_tienda = int(id_tienda)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Tienda invalida."}), 400
    if fecha_manual_raw and len(fecha_manual_raw) > 10:
        return jsonify({"ok": False, "msg": "Fecha manual invalida."}), 400

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
            "WHERE id_tienda=%s AND estado <> 'Eliminado'",
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
    try:
        nombre = sanitize_text(data.get("nombre"), "El nombre completo", max_len=150)
        cc = _parse_cc(data.get("cc"))
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    correo = str(data.get("correo", "")).strip().lower()
    password = str(data.get("password", ""))
    confirm = str(data.get("confirm_password", ""))
    rol_sesion = session["rol"]

    if rol_sesion == "Admin":
        nuevo_rol = "Cajero"
        id_tienda = session["id_tienda"]
        tienda_raw = None
    else:
        nuevo_rol = str(data.get("rol", "Cajero"))
        if nuevo_rol not in ("Master", "Admin", "Cajero"):
            return jsonify({"ok": False, "msg": "Rol invalido."}), 400
        # Tienda opcional; un Master nunca se ata a una tienda.
        id_tienda = None
        tienda_raw = None if nuevo_rol == "Master" else data.get("id_tienda")

    if not correo or len(correo) > 150 or not is_valid_email(correo):
        return jsonify({"ok": False, "msg": "El correo no es valido."}), 400
    if len(password) > 128:
        return jsonify({"ok": False, "msg": "La contrasena supera el maximo permitido."}), 400
    if password != confirm:
        return jsonify({"ok": False, "msg": "Las contrasenas no coinciden."}), 400

    pwd_error = first_password_policy_error(password)
    if pwd_error:
        return jsonify({"ok": False, "msg": pwd_error}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        liberar_datos_inactivos(cur, correo, cc)
        cur.execute(
            "SELECT id_usuario FROM usuarios WHERE correo = %s LIMIT 1",
            (correo,),
        )
        if cur.fetchone():
            return jsonify({"ok": False, "msg": "Ya existe un usuario con ese correo."}), 409
        if _cc_en_uso(cur, cc):
            return jsonify({"ok": False, "msg": _CC_DUPLICADA}), 409
        if tienda_raw not in (None, ""):
            id_tienda = _tienda_opcional(cur, tienda_raw)

        clave_hash = generate_password_hash(password)
        cur.execute(
            "INSERT INTO usuarios (id_tienda, nombre_completo, correo, clave_hash, rol, cc) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (id_tienda, nombre, correo, clave_hash, nuevo_rol, cc),
        )
        conn.commit()
    except IntegrityError:
        # Carrera entre el SELECT y el INSERT: uq_usuarios_correo / uq_usuarios_cc.
        conn.rollback()
        return jsonify({"ok": False, "msg": "Ya existe un usuario con ese correo o cedula."}), 409
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    finally:
        conn.close()

    return jsonify({"ok": True, "msg": "Usuario creado exitosamente."})


@core_bp.route("/api/master/usuarios", methods=["GET"])
@login_required
@roles_required("Master")
def api_master_usuarios_list():
    page, limit = paginacion(request.args.get("page"), request.args.get("limit"), defecto=10, maximo=50)
    q = str(request.args.get("q", "")).strip()[:100]
    desde = (
        "FROM usuarios u LEFT JOIN tiendas t ON t.id_tienda = u.id_tienda "
        "WHERE u.estado_activo = 1 "
    )
    params: list = []
    if q:
        # La CC ya no se muestra en la tabla, pero sigue sirviendo para buscar.
        desde += "AND (u.nombre_completo LIKE %s OR u.correo LIKE %s OR u.cc LIKE %s OR t.nombre_negocio LIKE %s) "
        params = [f"%{q}%"] * 4
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) AS n " + desde, params)
        meta = _meta_paginacion(cur.fetchone()["n"], page, limit)
        cur.execute(
            "SELECT u.id_usuario, u.nombre_completo, u.correo, u.rol, u.cc, u.id_tienda, "
            "t.nombre_negocio, (u.id_usuario = %s) AS es_actual "
            + desde +
            "ORDER BY t.nombre_negocio, FIELD(u.rol, 'Master', 'Admin', 'Cajero'), u.nombre_completo, u.id_usuario "
            "LIMIT %s OFFSET %s",
            [session["id_usuario"], *params, limit, meta["offset"]],
        )
        usuarios = cur.fetchall()
    finally:
        conn.close()
    for u in usuarios:
        u["es_actual"] = bool(u["es_actual"])
    return jsonify({"ok": True, "usuarios": usuarios, "meta": meta})


def _get_usuario_activo(cur, id_usuario: int) -> dict | None:
    cur.execute(
        "SELECT id_usuario, id_tienda, rol, cc, correo FROM usuarios "
        "WHERE id_usuario = %s AND estado_activo = 1 LIMIT 1",
        (id_usuario,),
    )
    return cur.fetchone()


@core_bp.route("/api/master/usuarios/<int:id_usuario>", methods=["PUT"])
@login_required
@roles_required("Master")
def api_master_usuarios_update(id_usuario):
    data = request.get_json(silent=True) or {}
    try:
        nombre = sanitize_text(data.get("nombre"), "El nombre completo", max_len=150)
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    nuevo_rol = str(data.get("rol", ""))
    if nuevo_rol not in ("Master", "Admin", "Cajero"):
        return jsonify({"ok": False, "msg": "Rol invalido."}), 400
    correo = str(data.get("correo") or "").strip().lower()
    if correo and (len(correo) > 150 or not is_valid_email(correo)):
        return jsonify({"ok": False, "msg": "El correo no es valido."}), 400

    password = str(data.get("password") or "")
    if password:
        if len(password) > 128:
            return jsonify({"ok": False, "msg": "La contrasena supera el maximo permitido."}), 400
        if password != str(data.get("confirm_password") or ""):
            return jsonify({"ok": False, "msg": "Las contrasenas no coinciden."}), 400
        pwd_error = first_password_policy_error(password)
        if pwd_error:
            return jsonify({"ok": False, "msg": pwd_error}), 400

    es_actual = id_usuario == session["id_usuario"]
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        usuario = _get_usuario_activo(cur, id_usuario)
        if not usuario:
            return jsonify({"ok": False, "msg": "Usuario no encontrado."}), 404

        # La CC es inmutable: el input va bloqueado en el panel y aqui se
        # rechaza cualquier cambio que llegue por fuera. Solo las cuentas
        # antiguas sin CC pueden registrarla, una vez.
        cc_raw = data.get("cc")
        try:
            if usuario["cc"]:
                if cc_raw not in (None, "") and only_digits(cc_raw) != usuario["cc"]:
                    return jsonify({"ok": False, "msg": "La cedula no se puede modificar."}), 400
                cc = usuario["cc"]
            else:
                cc = _parse_cc(cc_raw)
            # Un Master no se ata a tiendas: su id_tienda no se toca (el suyo
            # propio sostiene su sesion). Sin la clave, la tienda no cambia.
            if nuevo_rol == "Master" or "id_tienda" not in data:
                nueva_tienda = usuario["id_tienda"]
            else:
                nueva_tienda = _tienda_opcional(cur, data.get("id_tienda"))
        except ValueError as exc:
            return jsonify({"ok": False, "msg": str(exc)}), 400

        if es_actual and nuevo_rol != usuario["rol"]:
            return jsonify({"ok": False, "msg": "No puedes cambiar tu propio rol."}), 400
        if (nuevo_rol != "Admin" or nueva_tienda != usuario["id_tienda"]) and _es_ultimo_admin(cur, usuario):
            return jsonify({"ok": False, "msg": "Es el unico Admin de su tienda; asigna otro Admin antes de cambiar su rol o su tienda."}), 400
        if _cc_en_uso(cur, cc, id_usuario):
            return jsonify({"ok": False, "msg": _CC_DUPLICADA}), 409
        if correo and correo != usuario["correo"]:
            liberar_datos_inactivos(cur, correo)
            cur.execute(
                "SELECT 1 FROM usuarios WHERE correo = %s AND id_usuario <> %s LIMIT 1",
                (correo, id_usuario),
            )
            if cur.fetchone():
                return jsonify({"ok": False, "msg": "Ya existe un usuario con ese correo."}), 409
        else:
            correo = usuario["correo"]

        cur.execute(
            "UPDATE usuarios SET nombre_completo = %s, correo = %s, rol = %s, cc = %s, id_tienda = %s "
            "WHERE id_usuario = %s",
            (nombre, correo, nuevo_rol, cc, nueva_tienda, id_usuario),
        )
        if password:
            cur.execute(
                "UPDATE usuarios SET clave_hash = %s WHERE id_usuario = %s",
                (generate_password_hash(password), id_usuario),
            )
        conn.commit()
    except IntegrityError:
        conn.rollback()
        return jsonify({"ok": False, "msg": "Ya existe un usuario con ese correo o cedula."}), 409
    finally:
        conn.close()

    if es_actual:
        session["nombre_completo"] = nombre
    _registrar_auditoria(
        session.get("id_tienda"), session.get("id_usuario"), "editar_usuario",
        f"Se edito usuario id={id_usuario}" + (" (reset contrasena)" if password else ""),
    )
    return jsonify({"ok": True, "msg": "Usuario actualizado."})


@core_bp.route("/api/master/usuarios/<int:id_usuario>", methods=["DELETE"])
@login_required
@roles_required("Master")
def api_master_usuarios_delete(id_usuario):
    if id_usuario == session["id_usuario"]:
        return jsonify({"ok": False, "msg": "No puedes eliminar tu propia cuenta."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        usuario = _get_usuario_activo(cur, id_usuario)
        if not usuario:
            return jsonify({"ok": False, "msg": "Usuario no encontrado."}), 404
        if usuario["rol"] == "Master":
            return jsonify({"ok": False, "msg": "No se puede eliminar un usuario Master."}), 403
        if _es_ultimo_admin(cur, usuario):
            return jsonify({"ok": False, "msg": "Es el unico Admin de su tienda; no se puede eliminar."}), 400
        try:
            cur.execute("DELETE FROM usuarios WHERE id_usuario = %s", (id_usuario,))
            detalle = f"Se borro usuario id={id_usuario}"
        except IntegrityError:
            # Tiene ventas/turnos/gastos (FK RESTRICT): borrarlo destruiria la
            # contabilidad. Se desactiva y se libera su correo/cc para reusarlos.
            conn.rollback()
            cur.execute(
                "UPDATE usuarios SET " + LIBERAR_USUARIO_SQL + " WHERE id_usuario = %s",
                (id_usuario,),
            )
            detalle = f"Se desactivo usuario id={id_usuario} (tiene historial)"
        conn.commit()
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"), session.get("id_usuario"), "eliminar_usuario", detalle,
    )
    return jsonify({"ok": True, "msg": "Usuario eliminado."})


# Finanzas propias del SaaS: mensualidades cobradas y gastos operativos.
@core_bp.route("/api/master/movimientos", methods=["POST"])
@login_required
@roles_required("Master")
def api_master_movimientos_create():
    data = request.get_json(silent=True) or {}
    tipo = str(data.get("tipo", ""))
    if tipo not in ("Ingreso", "Gasto"):
        return jsonify({"ok": False, "msg": "Tipo invalido."}), 400
    try:
        concepto = sanitize_text(data.get("concepto"), "El concepto", max_len=150)
        # Pesos enteros; decimal(12,2) aguanta hasta 9.999.999.999.
        monto = parse_int(data.get("monto"), "El monto", min_value=1, max_value=9_999_999_999)
        fecha_raw = str(data.get("fecha") or "").strip()
        try:
            fecha = date.fromisoformat(fecha_raw) if fecha_raw else date.today()
        except ValueError:
            raise ValueError("Fecha invalida.") from None
        if fecha > date.today():
            raise ValueError("La fecha no puede ser futura.")
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO master_movimientos (tipo, concepto, monto, fecha, id_usuario) "
            "VALUES (%s, %s, %s, %s, %s)",
            (tipo, concepto, monto, fecha, session["id_usuario"]),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "msg": f"{tipo} registrado."})


@core_bp.route("/api/master/movimientos/<int:id_movimiento>", methods=["DELETE"])
@login_required
@roles_required("Master")
def api_master_movimientos_delete(id_movimiento):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM master_movimientos WHERE id_movimiento = %s", (id_movimiento,))
        if cur.rowcount == 0:
            return jsonify({"ok": False, "msg": "Movimiento no encontrado."}), 404
        conn.commit()
    finally:
        conn.close()
    _registrar_auditoria(
        session.get("id_tienda"), session.get("id_usuario"), "eliminar_movimiento_master",
        f"Se borro movimiento id={id_movimiento}",
    )
    return jsonify({"ok": True, "msg": "Movimiento eliminado."})


@core_bp.route("/api/dashboard", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_dashboard():
    filtro = request.args.get("filter") or request.args.get("filtro") or request.args.get("period") or "hoy"
    fecha = request.args.get("fecha") or None
    try:
        data = _build_dashboard_data(session["id_tienda"], filtro, fecha)
    except MySQLError as exc:
        # El mensaje del motor dice que falta ("Unknown column 'dv.unidad_venta'"):
        # casi siempre una migracion sin aplicar. Solo lo ven Admin/Master.
        current_app.logger.exception("api_dashboard: error de base de datos")
        return jsonify({"ok": False, "msg": f"Error de base de datos ({exc.errno}): {exc.msg}"}), 500
    return jsonify({"ok": True, **data})


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
    try:
        nombre = sanitize_text(data.get("nombre_completo"), "El nombre", max_len=150)
        negocio = sanitize_optional_text(data.get("nombre_negocio"), "El negocio", max_len=150) or ""
        telefono_raw = data.get("telefono")
        telefono_digits = only_digits(telefono_raw)
        if telefono_raw and not telefono_digits:
            raise ValueError("Telefono invalido.")
        if telefono_digits and len(telefono_digits) > 25:
            raise ValueError("El telefono no puede superar 25 digitos.")
        telefono = telefono_digits or None
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400

    update_profile_basic(
        id_usuario=int(session["id_usuario"]),
        id_tienda=int(session["id_tienda"]),
        nombre=nombre,
        negocio=negocio,
    )
    session["nombre_completo"] = nombre
    return jsonify({"ok": True, "msg": "Perfil actualizado."})


# ══════════════════════════════════════════════════════════════
# PAGINA 404
# ══════════════════════════════════════════════════════════════

@core_bp.app_errorhandler(404)
def pagina_no_encontrada(_err):
    """404 con la piel del sitio para navegadores, JSON para el frontend.

    Se registra con `app_errorhandler` (no `errorhandler`) para que cubra toda
    la aplicacion y no solo este blueprint. Asi queda una sola definicion que
    heredan los dos bootstraps: core_bp ya se registra en `app/__init__.py` y
    en `app.py`, y no hay que duplicar nada.

    La distincion importa: `fetch` de las vistas POS espera JSON y hace
    `response.json()`. Si a una peticion de API se le devolviera el HTML de la
    pagina 404, el frontend reventaria con un error de parseo en lugar de
    mostrar el aviso del toast. `_is_api_request` es el mismo criterio que ya
    usan los decoradores de sesion, para que todo el proyecto clasifique igual.

    Devuelve la tupla (plantilla, 404) a proposito: sin el codigo explicito
    Flask responderia 200 y los rastreadores indexarian la pagina de error como
    si fuera contenido valido (lo que Google llama "soft 404").
    """
    if _is_api_request():
        return jsonify({"ok": False, "msg": "Ruta no encontrada."}), 404
    return render_template("404.html"), 404
