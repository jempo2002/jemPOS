"""Rutas legales publicas: aviso legal y politica de privacidad.

Son publicas a proposito (sin login_required): el aviso de cookies enlaza a la
politica, y un visitante tiene que poder leerla antes de registrarse.

Igual que la landing, destruyen la sesion activa: son rutas publicas y aplican
la misma regla que /, /landing y /login.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from app.security import cerrar_sesion_publica

legal_bp = Blueprint("legal_bp", __name__, url_prefix="/legal")


@legal_bp.get("/aviso-legal")
def aviso_legal():
    cerrar_sesion_publica()
    return render_template("legal/aviso_legal.html")


@legal_bp.get("/politica-privacidad")
def politica_privacidad():
    cerrar_sesion_publica()
    return render_template("legal/politica_privacidad.html")
