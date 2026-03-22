from __future__ import annotations

from functools import wraps

from flask import flash, jsonify, redirect, request, session, url_for


def login_required(f):
    """Require an authenticated session for HTML and API endpoints."""
    @wraps(f)
    def _inner(*args, **kwargs):
        if "id_usuario" not in session:
            if request.is_json or request.path.startswith("/api/"):
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
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify({"ok": False, "msg": "No tienes permisos para esta accion."}), 403
                flash("No tienes permisos para ver esta pantalla.", "error")
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)

        return _inner

    return decorator
