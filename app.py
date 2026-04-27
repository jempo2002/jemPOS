"""app.py — bootstrap minimo de jemPOS."""

from __future__ import annotations

import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, session, url_for
from flask_wtf.csrf import CSRFProtect

from app import limiter
from app.routes.auth import auth
from app.routes.core import core_bp
from app.routes.inventory import inventory_api_bp, inventory_bp
from app.routes.sales import sales_api_bp, sales_bp
from database import init_pool

load_dotenv()

def _required_env(name: str, allow_empty: bool = False) -> str:
    value = os.getenv(name)
    if value is None or (not allow_empty and value.strip() == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _required_int_env(name: str) -> int:
    raw = _required_env(name)
    if not raw.strip().isdigit():
        raise RuntimeError(f"Invalid integer for environment variable: {name}")
    return int(raw)


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_required_env("SECRET_KEY"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=45),
    DB_HOST=_required_env("DB_HOST"),
    DB_PORT=_required_int_env("DB_PORT"),
    DB_USER=_required_env("DB_USER"),
    DB_PASSWORD=_required_env("DB_PASSWORD", allow_empty=True),
    DB_NAME=_required_env("DB_NAME"),
)

csrf = CSRFProtect(app)
limiter.init_app(app)

app.register_blueprint(auth)
app.register_blueprint(core_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(inventory_api_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(sales_api_bp)

with app.app_context():
    init_pool(
        host=app.config["DB_HOST"],
        port=app.config["DB_PORT"],
        user=app.config["DB_USER"],
        password=app.config["DB_PASSWORD"],
        database=app.config["DB_NAME"],
    )


@app.route("/")
def index():
    if "id_usuario" not in session:
        return redirect(url_for("auth.login"))

    rol = (session.get("rol") or "").strip()
    if rol in {"Admin", "Master"}:
        return redirect(url_for("core_bp.dashboard_page"))
    return redirect(url_for("sales_bp.turno"))


@app.errorhandler(404)
def not_found(_err):
    return jsonify({"ok": False, "msg": "Ruta no encontrada."}), 404


@app.errorhandler(500)
def server_error(_err):
    return jsonify({"ok": False, "msg": "Error interno del servidor."}), 500


@app.errorhandler(429)
def rate_limit_exceeded(_err):
    return (
        jsonify(
            {"ok": False, "msg": "Demasiadas solicitudes. Espera un momento e intenta de nuevo."}
        ),
        429,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
