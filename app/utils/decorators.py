from __future__ import annotations

from functools import wraps

from flask import flash, jsonify, redirect, request, session, url_for


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


def login_required(f):
    """Require an authenticated session for HTML and API endpoints."""
    @wraps(f)
    def _inner(*args, **kwargs):
        user_id = session.get("id_usuario")
        role = session.get("rol")
        if not user_id or not role:
            session.clear()
            if _is_api_request():
                return jsonify({"ok": False, "msg": "Sesion expirada."}), 401
            return redirect(url_for("auth.login"))
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
                if _is_api_request():
                    return jsonify({"ok": False, "msg": "No tienes permisos para esta accion."}), 403
                flash("No tienes permisos para ver esta pantalla.", "error")
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)

        return _inner

    return decorator
