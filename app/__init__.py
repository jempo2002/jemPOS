from __future__ import annotations

import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from flask_wtf.csrf import CSRFProtect

from database import init_pool_from_app
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import avatar_iniciales

csrf = CSRFProtect()
server_session = Session()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
)

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


def create_app() -> Flask:
    """Application factory for the new scalable structure.

    Note: legacy routes remain in app.py for now and will be migrated
    to app/routes in a later phase.
    """
    load_dotenv()

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, "templates"),
        static_folder=os.path.join(project_root, "static"),
    )

    app.config.update(
        SECRET_KEY=_required_env("SECRET_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=45),
        SESSION_TYPE=_required_env("SESSION_TYPE"),
        SESSION_PERMANENT=False,
        SESSION_USE_SIGNER=True,
        DB_HOST=_required_env("DB_HOST"),
        DB_PORT=_required_int_env("DB_PORT"),
        DB_USER=_required_env("DB_USER"),
        DB_PASSWORD=_required_env("DB_PASSWORD", allow_empty=True),
        DB_NAME=_required_env("DB_NAME"),
    )

    csrf.init_app(app)
    server_session.init_app(app)
    limiter.init_app(app)
    init_pool_from_app(app)

    from app.routes.auth import auth
    from app.routes.core import core_bp
    from app.routes.inventory import inventory_api_bp, inventory_bp
    from app.routes.sales import sales_api_bp, sales_bp

    app.register_blueprint(auth)
    app.register_blueprint(core_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(inventory_api_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(sales_api_bp)

    @app.get("/")
    def index():
        # La raíz siempre dirige a la landing pública; desde ahí el
        # usuario decide iniciar sesión o crear cuenta.
        return redirect(url_for("landing"))

    @app.get("/landing")
    def landing():
        return render_template("landing.html")

    @app.get("/health")
    def health() -> tuple[dict, int]:
        return {"ok": True, "app": "jemPOS", "mode": "factory-ready"}, 200

    @app.errorhandler(429)
    def rate_limit_exceeded(_err):
        return (
            jsonify(
                {
                    "ok": False,
                    "msg": "Demasiadas solicitudes. Espera un momento e intenta de nuevo.",
                }
            ),
            429,
        )

    return app
