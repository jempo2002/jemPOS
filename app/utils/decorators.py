from __future__ import annotations

from datetime import date
from functools import wraps

from flask import current_app, flash, jsonify, redirect, request, session, url_for

from database import get_db


def _is_api_request() -> bool:
    path = request.path or ""
    if request.is_json:
        return True
    if path.startswith("/api") or "/api/" in path:
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.accept_mimetypes
    if accept and accept.best == "application/json":
        return True
    return False


def log_seguridad(evento: str, **datos) -> None:
    """Una linea WARNING por evento sospechoso, con quien y desde donde."""
    extra = " ".join(f"{k}={v!r}" for k, v in datos.items())
    current_app.logger.warning(
        "SEGURIDAD %s ip=%s usuario=%s tienda=%s ruta=%s %s",
        evento, request.remote_addr, session.get("id_usuario"),
        session.get("id_tienda"), request.path, extra,
    )


def _usuario_vigente(user_id) -> dict | None:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT u.rol, u.id_tienda, u.estado_activo, t.fecha_fin_suscripcion "
            "FROM usuarios u LEFT JOIN tiendas t ON t.id_tienda = u.id_tienda "
            "WHERE u.id_usuario = %s LIMIT 1",
            (user_id,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def login_required(f):
    """Require an authenticated session for HTML and API endpoints.

    La sesion se contrasta con la base en cada peticion: un usuario eliminado,
    desactivado o movido de tienda pierde el acceso al instante (antes seguia
    dentro hasta que caducara la cookie), un cambio de rol aplica sin volver a
    entrar, y una suscripcion vencida bloquea tambien las APIs, no solo el
    dashboard. ponytail: 1 SELECT por PK por peticion; cachear si pesa.
    """
    @wraps(f)
    def _inner(*args, **kwargs):
        user_id = session.get("id_usuario")
        role = session.get("rol")
        fila = _usuario_vigente(user_id) if user_id and role else None
        if (
            not fila
            or not fila["estado_activo"]
            or fila["id_tienda"] != session.get("id_tienda")
        ):
            if user_id:
                log_seguridad("sesion_revocada")
            session.clear()
            if _is_api_request():
                return jsonify({"ok": False, "msg": "Sesion expirada."}), 401
            return redirect(url_for("auth.login"))
        session["rol"] = fila["rol"]

        vence = fila["fecha_fin_suscripcion"]
        if (
            fila["rol"] != "Master"
            and vence is not None
            and vence <= date.today()
            and request.endpoint != "core_bp.servicio_suspendido"
        ):
            if _is_api_request():
                return jsonify({"ok": False, "msg": "Suscripcion vencida."}), 402
            return redirect(url_for("core_bp.servicio_suspendido"))
        return f(*args, **kwargs)

    return _inner


def roles_required(*roles: str):
    """Allow access only to the given roles, using normalized comparisons."""
    allowed_roles = {
        str(role).strip().lower()
        for role in roles
        if isinstance(role, str) and role.strip()
    }
    if not allowed_roles:
        raise ValueError("roles_required necesita al menos un rol valido.")

    def decorator(f):
        @wraps(f)
        def _inner(*args, **kwargs):
            current_role = str(session.get("rol") or "").strip().lower()
            if current_role not in allowed_roles:
                log_seguridad("rol_denegado", requerido=sorted(allowed_roles))
                if _is_api_request():
                    return jsonify({"ok": False, "msg": "No tienes permisos para esta accion."}), 403
                flash("No tienes permisos para ver esta pantalla.", "error")
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)

        return _inner

    return decorator
