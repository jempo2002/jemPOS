"""app.py — Punto de entrada de jemPOS (Flask).

Arrancar:
    python app.py
o
    flask --app app run --debug
"""

from __future__ import annotations

import os
import re
import smtplib
import uuid
import calendar
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from functools import wraps
from io import BytesIO

from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import (
    Flask, flash, jsonify, redirect, render_template,
    request, session, url_for,
)
from flask_wtf.csrf import CSRFProtect
from PIL import Image
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, init_pool

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────
load_dotenv()

app = Flask(__name__)
app.config.update(
    SECRET_KEY              = os.environ["SECRET_KEY"],
    # Cookies de sesion seguras
    SESSION_COOKIE_HTTPONLY = True,
    SESSION_COOKIE_SAMESITE = "Lax",
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=45),
    # DB
    DB_HOST     = os.environ.get("DB_HOST", "127.0.0.1"),
    DB_PORT     = int(os.environ.get("DB_PORT", 3306)),
    DB_USER     = os.environ.get("DB_USER", "root"),
    DB_PASSWORD = os.environ.get("DB_PASSWORD", ""),
    DB_NAME     = os.environ.get("DB_NAME", "jempos"),
)

csrf = CSRFProtect(app)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
)

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", 587))

# Inicializar pool al arrancar
with app.app_context():
    init_pool(
        host     = app.config["DB_HOST"],
        port     = app.config["DB_PORT"],
        user     = app.config["DB_USER"],
        password = app.config["DB_PASSWORD"],
        database = app.config["DB_NAME"],
    )


# ─────────────────────────────────────────────────────────────
# Directorio de fotos de perfil
# ─────────────────────────────────────────────────────────────
_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'perfiles')


def _avatar_iniciales(nombre: str) -> str:
    """Devuelve las iniciales del usuario para mostrar en el avatar."""
    partes = nombre.strip().split()
    if len(partes) >= 2:
        return (partes[0][0] + partes[1][0]).upper()
    if partes:
        return partes[0][:2].upper()
    return "??"


def _reset_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(app.secret_key)


def enviar_correo_recuperacion(destinatario: str, enlace: str) -> bool:
    """Envia correo de recuperacion de contrasena via SMTP STARTTLS."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        return False

    cuerpo = (
        "Hola,\n\n"
        "Recibimos una solicitud para restablecer tu contrasena en jemPOS.\n"
        "Haz clic en el siguiente enlace (valido por 15 minutos):\n\n"
        f"{enlace}\n\n"
        "Si no solicitaste este cambio, ignora este correo.\n"
    )
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = "Recuperacion de contrasena - jemPOS"
    msg["From"] = EMAIL_SENDER
    msg["To"] = destinatario

    try:
        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.sendmail(EMAIL_SENDER, [destinatario], msg.as_string())
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# Helpers de suscripcion
# ─────────────────────────────────────────────────────────────
def _get_dias_restantes(id_tienda: int) -> int:
    """Dias restantes de suscripcion (puede ser negativo si expiro)."""
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
        return 999  # Sin fecha registrada → sin limite
    return (row["fecha_fin_suscripcion"] - date.today()).days


def _render_protected(template: str, **kwargs):
    """render_template con contexto de usuario + suscripcion.

    - Si la suscripcion expiro (dias <= 0): redirige a /servicio-suspendido.
    - Si quedan 1–5 dias: pasa mostrar_alerta_suscripcion=True al template.
    - Siempre inyecta `rol` y `nombre_completo` para la UI.
    """
    dias = _get_dias_restantes(session["id_tienda"])
    if dias <= 0:
        return redirect(url_for("servicio_suspendido"))

    nombre = session.get("nombre_completo", "")
    kwargs.setdefault("rol",             session.get("rol", ""))
    kwargs.setdefault("nombre_completo", nombre)
    kwargs.setdefault("foto_perfil",     session.get("foto_perfil"))
    kwargs.setdefault("avatar_iniciales", _avatar_iniciales(nombre))
    kwargs["dias_restantes"]             = dias
    kwargs["mostrar_alerta_suscripcion"] = (0 < dias <= 5)
    return render_template(template, **kwargs)


def _get_categorias_inventario(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT nombre FROM categorias WHERE id_tienda = %s ORDER BY nombre",
            (id_tienda,),
        )
        return [r[0] for r in cur.fetchall() if r and r[0]]
    finally:
        conn.close()


def _get_categorias_gastos(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT concepto FROM gastos_caja WHERE id_tienda = %s ORDER BY concepto",
            (id_tienda,),
        )
        return [r[0] for r in cur.fetchall() if r and r[0]]
    finally:
        conn.close()


def _get_proveedores(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor, nombre_empresa, nombre_contacto, celular, correo, detalles "
            "FROM proveedores "
            "WHERE id_tienda = %s "
            "ORDER BY nombre_empresa",
            (id_tienda,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": r["id_proveedor"],
            "empresa": r.get("nombre_empresa") or "",
            "contacto": r.get("nombre_contacto") or "",
            "celular": r.get("celular") or "",
            "correo": r.get("correo") or "",
            "detalles": r.get("detalles") or "",
        }
        for r in rows
    ]


def _get_insumos(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT i.id_insumo, i.nombre, i.stock_actual, i.unidad_medida, i.costo_unitario, "
            "i.id_proveedor, p.nombre_empresa AS proveedor_nombre "
            "FROM insumos i "
            "LEFT JOIN proveedores p ON p.id_proveedor = i.id_proveedor "
            "WHERE i.id_tienda = %s "
            "ORDER BY i.nombre",
            (id_tienda,),
        )
        rows = cur.fetchall() or []
    except Exception:
        # Compatibilidad: si la tabla no existe aun, la UI puede abrir sin romper.
        rows = []
    finally:
        conn.close()

    return [
        {
            "id_insumo": r.get("id_insumo"),
            "nombre": r.get("nombre") or "",
            "stock_actual": float(r.get("stock_actual") or 0),
            "unidad_medida": (r.get("unidad_medida") or "Un").strip() or "Un",
            "costo_unitario": float(r.get("costo_unitario") or 0),
            "id_proveedor": r.get("id_proveedor"),
            "proveedor_nombre": r.get("proveedor_nombre") or "Sin proveedor",
        }
        for r in rows
    ]


def _get_productos_inventario(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT p.id_producto, p.nombre, c.nombre AS categoria, p.precio_costo, p.precio_venta, "
                "p.stock_actual, p.id_proveedor, COALESCE(p.es_preparado, 0) AS es_preparado "
                "FROM productos p "
                "LEFT JOIN categorias c ON c.id_categoria = p.id_categoria "
                "WHERE p.id_tienda=%s AND p.estado_activo=1 "
                "ORDER BY p.nombre",
                (id_tienda,),
            )
        except Exception:
            cur.execute(
                "SELECT p.id_producto, p.nombre, c.nombre AS categoria, p.precio_costo, p.precio_venta, "
                "p.stock_actual, p.id_proveedor "
                "FROM productos p "
                "LEFT JOIN categorias c ON c.id_categoria = p.id_categoria "
                "WHERE p.id_tienda=%s AND p.estado_activo=1 "
                "ORDER BY p.nombre",
                (id_tienda,),
            )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        {
            "id": r.get("id_producto"),
            "nombre": r.get("nombre") or "",
            "categoria": r.get("categoria") or "",
            "precio_costo": float(r.get("precio_costo") or 0),
            "precio_venta": float(r.get("precio_venta") or 0),
            "stock_actual": float(r.get("stock_actual") or 0),
            "id_proveedor": r.get("id_proveedor"),
            "es_preparado": bool(r.get("es_preparado") or 0),
        }
        for r in rows
    ]


def _get_fiados_clientes(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT c.id_cliente, c.nombre, c.telefono,
              COALESCE((
                                SELECT SUM(
                                    GREATEST(
                                        v.total_final - COALESCE((
                                            SELECT SUM(ab.monto_abonado)
                                            FROM abonos_fiados ab
                                            WHERE ab.id_venta = v.id_venta
                                        ), 0),
                                        0
                                    )
                                )
                FROM ventas v
                WHERE v.id_cliente = c.id_cliente
                  AND v.id_tienda  = c.id_tienda
                                    AND v.estado_venta = 'Fiada/Pendiente'
              ), 0) AS deuda_total
            FROM clientes c
            WHERE c.id_tienda = %s AND c.estado_activo = 1
            ORDER BY c.nombre
            """,
            (id_tienda,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "id":    r["id_cliente"],
            "name":  r["nombre"],
            "phone": r["telefono"] or "—",
            "debt":  max(0.0, float(r["deuda_total"] or 0)),
        }
        for r in rows
    ]


def _add_months(base_date: date, months: int) -> date:
    """Suma meses conservando el dia valido en el mes destino."""
    m = base_date.month - 1 + months
    year = base_date.year + m // 12
    month = m % 12 + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _get_master_tiendas() -> list:
    """Listado de tiendas con datos de dueno (Admin) para panel Master."""
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
        tiendas.append({
            "id_tienda": tid,
            "nombre_negocio": r["nombre_negocio"],
            "nit": r.get("nit") or "—",
            "telefono": r.get("telefono") or "—",
            "fecha_fin_suscripcion": r.get("fecha_fin_suscripcion"),
            "estado_suscripcion": r.get("estado_suscripcion") or "suspendida",
            "owner_id": r.get("owner_id"),
            "owner_name": r.get("owner_name") or "Sin dueno",
        })
    return tiendas


def _get_master_proximos_vencer() -> list:
    """Tiendas vencidas o por vencer en los proximos 5 dias."""
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
        data.append({
            "id_tienda": r["id_tienda"],
            "nombre_negocio": r["nombre_negocio"],
            "telefono": phone or "—",
            "fecha_fin_suscripcion": r.get("fecha_fin_suscripcion"),
            "dias_restantes": int(r.get("dias_restantes") or 0),
            "wa_url": f"https://wa.me/57{digits}" if digits else None,
        })
    return data


def registrar_auditoria(id_tienda, id_usuario, accion, detalles):
    """Registra eventos criticos sin bloquear transacciones principales."""
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
        # La auditoria no debe cortar el flujo de negocio.
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


def _fmt_money(value: float) -> str:
    """Formato COP simple para UI."""
    return f"${int(round(value)):,}".replace(",", ".")


def _normalize_payment_method(raw_method: str | None, allow_fiado: bool = False) -> str | None:
    """Normaliza metodos de pago de UI/API al formato de BD."""
    key = str(raw_method or "").strip().lower()
    mapping = {
        "efectivo": "Efectivo",
        "nequi": "Nequi/Daviplata",
        "nequi/daviplata": "Nequi/Daviplata",
        "tarjeta": "Tarjeta",
        "fiado": "fiado",
    }
    value = mapping.get(key)
    if value == "fiado" and not allow_fiado:
        return None
    return value


def _dashboard_period_bounds(raw_filter: str):
    """Devuelve filtro normalizado y rangos [inicio, fin) para consultas."""
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
    """Calcula metricas reales del dashboard y datasets para grafico/listas."""
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
                "value": _fmt_money(float(r["rent"] or 0)),
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
        ingresos_por_dia = {
            r["d"]: float(r["total"] or 0)
            for r in cur.fetchall()
        }

        cur.execute(
            "SELECT DATE(g.fecha_creacion) AS d, COALESCE(SUM(g.monto),0) AS total "
            "FROM gastos_caja g "
            "WHERE g.id_tienda=%s "
            "AND g.fecha_creacion >= %s AND g.fecha_creacion < %s "
            "GROUP BY DATE(g.fecha_creacion) "
            "ORDER BY DATE(g.fecha_creacion)",
            (id_tienda, since, until),
        )
        gastos_por_dia = {
            r["d"]: float(r["total"] or 0)
            for r in cur.fetchall()
        }

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
            deudores.append({
                "name": r["nombre"],
                "phone": r.get("telefono") or "—",
                "debt": deuda,
                "debt_fmt": _fmt_money(deuda),
                "days_overdue": max(0, int(dias)),
            })

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
            cajeros_abiertos.append({
                "name": r["nombre_completo"],
                "value": _fmt_money(total_turno),
                "id_turno": r["id_turno"],
            })
    finally:
        conn.close()

    return {
        "filtro": filtro,
        "kpis": {
            "ventas": ventas,
            "ventas_fmt": _fmt_money(ventas),
            "ganancia": ganancia_neta,
            "ganancia_fmt": _fmt_money(ganancia_neta),
            "gastos": gastos,
            "gastos_fmt": _fmt_money(gastos),
            "fiados": cuentas_por_cobrar,
            "fiados_fmt": _fmt_money(cuentas_por_cobrar),
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


# ─────────────────────────────────────────────────────────────
# Decoradores de seguridad
# ─────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def _inner(*args, **kwargs):
        if "id_usuario" not in session:
            # Las llamadas JSON reciben 401; las paginas redirigen al login
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"ok": False, "msg": "Sesion expirada."}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return _inner


def roles_required(*roles: str):
    """Permite el acceso solo a los roles indicados.

    Si el usuario no tiene el rol, redirige a /caja con un mensaje flash de error.
    """
    def decorator(f):
        @wraps(f)
        def _inner(*args, **kwargs):
            if session.get("rol") not in roles:
                flash("No tienes permisos para ver esta pantalla.", "error")
                return redirect(url_for("caja_page"))
            return f(*args, **kwargs)
        return _inner
    return decorator


# ─────────────────────────────────────────────────────────────
# Rutas de paginas HTML
# ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if "id_usuario" in session:
        return redirect(url_for("turno_page"))
    return redirect(url_for("login_page"))


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login_page():
    if request.method == "GET":
        if "id_usuario" in session:
            return redirect(url_for("turno_page"))
        return render_template("auth/login.html")

    data = request.get_json(silent=True) if request.is_json else request.form
    correo = str((data or {}).get("correo", "")).strip().lower()
    contrasena = str((data or {}).get("contrasena", ""))

    if not correo or not contrasena:
        if request.is_json:
            return jsonify({"ok": False, "msg": "Correo y contrasena son requeridos."}), 400
        flash("Correo y contrasena son requeridos.", "error")
        return redirect(url_for("login_page"))

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT u.id_usuario, u.id_tienda, u.nombre_completo, u.clave_hash, u.rol, "
                "u.estado_activo, u.foto_perfil, COALESCE(t.es_restaurante, 0) AS es_restaurante "
                "FROM usuarios u "
                "LEFT JOIN tiendas t ON t.id_tienda = u.id_tienda "
                "WHERE u.correo = %s LIMIT 1",
                (correo,),
            )
        except Exception as e:
            # Compatibilidad temporal si la columna es_restaurante aun no existe en algun entorno.
            if "es_restaurante" in str(e):
                cur.execute(
                    "SELECT id_usuario, id_tienda, nombre_completo, clave_hash, rol, estado_activo, foto_perfil "
                    "FROM usuarios WHERE correo = %s LIMIT 1",
                    (correo,),
                )
            else:
                raise
        user = cur.fetchone()
    finally:
        conn.close()

    if not user:
        if request.is_json:
            return jsonify({"ok": False, "field": "correo", "msg": "Usuario no encontrado."}), 401
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("login_page"))

    if not check_password_hash(user["clave_hash"], contrasena):
        if request.is_json:
            return jsonify({"ok": False, "field": "contrasena", "msg": "Contrasena incorrecta."}), 401
        flash("Contrasena incorrecta.", "error")
        return redirect(url_for("login_page"))

    if not user["estado_activo"]:
        if request.is_json:
            return jsonify({"ok": False, "msg": "Cuenta desactivada. Contacta al administrador."}), 403
        flash("Cuenta desactivada. Contacta al administrador.", "error")
        return redirect(url_for("login_page"))

    session.clear()
    session.permanent = True
    session["id_usuario"] = user["id_usuario"]
    session["id_tienda"] = user["id_tienda"]
    session["nombre_completo"] = user["nombre_completo"]
    session["rol"] = user["rol"]
    session["foto_perfil"] = user.get("foto_perfil") or None
    session["es_restaurante"] = bool(user.get("es_restaurante"))

    rol = user["rol"]
    if rol == "Master":
        redirect_url = "/panel-master"
    elif rol == "Admin":
        conn2 = get_db()
        try:
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT COUNT(*) FROM categorias WHERE id_tienda = %s",
                (user["id_tienda"],),
            )
            cat_count = cur2.fetchone()[0]
        finally:
            conn2.close()
        redirect_url = "/dashboard" if cat_count > 0 else "/onboarding"
    else:
        redirect_url = "/turno"

    if request.is_json:
        return jsonify({"ok": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/olvide_password", methods=["GET", "POST"])
def olvide_password():
    if request.method == "POST":
        correo = str(request.form.get("correo", "")).strip().lower()
        if correo:
            conn = get_db()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT correo FROM usuarios WHERE correo = %s LIMIT 1",
                    (correo,),
                )
                user = cur.fetchone()
            finally:
                conn.close()

            if user:
                token = _reset_serializer().dumps(correo, salt="password-reset-salt")
                enlace = url_for("reset_password", token=token, _external=True)
                enviar_correo_recuperacion(correo, enlace)

        flash("Si el correo existe, recibiras un enlace de recuperacion.", "success")
        return redirect(url_for("olvide_password"))

    return render_template("auth/olvide_password.html")


@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        correo = _reset_serializer().loads(token, salt="password-reset-salt", max_age=900)
    except (SignatureExpired, BadSignature):
        flash("El enlace de recuperacion es invalido o ha expirado.", "error")
        return redirect(url_for("login_page"))

    if request.method == "POST":
        password = str(request.form.get("password", ""))
        confirm = str(request.form.get("confirm_password", ""))

        if password != confirm:
            flash("Las contrasenas no coinciden.", "error")
            return redirect(url_for("reset_password", token=token))
        if len(password) < 8:
            flash("La contrasena debe tener al menos 8 caracteres.", "error")
            return redirect(url_for("reset_password", token=token))
        if not _PWD_RE["upper"].search(password):
            flash("La contrasena debe incluir al menos una letra mayuscula.", "error")
            return redirect(url_for("reset_password", token=token))
        if not _PWD_RE["lower"].search(password):
            flash("La contrasena debe incluir al menos una letra minuscula.", "error")
            return redirect(url_for("reset_password", token=token))
        if not _PWD_RE["number"].search(password):
            flash("La contrasena debe incluir al menos un numero.", "error")
            return redirect(url_for("reset_password", token=token))

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE usuarios SET clave_hash = %s WHERE correo = %s",
                (generate_password_hash(password), correo),
            )
            conn.commit()
        finally:
            conn.close()

        flash("Tu contrasena fue actualizada correctamente.", "success")
        return redirect(url_for("login_page"))

    return render_template("auth/reset_password.html", token=token)


@app.route("/servicio-suspendido")
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


@app.route("/turno")
@login_required
def turno_page():
    return _render_protected("pos/turno.html")


@app.route("/dashboard")
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


@app.route("/caja")
@login_required
def caja_page():
    return _render_protected("pos/caja.html")


@app.route("/inventario")
@login_required
@roles_required("Admin", "Master", "Cajero")
def inventario_page():
    return _render_protected(
        "pos/inventario.html",
        productos=_get_productos_inventario(session["id_tienda"]),
        insumos=_get_insumos(session["id_tienda"]),
        categorias=_get_categorias_inventario(session["id_tienda"]),
        proveedores=_get_proveedores(session["id_tienda"]),
    )


@app.route("/insumos")
@login_required
@roles_required("Admin", "Master")
def insumos_page():
    return _render_protected(
        "pos/insumos.html",
        insumos=_get_insumos(session["id_tienda"]),
        proveedores=_get_proveedores(session["id_tienda"]),
    )


@app.route("/insumos/crear", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def insumos_crear_page():
    nombre = str(request.form.get("nombre", "")).strip()
    unidad = str(request.form.get("unidad_medida", "Un")).strip() or "Un"
    proveedor_raw = request.form.get("id_proveedor")

    try:
        stock = float(request.form.get("stock_actual", 0) or 0)
        costo = float(request.form.get("costo_unitario", 0) or 0)
    except (TypeError, ValueError):
        flash("Stock y costo deben ser numericos.", "error")
        return redirect(url_for("insumos_page"))

    if not nombre:
        flash("El nombre del insumo es requerido.", "error")
        return redirect(url_for("insumos_page"))

    if unidad not in {"Gr", "Ml", "Un"}:
        flash("Unidad invalida. Usa Gr, Ml o Un.", "error")
        return redirect(url_for("insumos_page"))

    if stock < 0 or costo < 0:
        flash("Stock y costo no pueden ser negativos.", "error")
        return redirect(url_for("insumos_page"))

    try:
        proveedor_id = int(proveedor_raw) if proveedor_raw not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        flash("Proveedor invalido.", "error")
        return redirect(url_for("insumos_page"))

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, session["id_tienda"]),
            )
            if not cur.fetchone():
                flash("Proveedor no encontrado para esta tienda.", "error")
                return redirect(url_for("insumos_page"))

        cur.execute(
            "INSERT INTO insumos "
            "(id_tienda, nombre, stock_actual, unidad_medida, costo_unitario, id_proveedor) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (session["id_tienda"], nombre, stock, unidad, costo, proveedor_id),
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception:
        flash("No fue posible crear el insumo. Verifica migraciones de base de datos.", "error")
        return redirect(url_for("insumos_page"))
    finally:
        conn.close()

    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "crear_insumo",
        f"Insumo creado id={new_id}, nombre={nombre}",
    )
    flash("Insumo creado correctamente.", "success")
    return redirect(url_for("insumos_page"))


@app.route("/insumos/editar/<int:id_insumo>", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def insumos_editar_page(id_insumo):
    nombre = str(request.form.get("nombre", "")).strip()
    unidad = str(request.form.get("unidad_medida", "Un")).strip() or "Un"
    proveedor_raw = request.form.get("id_proveedor")

    try:
        stock = float(request.form.get("stock_actual", 0) or 0)
        costo = float(request.form.get("costo_unitario", 0) or 0)
    except (TypeError, ValueError):
        flash("Stock y costo deben ser numericos.", "error")
        return redirect(url_for("insumos_page"))

    if not nombre:
        flash("El nombre del insumo es requerido.", "error")
        return redirect(url_for("insumos_page"))

    if unidad not in {"Gr", "Ml", "Un"}:
        flash("Unidad invalida. Usa Gr, Ml o Un.", "error")
        return redirect(url_for("insumos_page"))

    if stock < 0 or costo < 0:
        flash("Stock y costo no pueden ser negativos.", "error")
        return redirect(url_for("insumos_page"))

    try:
        proveedor_id = int(proveedor_raw) if proveedor_raw not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        flash("Proveedor invalido.", "error")
        return redirect(url_for("insumos_page"))

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, session["id_tienda"]),
            )
            if not cur.fetchone():
                flash("Proveedor no encontrado para esta tienda.", "error")
                return redirect(url_for("insumos_page"))

        cur.execute(
            "UPDATE insumos "
            "SET nombre=%s, stock_actual=%s, unidad_medida=%s, costo_unitario=%s, id_proveedor=%s "
            "WHERE id_insumo=%s AND id_tienda=%s",
            (nombre, stock, unidad, costo, proveedor_id, id_insumo, session["id_tienda"]),
        )
        conn.commit()
        updated = cur.rowcount > 0
    except Exception:
        flash("No fue posible actualizar el insumo.", "error")
        return redirect(url_for("insumos_page"))
    finally:
        conn.close()

    if not updated:
        flash("Insumo no encontrado para esta tienda.", "error")
        return redirect(url_for("insumos_page"))

    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "editar_insumo",
        f"Insumo editado id={id_insumo}, nombre={nombre}",
    )
    flash("Insumo actualizado correctamente.", "success")
    return redirect(url_for("insumos_page"))


@app.route("/insumos/eliminar/<int:id_insumo>", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def insumos_eliminar_page(id_insumo):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM insumos WHERE id_insumo=%s AND id_tienda=%s",
            (id_insumo, session["id_tienda"]),
        )
        conn.commit()
        deleted = cur.rowcount > 0
    except Exception:
        flash("No fue posible eliminar el insumo.", "error")
        return redirect(url_for("insumos_page"))
    finally:
        conn.close()

    if not deleted:
        flash("Insumo no encontrado para esta tienda.", "error")
        return redirect(url_for("insumos_page"))

    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "eliminar_insumo",
        f"Insumo eliminado id={id_insumo}",
    )
    flash("Insumo eliminado correctamente.", "success")
    return redirect(url_for("insumos_page"))


@app.route("/fiados")
@login_required
def fiados_page():
    return _render_protected(
        "pos/fiados.html",
        fiados_clientes=_get_fiados_clientes(session["id_tienda"]),
    )


@app.route("/gastos")
@login_required
@roles_required("Admin", "Master", "Cajero")
def gastos_page():
    return _render_protected(
        "pos/gastos.html",
        categorias_gastos=_get_categorias_gastos(session["id_tienda"]),
    )


@app.route("/proveedores")
@login_required
@roles_required("Admin", "Master")
def proveedores_page():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM proveedores WHERE id_tienda = %s ORDER BY nombre_empresa",
            (session["id_tienda"],),
        )
        proveedores = cur.fetchall()
    finally:
        conn.close()

    return _render_protected("pos/proveedores.html", proveedores=proveedores)


@app.route("/proveedores/crear", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def proveedores_crear_page():
    empresa = str(request.form.get("empresa", "")).strip()
    nombre_contacto = str(request.form.get("nombre_contacto", "")).strip()
    celular = re.sub(r"\D", "", str(request.form.get("celular", "")).strip())
    correo = str(request.form.get("correo", "")).strip()
    detalles = str(request.form.get("detalles", "")).strip()

    if not empresa:
        flash("La empresa es requerida.", "error")
        return redirect(url_for("proveedores_page"))

    if celular and len(celular) > 10:
        flash("El celular debe tener maximo 10 digitos.", "error")
        return redirect(url_for("proveedores_page"))

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO proveedores (id_tienda, nombre_empresa, nombre_contacto, celular, correo, detalles) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                session["id_tienda"],
                empresa,
                nombre_contacto or None,
                celular or None,
                correo or None,
                detalles or None,
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()

    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "crear_proveedor",
        f"Proveedor creado id={new_id}, empresa={empresa}",
    )
    flash("Proveedor creado correctamente.", "success")
    return redirect(url_for("proveedores_page"))


@app.route("/proveedores/editar/<int:id_proveedor>", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def proveedores_editar_page(id_proveedor):
    empresa = str(request.form.get("empresa", "")).strip()
    nombre_contacto = str(request.form.get("nombre_contacto", "")).strip()
    celular = re.sub(r"\D", "", str(request.form.get("celular", "")).strip())
    correo = str(request.form.get("correo", "")).strip()
    detalles = str(request.form.get("detalles", "")).strip()

    if not empresa:
        flash("La empresa es requerida.", "error")
        return redirect(url_for("proveedores_page"))

    if celular and len(celular) > 10:
        flash("El celular debe tener maximo 10 digitos.", "error")
        return redirect(url_for("proveedores_page"))

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE proveedores "
            "SET nombre_empresa=%s, nombre_contacto=%s, celular=%s, correo=%s, detalles=%s "
            "WHERE id_proveedor=%s AND id_tienda=%s",
            (
                empresa,
                nombre_contacto or None,
                celular or None,
                correo or None,
                detalles or None,
                id_proveedor,
                session["id_tienda"],
            ),
        )
        conn.commit()
        updated = cur.rowcount > 0
    finally:
        conn.close()

    if not updated:
        flash("Proveedor no encontrado para esta tienda.", "error")
        return redirect(url_for("proveedores_page"))

    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "editar_proveedor",
        f"Proveedor editado id={id_proveedor}, empresa={empresa}",
    )
    flash("Proveedor actualizado correctamente.", "success")
    return redirect(url_for("proveedores_page"))


@app.route("/proveedores/eliminar/<int:id_proveedor>", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def proveedores_eliminar_page(id_proveedor):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s",
            (id_proveedor, session["id_tienda"]),
        )
        conn.commit()
        deleted = cur.rowcount > 0
    finally:
        conn.close()

    if not deleted:
        flash("Proveedor no encontrado para esta tienda.", "error")
        return redirect(url_for("proveedores_page"))

    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "eliminar_proveedor",
        f"Proveedor eliminado id={id_proveedor}",
    )
    flash("Proveedor eliminado correctamente.", "success")
    return redirect(url_for("proveedores_page"))


@app.route("/ventas")
@login_required
def ventas():
    if not session.get("id_usuario"):
        return redirect(url_for("login_page"))

    id_tienda = session.get("id_tienda")
    rol = (session.get("rol") or "").strip()
    filtro_url = request.args.get("filtro")
    filtro = "24h" if rol == "Cajero" else (filtro_url or "mes")
    ventas = []

    if not id_tienda:
        flash("No se encontro la tienda activa en la sesion.", "error")
        return redirect(url_for("dashboard_page"))

    conn = get_db()
    try:
        cursor = conn.cursor(dictionary=True)
        query = (
            "SELECT v.id_venta, v.total_final, v.estado_venta, v.fecha_creacion, "
            "COALESCE(c.nombre, 'Mostrador') AS nombre_cliente, "
            "u.nombre_completo AS nombre_cajero "
            "FROM ventas v "
            "LEFT JOIN clientes c ON v.id_cliente = c.id_cliente "
            "LEFT JOIN usuarios u ON v.id_cajero = u.id_usuario "
            "WHERE v.id_tienda = %s "
        )
        params = [id_tienda]

        if rol == "Cajero":
            # Seguridad: Cajero no puede manipular filtros por URL.
            filtro = "24h"
            query += "AND v.id_cajero = %s "
            params.append(session.get("id_usuario"))
            query += "AND v.fecha_creacion >= (NOW() - INTERVAL 1 DAY) "
        elif rol in {"Admin", "Master"}:
            if filtro not in {"hoy", "semana", "mes", "todas"}:
                filtro = "mes"

            if filtro == "hoy":
                query += "AND DATE(v.fecha_creacion) = CURDATE() "
            elif filtro == "semana":
                query += "AND v.fecha_creacion >= (NOW() - INTERVAL 7 DAY) "
            elif filtro == "mes":
                query += "AND YEAR(v.fecha_creacion) = YEAR(CURDATE()) AND MONTH(v.fecha_creacion) = MONTH(CURDATE()) "
        else:
            flash("No tienes permisos para ver el historial de ventas.", "error")
            return redirect(url_for("dashboard_page"))

        query += "ORDER BY v.id_venta DESC"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall() or []
    finally:
        conn.close()

    for row in rows:
        ventas.append({
            "id_venta": row.get("id_venta"),
            "total_final": float(row.get("total_final") or 0),
            "estado_venta": (row.get("estado_venta") or "Pagada").strip() or "Pagada",
            "fecha_creacion": row.get("fecha_creacion"),
            "nombre_cliente": row.get("nombre_cliente") or "Mostrador",
            "nombre_cajero": row.get("nombre_cajero") or "Sin cajero",
        })

    return _render_protected(
        "pos/ventas.html",
        ventas=ventas,
        filtro_activo=filtro,
    )

@app.route("/perfil")
@login_required
@roles_required("Admin")
def perfil_page():
    return _render_protected("pos/perfil.html")


@app.route("/onboarding")
@login_required
@roles_required("Admin", "Master")
def onboarding_page():
    return _render_protected("pos/onboarding.html")


@app.route("/panel-master")
@login_required
@roles_required("Admin", "Master")
def panel_master_page():
    # Para el Master no se verifica suscripcion de su tienda
    return render_template(
        "auth/panel_master.html",
        rol=session.get("rol", ""),
        nombre_completo=session.get("nombre_completo", ""),
        tiendas=_get_master_tiendas(),
        proximos_vencer=_get_master_proximos_vencer(),
        hoy=date.today(),
    )


# ─────────────────────────────────────────────────────────────
# API — Autenticacion
# ─────────────────────────────────────────────────────────────
@app.route("/api/auth/login", methods=["POST"])
def api_login():
    return login_page()


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True, "redirect": "/login"})


# ─────────────────────────────────────────────────────────────
# API — Turno de Caja
# ─────────────────────────────────────────────────────────────
@app.route("/api/turno/estado", methods=["GET"])
@login_required
def api_turno_estado():
    """Devuelve el turno abierto de la tienda, o null si no hay ninguno."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno, fecha_apertura, monto_inicial "
            "FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
            "ORDER BY fecha_apertura DESC LIMIT 1",
            (session["id_tienda"],),
        )
        turno = cur.fetchone()
    finally:
        conn.close()

    if turno:
        return jsonify({
            "ok": True,
            "turno": {
                "id_turno":      turno["id_turno"],
                "hora_apertura": turno["fecha_apertura"].strftime("%I:%M %p"),
                "monto_inicial": float(turno["monto_inicial"]),
            },
        })
    return jsonify({"ok": True, "turno": None})


@app.route("/api/turno/abrir", methods=["POST"])
@login_required
def api_turno_abrir():
    """Abre un nuevo turno. Rechaza si ya hay uno abierto."""
    data = request.get_json(silent=True) or {}
    try:
        monto = float(data.get("monto_inicial", 0))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400

    if monto <= 0:
        return jsonify({"ok": False, "msg": "El monto debe ser mayor a cero."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        # Verificar que no haya turno abierto
        cur.execute(
            "SELECT id_turno FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' LIMIT 1",
            (session["id_tienda"],),
        )
        if cur.fetchone():
            return jsonify({"ok": False, "msg": "Ya hay un turno abierto para esta tienda."}), 409

        cur.execute(
            "INSERT INTO turnos_caja "
            "(id_tienda, id_usuario_apertura, monto_inicial, monto_final_esperado) "
            "VALUES (%s, %s, %s, %s)",
            (session["id_tienda"], session["id_usuario"], monto, monto),
        )
        conn.commit()
        turno_id = cur.lastrowid
    finally:
        conn.close()

    return jsonify({"ok": True, "id_turno": turno_id})


@app.route("/api/turno/cerrar", methods=["POST"])
@login_required
def api_turno_cerrar():
    """Cierra el turno abierto de la tienda."""
    data = request.get_json(silent=True) or {}
    try:
        monto_final = float(data.get("monto_final", -1))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400

    if monto_final < 0:
        return jsonify({"ok": False, "msg": "El monto no puede ser negativo."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
            "ORDER BY fecha_apertura DESC LIMIT 1",
            (session["id_tienda"],),
        )
        turno = cur.fetchone()
        if not turno:
            return jsonify({"ok": False, "msg": "No hay turno abierto."}), 404

        cur.execute(
            "UPDATE turnos_caja "
            "SET estado_turno = 'Cerrado', fecha_cierre = NOW(), "
            "    monto_final_real = %s, id_usuario_cierre = %s "
            "WHERE id_turno = %s",
            (monto_final, session["id_usuario"], turno["id_turno"]),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# API — Onboarding
# ─────────────────────────────────────────────────────────────
@app.route("/api/onboarding", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_onboarding():
    """Guarda la primera categoria y producto del negocio."""
    data     = request.get_json(silent=True) or {}
    category = str(data.get("category", "")).strip()
    product  = str(data.get("product",  "")).strip()
    cost     = data.get("cost")
    sale     = data.get("sale")
    stock    = data.get("stock", 0)

    if not category:
        return jsonify({"ok": False, "msg": "El nombre de la categoria es requerido."}), 400
    if not product:
        return jsonify({"ok": False, "msg": "El nombre del producto es requerido."}), 400

    try:
        cost  = float(cost)  if cost  not in (None, "") else 0.0
        sale  = float(sale)  if sale  not in (None, "") else 0.0
        stock = int(stock)   if stock not in (None, "") else 0
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


# ─────────────────────────────────────────────────────────────
# API — Crear Usuario
# ─────────────────────────────────────────────────────────────
_PWD_RE = {
    "upper":  re.compile(r"[A-Z]"),
    "lower":  re.compile(r"[a-z]"),
    "number": re.compile(r"\d"),
    "email":  re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$"),
}


@app.route("/api/tiendas", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_tiendas():
    q    = request.args.get("q", "").strip()
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


@app.route("/api/master/admins", methods=["GET"])
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


@app.route("/api/master/tiendas", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_master_tiendas_create():
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre_negocio", "")).strip()
    nit = str(data.get("nit", "")).strip() or None
    telefono_raw = str(data.get("telefono", "")).strip()
    telefono = re.sub(r"\D", "", telefono_raw)[:10] or None
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


@app.route("/api/master/tiendas/<int:id_tienda>", methods=["PUT"])
@login_required
@roles_required("Admin", "Master")
def api_master_tiendas_update(id_tienda):
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre_negocio", "")).strip()
    nit = str(data.get("nit", "")).strip() or None
    telefono_raw = str(data.get("telefono", "")).strip()
    telefono = re.sub(r"\D", "", telefono_raw)[:10] or None
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


@app.route("/api/master/tiendas/<int:id_tienda>", methods=["DELETE"])
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
    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "eliminar_tienda",
        f"Se elimino tienda id={id_tienda}",
    )
    return jsonify({"ok": True, "msg": "Tienda eliminada."})


@app.route("/api/master/suscripciones", methods=["POST"])
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


@app.route("/api/crear_usuario", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_crear_usuario():
    data            = request.get_json(silent=True) or {}
    nombre          = str(data.get("nombre", "")).strip()
    correo          = str(data.get("correo", "")).strip().lower()
    password        = str(data.get("password", ""))
    confirm         = str(data.get("confirm_password", ""))
    cedula          = str(data.get("cedula",   "") or "").strip()
    telefono        = str(data.get("telefono", "") or "").strip()
    rol_sesion      = session["rol"]

    # ── Rol e id_tienda segun quien crea ─────────────────────
    if rol_sesion == "Admin":
        nuevo_rol = "Cajero"                       # Admin solo puede crear cajeros
        id_tienda = session["id_tienda"]
    else:  # Master
        nuevo_rol = str(data.get("rol", "Cajero"))
        if nuevo_rol not in ("Master", "Admin", "Cajero"):
            return jsonify({"ok": False, "msg": "Rol invalido."}), 400
        nombre_negocio = None
        id_tienda      = None
        if nuevo_rol == "Admin":
            nombre_negocio = str(data.get("nombre_negocio", "")).strip()
            # Si no se envia negocio, se crea Admin sin tienda para asignarlo luego.
            # Si se envia, se mantiene el comportamiento previo (crear tienda al vuelo).
        elif nuevo_rol == "Cajero":
            try:
                id_tienda = int(data.get("id_tienda"))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "msg": "Debes seleccionar una tienda valida."}), 400
        else:  # Master
            try:
                id_tienda = int(data.get("id_tienda", session["id_tienda"]))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "msg": "ID de tienda invalido."}), 400

    # ── Validacion de campos ──────────────────────────────────
    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre completo es requerido."}), 400
    if not correo or not _PWD_RE["email"].match(correo):
        return jsonify({"ok": False, "msg": "El correo no es valido."}), 400
    if not password:
        return jsonify({"ok": False, "msg": "La contrasena es requerida."}), 400
    if password != confirm:
        return jsonify({"ok": False, "msg": "Las contrasenas no coinciden."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "msg": "La contrasena debe tener al menos 8 caracteres."}), 400
    if not _PWD_RE["upper"].search(password):
        return jsonify({"ok": False, "msg": "La contrasena debe incluir al menos una letra mayuscula."}), 400
    if not _PWD_RE["lower"].search(password):
        return jsonify({"ok": False, "msg": "La contrasena debe incluir al menos una letra minuscula."}), 400
    if not _PWD_RE["number"].search(password):
        return jsonify({"ok": False, "msg": "La contrasena debe incluir al menos un numero."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        # Verificar que el correo no este registrado
        cur.execute(
            "SELECT id_usuario FROM usuarios WHERE correo = %s LIMIT 1",
            (correo,),
        )
        if cur.fetchone():
            return jsonify({"ok": False, "msg": "Ya existe un usuario con ese correo."}), 409

        # Master creando Admin con nombre_negocio → crear tienda al vuelo (compatibilidad)
        if rol_sesion == "Master" and nuevo_rol == "Admin" and nombre_negocio:
            cur.execute(
                "INSERT INTO tiendas (nombre_negocio, estado_suscripcion) VALUES (%s, 'activa')",
                (nombre_negocio,),
            )
            id_tienda = cur.lastrowid

        clave_hash = generate_password_hash(password)
        # Intentar INSERT con cedula y telefono; si las columnas no existen, reintentar sin ellas
        import mysql.connector.errors as _mc_err
        try:
            cur.execute(
                "INSERT INTO usuarios (id_tienda, nombre_completo, correo, clave_hash, rol, cedula, telefono) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (id_tienda, nombre, correo, clave_hash, nuevo_rol,
                 cedula or None, telefono or None),
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


# ─────────────────────────────────────────────────────────────
# API — Inventario
# ─────────────────────────────────────────────────────────────
def _turno_abierto(id_tienda: int, cur) -> int | None:
    """Devuelve id_turno abierto o None. Reutiliza cursor existente."""
    cur.execute(
        "SELECT id_turno FROM turnos_caja "
        "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
        "ORDER BY fecha_apertura DESC LIMIT 1",
        (id_tienda,),
    )
    row = cur.fetchone()
    return row["id_turno"] if row else None


@app.route("/api/inventario", methods=["GET"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_list():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT p.id_producto, p.nombre, c.nombre AS categoria, "
                "p.precio_costo, p.precio_venta, p.stock_actual, p.stock_minimo_alerta, "
                "p.id_proveedor, pr.nombre_empresa AS proveedor_nombre, COALESCE(p.es_preparado, 0) AS es_preparado "
                "FROM productos p "
                "LEFT JOIN categorias c ON c.id_categoria = p.id_categoria "
                "LEFT JOIN proveedores pr ON pr.id_proveedor = p.id_proveedor "
                "WHERE p.id_tienda = %s AND p.estado_activo = 1 "
                "ORDER BY p.nombre",
                (session["id_tienda"],),
            )
        except Exception:
            cur.execute(
                "SELECT p.id_producto, p.nombre, c.nombre AS categoria, "
                "p.precio_costo, p.precio_venta, p.stock_actual, p.stock_minimo_alerta, "
                "p.id_proveedor, pr.nombre_empresa AS proveedor_nombre "
                "FROM productos p "
                "LEFT JOIN categorias c ON c.id_categoria = p.id_categoria "
                "LEFT JOIN proveedores pr ON pr.id_proveedor = p.id_proveedor "
                "WHERE p.id_tienda = %s AND p.estado_activo = 1 "
                "ORDER BY p.nombre",
                (session["id_tienda"],),
            )
        rows = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"ok": True, "productos": [
        {
            "id":        r["id_producto"],
            "name":      r["nombre"],
            "category":  r["categoria"] or "",
            "cost":      float(r["precio_costo"]),
            "sale":      float(r["precio_venta"]),
            "stock":     r["stock_actual"],
            "stock_min": r["stock_minimo_alerta"] or 0,
            "proveedor_id": r.get("id_proveedor"),
            "proveedor_nombre": r.get("proveedor_nombre") or "",
            "es_preparado": bool(r.get("es_preparado") or 0),
        }
        for r in rows
    ]})


@app.route("/api/proveedores", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_list():
    return jsonify({"ok": True, "proveedores": _get_proveedores(session["id_tienda"])})


@app.route("/api/proveedores", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_create():
    data = request.get_json(silent=True) or {}
    empresa = str(data.get("empresa", "")).strip()
    contacto = str(data.get("contacto", "")).strip()
    celular = str(data.get("celular", "")).strip()
    correo = str(data.get("correo", "")).strip()
    detalles = str(data.get("detalles", "")).strip()

    if not empresa:
        return jsonify({"ok": False, "msg": "La empresa es requerida."}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO proveedores "
            "(id_tienda, nombre_empresa, nombre_contacto, celular, correo, detalles) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                session["id_tienda"],
                empresa,
                contacto or None,
                celular or None,
                correo or None,
                detalles or None,
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()

    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "crear_proveedor",
        f"Proveedor creado id={new_id}, empresa={empresa}",
    )
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/proveedores/<int:id_proveedor>", methods=["PUT"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_update(id_proveedor):
    data = request.get_json(silent=True) or {}
    empresa = str(data.get("empresa", "")).strip()
    contacto = str(data.get("contacto", "")).strip()
    celular = str(data.get("celular", "")).strip()
    correo = str(data.get("correo", "")).strip()
    detalles = str(data.get("detalles", "")).strip()

    if not empresa:
        return jsonify({"ok": False, "msg": "La empresa es requerida."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
            (id_proveedor, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        cur.execute(
            "UPDATE proveedores "
            "SET nombre_empresa=%s, nombre_contacto=%s, celular=%s, correo=%s, detalles=%s "
            "WHERE id_proveedor=%s AND id_tienda=%s",
            (
                empresa,
                contacto or None,
                celular or None,
                correo or None,
                detalles or None,
                id_proveedor,
                session["id_tienda"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "editar_proveedor",
        f"Proveedor editado id={id_proveedor}, empresa={empresa}",
    )
    return jsonify({"ok": True})


@app.route("/api/proveedores/<int:id_proveedor>", methods=["DELETE"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_delete(id_proveedor):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
            (id_proveedor, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        cur.execute(
            "UPDATE productos SET id_proveedor = NULL WHERE id_proveedor=%s AND id_tienda=%s",
            (id_proveedor, session["id_tienda"]),
        )
        cur.execute(
            "DELETE FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s",
            (id_proveedor, session["id_tienda"]),
        )
        conn.commit()
    finally:
        conn.close()

    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "eliminar_proveedor",
        f"Proveedor eliminado id={id_proveedor}",
    )
    return jsonify({"ok": True})


@app.route("/api/proveedores/<int:id_proveedor>/productos", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_proveedor_productos(id_proveedor):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor, nombre_empresa "
            "FROM proveedores "
            "WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
            (id_proveedor, session["id_tienda"]),
        )
        prov = cur.fetchone()
        if not prov:
            return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        cur.execute(
            "SELECT id_producto, nombre, precio_venta, stock_actual "
            "FROM productos "
            "WHERE id_tienda=%s AND id_proveedor=%s AND estado_activo=1 "
            "ORDER BY nombre",
            (session["id_tienda"], id_proveedor),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "proveedor": {
            "id": prov["id_proveedor"],
            "empresa": prov.get("nombre_empresa") or "",
        },
        "productos": [
            {
                "id": r["id_producto"],
                "nombre": r["nombre"],
                "precio_venta": float(r.get("precio_venta") or 0),
                "stock_actual": int(r.get("stock_actual") or 0),
            }
            for r in rows
        ],
    })


@app.route("/api/inventario/categorias", methods=["GET"])
@login_required
def api_inventario_categorias():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT nombre FROM categorias "
            "WHERE id_tienda = %s AND estado_activo = 1 ORDER BY nombre",
            (session["id_tienda"],),
        )
        cats = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"ok": True, "categorias": [r["nombre"] for r in cats]})


@app.route("/api/inventario", methods=["POST"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_create():
    data = request.get_json(silent=True)
    is_json = data is not None
    data = data or {}

    fuente = data if is_json else request.form
    nombre = str(fuente.get("nombre", "")).strip()
    categoria = str(fuente.get("categoria", "")).strip()

    try:
        costo = float(fuente.get("costo", 0) or 0)
        venta = float(fuente.get("venta", 0) or 0)
        stock = float(fuente.get("stock", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Valores numericos invalidos."}), 400

    es_preparado = bool(data.get("es_preparado")) if is_json else (request.form.get("es_preparado") == "on")
    if es_preparado:
        stock = 0

    if is_json:
        ingredientes_raw = data.get("ingredientes") or []
    else:
        ids = request.form.getlist("id_insumo[]")
        cants = request.form.getlist("cantidad_insumo[]")
        ingredientes_raw = [{"id_insumo": i, "cantidad": c} for i, c in zip(ids, cants)]

    ingredientes = []
    for item in ingredientes_raw:
        try:
            id_insumo = int(item.get("id_insumo"))
            cantidad = float(item.get("cantidad"))
            if id_insumo <= 0 or cantidad <= 0:
                continue
            ingredientes.append({"id_insumo": id_insumo, "cantidad": cantidad})
        except (TypeError, ValueError, AttributeError):
            continue

    if es_preparado and not ingredientes:
        return jsonify({"ok": False, "msg": "Agrega al menos un ingrediente para la receta."}), 400

    proveedor_id = fuente.get("id_proveedor")
    try:
        proveedor_id = int(proveedor_id) if proveedor_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Proveedor invalido."}), 400

    if not nombre or not categoria:
        return jsonify({"ok": False, "msg": "Nombre y categoria son requeridos."}), 400
    if costo < 0 or venta < 0 or stock < 0:
        return jsonify({"ok": False, "msg": "Los valores no pueden ser negativos."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_categoria FROM categorias "
            "WHERE nombre = %s AND id_tienda = %s LIMIT 1",
            (categoria, session["id_tienda"]),
        )
        cat_row = cur.fetchone()
        if cat_row:
            id_cat = cat_row["id_categoria"]
        else:
            cur.execute(
                "INSERT INTO categorias (id_tienda, nombre) VALUES (%s, %s)",
                (session["id_tienda"], categoria),
            )
            id_cat = cur.lastrowid

        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, session["id_tienda"]),
            )
            if not cur.fetchone():
                return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        try:
            cur.execute(
                "INSERT INTO productos "
                "(id_tienda, id_categoria, nombre, precio_costo, precio_venta, stock_actual, id_proveedor, es_preparado) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (session["id_tienda"], id_cat, nombre, costo, venta, stock, proveedor_id, 1 if es_preparado else 0),
            )
        except Exception:
            cur.execute(
                "INSERT INTO productos "
                "(id_tienda, id_categoria, nombre, precio_costo, precio_venta, stock_actual, id_proveedor) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (session["id_tienda"], id_cat, nombre, costo, venta, stock, proveedor_id),
            )
        new_id = cur.lastrowid

        if es_preparado:
            for ing in ingredientes:
                cur.execute(
                    "INSERT INTO recetas_productos (id_producto, id_insumo, cantidad_requerida) "
                    "VALUES (%s, %s, %s)",
                    (new_id, ing["id_insumo"], ing["cantidad"]),
                )

        conn.commit()
    finally:
        conn.close()
    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "crear_producto",
        f"Producto creado id={new_id}, nombre={nombre}",
    )
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/inventario/<int:id_producto>", methods=["PUT"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_update(id_producto):
    data = request.get_json(silent=True)
    is_json = data is not None
    data = data or {}

    fuente = data if is_json else request.form
    nombre = str(fuente.get("nombre", "")).strip()
    categoria = str(fuente.get("categoria", "")).strip()

    try:
        costo = float(fuente.get("costo", 0) or 0)
        venta = float(fuente.get("venta", 0) or 0)
        stock = float(fuente.get("stock", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Valores numericos invalidos."}), 400

    es_preparado = bool(data.get("es_preparado")) if is_json else (request.form.get("es_preparado") == "on")
    if es_preparado:
        stock = 0

    if is_json:
        ingredientes_raw = data.get("ingredientes") or []
    else:
        ids = request.form.getlist("id_insumo[]")
        cants = request.form.getlist("cantidad_insumo[]")
        ingredientes_raw = [{"id_insumo": i, "cantidad": c} for i, c in zip(ids, cants)]

    ingredientes = []
    for item in ingredientes_raw:
        try:
            id_insumo = int(item.get("id_insumo"))
            cantidad = float(item.get("cantidad"))
            if id_insumo <= 0 or cantidad <= 0:
                continue
            ingredientes.append({"id_insumo": id_insumo, "cantidad": cantidad})
        except (TypeError, ValueError, AttributeError):
            continue

    if es_preparado and not ingredientes:
        return jsonify({"ok": False, "msg": "Agrega al menos un ingrediente para la receta."}), 400

    proveedor_id = fuente.get("id_proveedor")
    try:
        proveedor_id = int(proveedor_id) if proveedor_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Proveedor invalido."}), 400
    if not nombre or not categoria:
        return jsonify({"ok": False, "msg": "Nombre y categoria son requeridos."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_producto FROM productos "
            "WHERE id_producto = %s AND id_tienda = %s LIMIT 1",
            (id_producto, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Producto no encontrado."}), 404

        cur.execute(
            "SELECT id_categoria FROM categorias "
            "WHERE nombre = %s AND id_tienda = %s LIMIT 1",
            (categoria, session["id_tienda"]),
        )
        cat_row = cur.fetchone()
        if cat_row:
            id_cat = cat_row["id_categoria"]
        else:
            cur.execute(
                "INSERT INTO categorias (id_tienda, nombre) VALUES (%s, %s)",
                (session["id_tienda"], categoria),
            )
            id_cat = cur.lastrowid

        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, session["id_tienda"]),
            )
            if not cur.fetchone():
                return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        try:
            cur.execute(
                "UPDATE productos "
                "SET nombre=%s, id_categoria=%s, precio_costo=%s, precio_venta=%s, stock_actual=%s, id_proveedor=%s, es_preparado=%s "
                "WHERE id_producto=%s AND id_tienda=%s",
                (
                    nombre,
                    id_cat,
                    costo,
                    venta,
                    stock,
                    proveedor_id,
                    1 if es_preparado else 0,
                    id_producto,
                    session["id_tienda"],
                ),
            )
        except Exception:
            cur.execute(
                "UPDATE productos "
                "SET nombre=%s, id_categoria=%s, precio_costo=%s, precio_venta=%s, stock_actual=%s, id_proveedor=%s "
                "WHERE id_producto=%s AND id_tienda=%s",
                (
                    nombre,
                    id_cat,
                    costo,
                    venta,
                    stock,
                    proveedor_id,
                    id_producto,
                    session["id_tienda"],
                ),
            )

        cur.execute("DELETE FROM recetas_productos WHERE id_producto=%s", (id_producto,))
        if es_preparado:
            for ing in ingredientes:
                cur.execute(
                    "INSERT INTO recetas_productos (id_producto, id_insumo, cantidad_requerida) "
                    "VALUES (%s, %s, %s)",
                    (id_producto, ing["id_insumo"], ing["cantidad"]),
                )

        conn.commit()
    finally:
        conn.close()
    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "editar_producto",
        f"Producto editado id={id_producto}, nombre={nombre}",
    )
    return jsonify({"ok": True})


@app.route("/api/inventario/<int:id_producto>", methods=["DELETE"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_delete(id_producto):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE productos SET estado_activo = 0 "
            "WHERE id_producto = %s AND id_tienda = %s",
            (id_producto, session["id_tienda"]),
        )
        conn.commit()
    finally:
        conn.close()
    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "eliminar_producto",
        f"Producto desactivado id={id_producto}",
    )
    return jsonify({"ok": True})


@app.route("/api/inventario/<int:id_producto>/stock", methods=["POST"])
@login_required
def api_inventario_stock(id_producto):
    data = request.get_json(silent=True) or {}
    try:
        cantidad = int(data.get("cantidad", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Cantidad invalida."}), 400
    if cantidad <= 0:
        return jsonify({"ok": False, "msg": "La cantidad debe ser mayor a cero."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT id_producto, stock_actual, COALESCE(es_preparado, 0) AS es_preparado FROM productos "
                "WHERE id_producto = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
                (id_producto, session["id_tienda"]),
            )
        except Exception:
            cur.execute(
                "SELECT id_producto, stock_actual FROM productos "
                "WHERE id_producto = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
                (id_producto, session["id_tienda"]),
            )
        p = cur.fetchone()
        if not p:
            return jsonify({"ok": False, "msg": "Producto no encontrado."}), 404
        if bool(p.get("es_preparado") or 0):
            return jsonify({"ok": False, "msg": "El stock de platos preparados se calcula desde sus insumos."}), 400

        nuevo_stock = p["stock_actual"] + cantidad
        cur.execute(
            "UPDATE productos SET stock_actual = %s WHERE id_producto = %s",
            (nuevo_stock, id_producto),
        )
        cur.execute(
            "INSERT INTO movimientos_inventario "
            "(id_tienda, id_producto, id_usuario, tipo_movimiento, "
            " cantidad, stock_anterior, stock_posterior) "
            "VALUES (%s, %s, %s, 'Entrada', %s, %s, %s)",
            (session["id_tienda"], id_producto, session["id_usuario"],
             cantidad, p["stock_actual"], nuevo_stock),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "nuevo_stock": nuevo_stock})


# ─────────────────────────────────────────────────────────────
# API — Caja / Ventas
# ─────────────────────────────────────────────────────────────
@app.route("/api/caja/productos", methods=["GET"])
@login_required
def api_caja_productos():
    q = str(request.args.get("q", "")).strip()
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if q:
            cur.execute(
                "SELECT id_producto, nombre, precio_venta, stock_actual "
                "FROM productos "
                "WHERE id_tienda = %s AND estado_activo = 1 "
                "AND (nombre LIKE %s OR codigo_barras = %s) "
                "ORDER BY nombre LIMIT 20",
                (session["id_tienda"], f"%{q}%", q),
            )
        else:
            cur.execute(
                "SELECT id_producto, nombre, precio_venta, stock_actual "
                "FROM productos "
                "WHERE id_tienda = %s AND estado_activo = 1 "
                "ORDER BY nombre LIMIT 50",
                (session["id_tienda"],),
            )
        rows = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"ok": True, "productos": [
        {"id": r["id_producto"], "name": r["nombre"],
         "price": float(r["precio_venta"]), "stock": r["stock_actual"]}
        for r in rows
    ]})


@app.route("/api/ventas", methods=["POST"])
@login_required
def api_ventas_crear():
    data      = request.get_json(silent=True) or {}
    items     = data.get("items", [])
    method    = str(data.get("method", "efectivo"))
    id_cliente = data.get("id_cliente")  # optional
    try:
        subtotal = float(data.get("subtotal", 0))
        total    = float(data.get("total",    0))
        descuento = float(data.get("discount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Totales invalidos."}), 400
    if not items:
        return jsonify({"ok": False, "msg": "No hay productos en la venta."}), 400
    db_method = _normalize_payment_method(method)
    if not db_method:
        return jsonify({"ok": False, "msg": "Metodo de pago invalido."}), 400

    conn = get_db()
    stock_alerts = []
    stock_alert_keys = set()
    try:
        cur = conn.cursor(dictionary=True)
        id_turno = _turno_abierto(session["id_tienda"], cur)
        if not id_turno:
            return jsonify({"ok": False, "msg": "Abre un turno antes de registrar ventas."}), 409

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
            (session["id_tienda"],),
        )
        cnt = cur.fetchone()["cnt"]
        numero_venta = f"V{session['id_tienda']:04d}-{cnt + 1:06d}"

        cur.execute(
            "INSERT INTO ventas "
            "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
            " subtotal, total_final, metodo_pago, estado_venta) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Pagada')",
            (session["id_tienda"], id_turno, session["id_usuario"],
               id_cliente, numero_venta, subtotal, total, db_method),
        )
        id_venta = cur.lastrowid

        for item in items:
            try:
                id_prod = int(item["id"])
                qty     = float(item["qty"])
                price   = float(item["price"])
            except (KeyError, TypeError, ValueError):
                continue

            if qty <= 0:
                continue

            cur.execute(
                "INSERT INTO detalle_ventas "
                "(id_venta, id_producto, cantidad, precio_unitario_historico, subtotal_linea) "
                "VALUES (%s,%s,%s,%s,%s)",
                (id_venta, id_prod, qty, price, price * qty),
            )

            cur.execute(
                "SELECT COALESCE(es_preparado, 0) AS es_preparado "
                "FROM productos "
                "WHERE id_producto = %s AND id_tienda = %s LIMIT 1",
                (id_prod, session["id_tienda"]),
            )
            prod = cur.fetchone()
            if not prod:
                raise ValueError(f"Producto no encontrado: {id_prod}")

            if bool(prod.get("es_preparado") or 0):
                try:
                    cur.execute(
                        "SELECT id_insumo, cantidad_necesaria "
                        "FROM recetas_productos WHERE id_producto = %s",
                        (id_prod,),
                    )
                    receta_rows = cur.fetchall() or []
                except Exception:
                    cur.execute(
                        "SELECT id_insumo, cantidad_requerida AS cantidad_necesaria "
                        "FROM recetas_productos WHERE id_producto = %s",
                        (id_prod,),
                    )
                    receta_rows = cur.fetchall() or []

                for rec in receta_rows:
                    id_insumo = rec.get("id_insumo")
                    cant_necesaria = float(rec.get("cantidad_necesaria") or 0)
                    if not id_insumo or cant_necesaria <= 0:
                        continue
                    cantidad_total_insumo = qty * cant_necesaria
                    cur.execute(
                        "UPDATE insumos SET stock_actual = stock_actual - %s "
                        "WHERE id_insumo = %s AND id_tienda = %s",
                        (cantidad_total_insumo, id_insumo, session["id_tienda"]),
                    )
            else:
                cur.execute(
                    "UPDATE productos SET stock_actual = stock_actual - %s "
                    "WHERE id_producto = %s AND id_tienda = %s",
                    (qty, id_prod, session["id_tienda"]),
                )

                cur.execute(
                    "SELECT nombre, stock_actual, stock_minimo_alerta "
                    "FROM productos WHERE id_producto = %s AND id_tienda = %s LIMIT 1",
                    (id_prod, session["id_tienda"]),
                )
                p = cur.fetchone()
                if p:
                    stock_actual = int(p.get("stock_actual") or 0)
                    stock_min = int(p.get("stock_minimo_alerta") or 0)
                    if stock_min > 0 and stock_actual <= stock_min:
                        key = int(id_prod)
                        if key not in stock_alert_keys:
                            stock_alert_keys.add(key)
                            stock_alerts.append(
                                f"Stock bajo: {p.get('nombre') or 'Producto'} ({stock_actual} und)."
                            )

        if db_method == "Efectivo":
            cur.execute(
                "UPDATE turnos_caja "
                "SET monto_final_esperado = COALESCE(monto_final_esperado, monto_inicial, 0) + %s "
                "WHERE id_turno = %s",
                (total, id_turno),
            )

        conn.commit()
        if descuento >= 20000:
            registrar_auditoria(
                session.get("id_tienda"),
                session.get("id_usuario"),
                "descuento_manual_alto",
                f"Venta {numero_venta}: descuento manual de {descuento}",
            )
        for alert_msg in stock_alerts:
            flash(alert_msg, "alerta_stock")
    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "msg": f"Error al registrar la venta: {e}"}), 500
    finally:
        conn.close()
    return jsonify({
        "ok": True,
        "id_venta": id_venta,
        "numero_venta": numero_venta,
        "stock_alerts": stock_alerts,
    })


@app.route("/ventas/detalle/<int:id_venta>", methods=["GET"])
@login_required
def ventas_detalle(id_venta: int):
    if not session.get("id_usuario"):
        return jsonify({"ok": False, "msg": "Sesion no valida."}), 401

    conn = get_db()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id_venta, numero_venta, total_final "
            "FROM ventas "
            "WHERE id_venta = %s AND id_tienda = %s "
            "LIMIT 1",
            (id_venta, session["id_tienda"]),
        )
        venta = cursor.fetchone()
        if not venta:
            return jsonify({"ok": False, "msg": "Venta no encontrada."}), 404

        cursor.execute(
            "SELECT p.nombre AS producto, dv.cantidad, dv.subtotal_linea "
            "FROM detalle_ventas dv "
            "INNER JOIN productos p ON p.id_producto = dv.id_producto "
            "INNER JOIN ventas v ON v.id_venta = dv.id_venta "
            "WHERE dv.id_venta = %s AND v.id_tienda = %s "
            "ORDER BY dv.id_detalle_venta ASC",
            (id_venta, session["id_tienda"]),
        )
        rows = cursor.fetchall() or []
    except Exception as e:
        print(f"[ventas_detalle] Error en venta {id_venta}: {e}")
        return jsonify({"ok": False, "msg": "Error consultando el detalle de la venta."}), 500
    finally:
        conn.close()

    detalles = [
        {
            "producto": r.get("producto") or "Producto",
            "cantidad": float(r.get("cantidad") or 0),
            "subtotal": float(r.get("subtotal_linea") or 0),
        }
        for r in rows
    ]
    return jsonify({
        "ok": True,
        "id_venta": venta["id_venta"],
        "numero_venta": venta.get("numero_venta") or f"V-{venta['id_venta']}",
        "items": detalles,
        "total": float(venta.get("total_final") or 0),
    })


# ─────────────────────────────────────────────────────────────
# API — Fiados
# ─────────────────────────────────────────────────────────────
@app.route("/api/fiados", methods=["GET"])
@login_required
def api_fiados_list():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT c.id_cliente, c.nombre, c.telefono,
              COALESCE((
                                SELECT SUM(
                                    GREATEST(
                                        v.total_final - COALESCE((
                                            SELECT SUM(ab.monto_abonado)
                                            FROM abonos_fiados ab
                                            WHERE ab.id_venta = v.id_venta
                                        ), 0),
                                        0
                                    )
                                )
                FROM ventas v
                WHERE v.id_cliente = c.id_cliente
                  AND v.id_tienda  = c.id_tienda
                                    AND v.estado_venta = 'Fiada/Pendiente'
              ), 0) AS deuda_total
            FROM clientes c
            WHERE c.id_tienda = %s AND c.estado_activo = 1
            ORDER BY c.nombre
            """,
            (session["id_tienda"],),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"ok": True, "clientes": [
        {
            "id":    r["id_cliente"],
            "name":  r["nombre"],
            "phone": r["telefono"] or "—",
            "debt":  max(0.0, float(r["deuda_total"] or 0)),
        }
        for r in rows
    ]})


@app.route("/api/fiados", methods=["POST"])
@login_required
def api_fiados_crear_cliente():
    data    = request.get_json(silent=True) or {}
    nombre  = str(data.get("nombre",   "")).strip()
    telefono_raw = str(data.get("telefono", "")).strip()
    telefono = re.sub(r"\D", "", telefono_raw)
    try:
        deuda_inicial = float(data.get("deuda_inicial", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "La deuda inicial es invalida."}), 400
    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre es requerido."}), 400
    if not telefono:
        return jsonify({"ok": False, "msg": "El telefono es requerido."}), 400
    if len(telefono) > 10:
        return jsonify({"ok": False, "msg": "El telefono debe tener maximo 10 digitos."}), 400
    if len(telefono) < 10:
        return jsonify({"ok": False, "msg": "El telefono debe tener 10 digitos."}), 400
    if deuda_inicial < 0:
        return jsonify({"ok": False, "msg": "La deuda inicial no puede ser negativa."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        id_turno = None
        if deuda_inicial > 0:
            id_turno = _turno_abierto(session["id_tienda"], cur)
            if not id_turno:
                return jsonify({"ok": False, "msg": "Debes abrir un turno para registrar deuda inicial."}), 409

        cur.execute(
            "INSERT INTO clientes (id_tienda, nombre, telefono) VALUES (%s, %s, %s)",
            (session["id_tienda"], nombre, telefono or None),
        )
        new_id = cur.lastrowid

        if deuda_inicial > 0:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
                (session["id_tienda"],),
            )
            cnt = cur.fetchone()["cnt"]
            numero_venta = f"F{session['id_tienda']:04d}-{cnt + 1:06d}"

            cur.execute(
                "INSERT INTO ventas "
                "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
                " subtotal, total_final, metodo_pago, estado_venta, observaciones) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'Efectivo','Fiada/Pendiente',%s)",
                (
                    session["id_tienda"], id_turno, session["id_usuario"],
                    new_id, numero_venta, deuda_inicial, deuda_inicial, "Saldo inicial",
                ),
            )

        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/fiados/<int:id_cliente>/sumar", methods=["POST"])
@login_required
def api_fiados_sumar(id_cliente):
    data = request.get_json(silent=True) or {}
    try:
        monto = float(data.get("monto", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400
    if monto <= 0:
        return jsonify({"ok": False, "msg": "El monto debe ser mayor a cero."}), 400
    concepto = str(data.get("concepto", "Fiado")).strip() or "Fiado"

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_cliente FROM clientes "
            "WHERE id_cliente = %s AND id_tienda = %s LIMIT 1",
            (id_cliente, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Cliente no encontrado."}), 404

        id_turno = _turno_abierto(session["id_tienda"], cur)
        if not id_turno:
            return jsonify({"ok": False, "msg": "No hay turno abierto."}), 409

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
            (session["id_tienda"],),
        )
        cnt = cur.fetchone()["cnt"]
        numero_venta = f"F{session['id_tienda']:04d}-{cnt + 1:06d}"

        cur.execute(
            "INSERT INTO ventas "
            "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
              " subtotal, total_final, metodo_pago, estado_venta, observaciones) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,'Efectivo','Fiada/Pendiente',%s)",
            (session["id_tienda"], id_turno, session["id_usuario"],
               id_cliente, numero_venta, monto, monto, concepto),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@app.route("/api/fiados/<int:id_cliente>/abonar", methods=["POST"])
@login_required
def api_fiados_abonar(id_cliente):
    data = request.get_json(silent=True) or {}
    try:
        monto = float(data.get("monto", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400
    if monto <= 0:
        return jsonify({"ok": False, "msg": "El monto debe ser mayor a cero."}), 400
    metodo = _normalize_payment_method(data.get("metodo", "efectivo"))
    if not metodo:
        return jsonify({"ok": False, "msg": "Metodo invalido."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_cliente FROM clientes "
            "WHERE id_cliente = %s AND id_tienda = %s LIMIT 1",
            (id_cliente, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Cliente no encontrado."}), 404

        # Venta fiado mas antigua pendiente para este cliente
        cur.execute(
            "SELECT v.id_venta, v.total_final, "
            "COALESCE((SELECT SUM(ab.monto_abonado) FROM abonos_fiados ab "
            "          WHERE ab.id_venta = v.id_venta), 0) AS abonado "
            "FROM ventas v "
            "WHERE v.id_cliente = %s AND v.id_tienda = %s "
            "  AND v.estado_venta = 'Fiada/Pendiente' "
            "ORDER BY v.id_venta ASC LIMIT 1",
            (id_cliente, session["id_tienda"]),
        )
        venta = cur.fetchone()
        if not venta:
            return jsonify({"ok": False, "msg": "Este cliente no tiene deuda pendiente."}), 404

        deuda_actual = max(
            0.0,
            float(venta.get("total_final") or 0) - float(venta.get("abonado") or 0),
        )
        if monto <= 0 or monto > deuda_actual:
            return jsonify({
                "ok": False,
                "error": "El monto debe ser mayor a 0 y no puede superar la deuda actual.",
            }), 400

        cur.execute(
            "INSERT INTO abonos_fiados "
            "(id_tienda, id_venta, id_usuario, monto_abonado, metodo_pago) "
            "VALUES (%s,%s,%s,%s,%s)",
            (session["id_tienda"], venta["id_venta"],
             session["id_usuario"], monto, metodo),
        )
        # Marcar venta como completada si ya esta saldada
        if float(venta["abonado"]) + monto >= float(venta["total_final"]):
            cur.execute(
                "UPDATE ventas SET estado_venta = 'Pagada' WHERE id_venta = %s",
                (venta["id_venta"],),
            )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# API — Gastos
# ─────────────────────────────────────────────────────────────
@app.route("/api/gastos", methods=["GET"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_gastos_list():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT gc.id_gasto, gc.concepto, gc.descripcion, gc.monto, gc.fuente_dinero, "
            "UNIX_TIMESTAMP(gc.fecha_creacion) * 1000 AS ts "
            "FROM gastos_caja gc "
            "WHERE gc.id_tienda = %s AND gc.id_usuario = %s "
            "ORDER BY gc.id_gasto DESC LIMIT 100",
            (session["id_tienda"], session["id_usuario"]),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return jsonify({"ok": True, "gastos": [
        {
            "id":       r["id_gasto"],
            "category": r["concepto"],
            "desc":     str(r.get("descripcion") or "").strip(),
            "origen":   (r.get("fuente_dinero") or "Bancos"),
            "amount":   float(r["monto"]),
            "ts":       int(r["ts"] or 0),
        }
        for r in rows
    ]})


@app.route("/api/gastos", methods=["POST"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_gastos_crear():
    data    = request.get_json(silent=True) or {}
    concepto = str(data.get("category", "")).strip()
    desc     = str(data.get("desc",     "")).strip()
    metodo_pago = str(data.get("metodo_pago", "Efectivo")).strip()
    fuente_dinero = str(data.get("fuente_dinero", "")).strip()
    try:
        monto = float(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400
    if monto <= 0:
        return jsonify({"ok": False, "msg": "El monto debe ser mayor a cero."}), 400
    if not concepto:
        return jsonify({"ok": False, "msg": "La categoria es requerida."}), 400
    if metodo_pago not in {"Efectivo", "Bancos"}:
        return jsonify({"ok": False, "msg": "Metodo de pago invalido."}), 400

    if metodo_pago == "Efectivo":
        if fuente_dinero not in {"Caja Menor", "Caja Fuerte"}:
            return jsonify({"ok": False, "msg": "Fuente de dinero invalida para efectivo."}), 400
    else:
        fuente_dinero = "Bancos"

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        id_turno = _turno_abierto(session["id_tienda"], cur)

        if metodo_pago == "Efectivo" and fuente_dinero == "Caja Menor" and not id_turno:
            return jsonify({"ok": False, "msg": "No hay turno activo para cargar gastos de Caja Menor."}), 409

        if not id_turno:
            cur.execute(
                "SELECT id_turno FROM turnos_caja "
                "WHERE id_tienda = %s "
                "ORDER BY fecha_apertura DESC LIMIT 1",
                (session["id_tienda"],),
            )
            turno_row = cur.fetchone()
            if not turno_row:
                return jsonify({"ok": False, "msg": "No existe ningun turno para registrar el gasto."}), 409
            id_turno = turno_row["id_turno"]

        cur.execute(
            "INSERT INTO gastos_caja "
            "(id_tienda, id_turno, id_usuario, concepto, descripcion, monto, fuente_dinero) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (session["id_tienda"], id_turno, session["id_usuario"],
               concepto, desc, monto, fuente_dinero),
        )

        if metodo_pago == "Efectivo" and fuente_dinero == "Caja Menor":
            cur.execute(
                "UPDATE turnos_caja "
                "SET monto_final_esperado = COALESCE(monto_final_esperado, monto_inicial, 0) - %s "
                "WHERE id_turno = %s AND id_tienda = %s",
                (monto, id_turno, session["id_tienda"]),
            )

        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()
    registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "registrar_gasto",
        f"Gasto id={new_id}, categoria={concepto}, monto={monto}, fuente={fuente_dinero}",
    )
    return jsonify({"ok": True, "id": new_id})


# ─────────────────────────────────────────────────────────────
# API — Dashboard KPIs
# ─────────────────────────────────────────────────────────────
@app.route("/api/dashboard", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_dashboard():
    filtro = request.args.get("filtro") or request.args.get("period") or "hoy"
    data = _build_dashboard_data(session["id_tienda"], filtro)

    return jsonify({
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
    })


# ─────────────────────────────────────────────────────────────
# API — Perfil
# ─────────────────────────────────────────────────────────────
@app.route("/api/perfil", methods=["GET"])
@login_required
@roles_required("Admin")
def api_perfil_get():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT u.nombre_completo, u.correo, u.rol, u.foto_perfil, u.telefono, "
                "t.nombre_negocio "
                "FROM usuarios u "
                "LEFT JOIN tiendas t ON t.id_tienda = u.id_tienda "
                "WHERE u.id_usuario = %s LIMIT 1",
                (session["id_usuario"],),
            )
        except Exception:
            cur.execute(
                "SELECT u.nombre_completo, u.correo, u.rol, u.foto_perfil, "
                "t.nombre_negocio "
                "FROM usuarios u "
                "LEFT JOIN tiendas t ON t.id_tienda = u.id_tienda "
                "WHERE u.id_usuario = %s LIMIT 1",
                (session["id_usuario"],),
            )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({"ok": False, "msg": "Usuario no encontrado."}), 404
    foto_url = None
    if row.get("foto_perfil"):
        foto_url = f'/static/uploads/perfiles/{row["foto_perfil"]}'
    return jsonify({"ok": True, "perfil": {
        "nombre_completo": row["nombre_completo"],
        "correo":          row["correo"],
        "rol":             row["rol"],
        "nombre_negocio":  row["nombre_negocio"] or "",
        "telefono":        (row.get("telefono") or ""),
        "foto_url":        foto_url,
    }})


@app.route("/api/perfil", methods=["PUT"])
@login_required
@roles_required("Admin")
def api_perfil_update():
    data    = request.get_json(silent=True) or {}
    nombre  = str(data.get("nombre_completo", "")).strip()
    negocio = str(data.get("nombre_negocio",  "")).strip()
    telefono_raw = str(data.get("telefono", "")).strip()
    telefono = re.sub(r"\D", "", telefono_raw)[:10] or None
    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre no puede estar vacio."}), 400
    if telefono and len(telefono) < 7:
        return jsonify({"ok": False, "msg": "Telefono invalido."}), 400
    conn = get_db()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE usuarios SET nombre_completo = %s, telefono = %s WHERE id_usuario = %s",
                (nombre, telefono, session["id_usuario"]),
            )
        except Exception:
            cur.execute(
                "UPDATE usuarios SET nombre_completo = %s WHERE id_usuario = %s",
                (nombre, session["id_usuario"]),
            )
        if negocio:
            cur.execute(
                "UPDATE tiendas SET nombre_negocio = %s WHERE id_tienda = %s",
                (negocio, session["id_tienda"]),
            )
        conn.commit()
    finally:
        conn.close()
    session["nombre_completo"] = nombre
    return jsonify({"ok": True, "msg": "Perfil actualizado."})


# ─────────────────────────────────────────────────────────────
# API — Foto de perfil
# ─────────────────────────────────────────────────────────────
@app.route("/api/perfil/foto", methods=["POST"])
@login_required
@roles_required("Admin")
def api_perfil_foto():
    if 'foto' not in request.files:
        return jsonify({"ok": False, "msg": "No se recibio archivo."}), 400
    f = request.files['foto']
    if not f.filename:
        return jsonify({"ok": False, "msg": "Nombre de archivo invalido."}), 400

    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in {'jpg', 'jpeg', 'png'}:
        return jsonify({"ok": False, "msg": "Solo se permiten JPG o PNG."}), 400

    content = f.read()
    if len(content) > 5 * 1024 * 1024:
        return jsonify({"ok": False, "msg": "El archivo supera los 5 MB."}), 400

    # Procesar imagen con Pillow
    try:
        img = Image.open(BytesIO(content))
        img = img.convert('RGB')
        img.thumbnail((500, 500))
    except Exception:
        return jsonify({"ok": False, "msg": "Imagen invalida o corrupta."}), 400

    id_usuario = session['id_usuario']

    # Eliminar foto anterior usando el registro en la BD
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

    if old_row and old_row.get('foto_perfil'):
        old_path = os.path.join(_UPLOAD_DIR, old_row['foto_perfil'])
        if os.path.exists(old_path):
            os.remove(old_path)

    # Guardar imagen procesada con nombre UUID
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.jpg"
    save_path = os.path.join(_UPLOAD_DIR, filename)
    img.save(save_path, format='JPEG', quality=85, optimize=True)

    # Actualizar BD y sesion
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

    session['foto_perfil'] = filename
    return jsonify({"ok": True, "url": f'/static/uploads/perfiles/{filename}'})


@app.route("/api/perfil/foto", methods=["DELETE"])
@login_required
@roles_required("Admin")
def api_perfil_foto_delete():
    """Elimina la foto de perfil del usuario actual."""
    id_usuario = session['id_usuario']
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT foto_perfil FROM usuarios WHERE id_usuario = %s LIMIT 1",
            (id_usuario,),
        )
        row = cur.fetchone()
        if row and row.get('foto_perfil'):
            old_path = os.path.join(_UPLOAD_DIR, row['foto_perfil'])
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
    session['foto_perfil'] = None
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# Arranque
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
