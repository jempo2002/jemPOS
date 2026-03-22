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
limiter = Limiter(key_func=get_remote_address, default_limits=[])


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
        SECRET_KEY=os.environ["SECRET_KEY"],
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=45),
        SESSION_TYPE=os.environ.get("SESSION_TYPE", "filesystem"),
        SESSION_PERMANENT=False,
        SESSION_USE_SIGNER=True,
        DB_HOST=os.environ.get("DB_HOST", "127.0.0.1"),
        DB_PORT=int(os.environ.get("DB_PORT", 3306)),
        DB_USER=os.environ.get("DB_USER", "root"),
        DB_PASSWORD=os.environ.get("DB_PASSWORD", ""),
        DB_NAME=os.environ.get("DB_NAME", "jempos"),
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
        return redirect(url_for("auth.login"))

    @app.get("/health")
    def health() -> tuple[dict, int]:
        return {"ok": True, "app": "jemPOS", "mode": "factory-ready"}, 200

    return app
