"""app.py — bootstrap minimo de jemPOS."""

from __future__ import annotations

import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, session, url_for
from flask_wtf.csrf import CSRFProtect

from app import limiter
from app.routes.auth import auth
from app.routes.cartera import cartera_api_bp, cartera_bp
from app.routes.core import core_bp
from app.routes.guias import guias_bp
from app.routes.inventory import inventory_api_bp, inventory_bp
from app.routes.legal import legal_bp
from app.routes.seo import seo_bp
from app.routes.sales import sales_api_bp, sales_bp
from app.performance import init_compresion
from app.security import cerrar_sesion_publica, init_security
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
init_security(app)
init_compresion(app)

app.register_blueprint(auth)
app.register_blueprint(core_bp)
app.register_blueprint(guias_bp)
app.register_blueprint(cartera_bp)
app.register_blueprint(cartera_api_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(inventory_api_bp)
app.register_blueprint(legal_bp)
app.register_blueprint(seo_bp)
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
    # La raíz es pública: destruye la sesión y manda a la landing. Antes
    # reenviaba al dashboard si había sesión, lo que mantenía vivas sesiones
    # que el usuario creía cerradas.
    cerrar_sesion_publica()
    return redirect(url_for("landing"))


@app.route("/landing")
def landing():
    cerrar_sesion_publica()
    return render_template("landing.html")


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
    from app.security import es_desarrollo

    app.run(debug=es_desarrollo(), host="0.0.0.0", port=5000)
