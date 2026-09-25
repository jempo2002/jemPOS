from __future__ import annotations

import hmac
import re

import mysql.connector
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired
from werkzeug.security import check_password_hash, generate_password_hash

from app import limiter
from app.security import cerrar_sesion_publica
from app.services.auth_service import (
    create_reset_token,
    decode_reset_token,
    first_password_policy_error,
    huella_clave,
    initialize_user_session,
    is_valid_email,
    liberar_datos_inactivos,
    resolve_post_login_redirect,
    send_recovery_email,
)
from app.utils.decorators import log_seguridad, login_required
from app.utils.validation import sanitize_optional_text, sanitize_text
from database import get_db

auth = Blueprint("auth", __name__)
LOGIN_RATE_LIMIT = "5 per minute"
# Por cuenta, no por IP: frena la fuerza bruta distribuida contra un correo.
LOGIN_CUENTA_RATE_LIMIT = "10 per 15 minutes"
# Hash valido para comparar cuando el correo no existe: iguala el tiempo de
# respuesta y no delata que cuentas existen.
_HASH_SENUELO = generate_password_hash("jempos-senuelo")
_CREDENCIALES_INVALIDAS = "Correo o contrasena incorrectos."


def _correo_login() -> str:
    data = request.get_json(silent=True) if request.is_json else request.form
    return "login:" + str((data or {}).get("correo", "")).strip().lower()[:150]


@auth.route("/login", methods=["GET", "POST"])
@limiter.limit(LOGIN_RATE_LIMIT, methods=["POST"])
@limiter.limit(LOGIN_CUENTA_RATE_LIMIT, methods=["POST"], key_func=_correo_login)
def login():
    if request.method == "GET":
        # Ruta publica: abrir el login destruye cualquier sesion activa en vez
        # de reenviar al dashboard. Quien llega aqui quiere autenticarse, y
        # dejar la sesion anterior viva permitia seguir usandola con el boton
        # "atras". El POST de abajo crea la sesion nueva desde cero.
        # Se usa el helper para no borrar los flashes que trae el redirect.
        cerrar_sesion_publica()
        return render_template("auth/login.html")

    data = request.get_json(silent=True) if request.is_json else request.form
    correo = str((data or {}).get("correo", "")).strip().lower()
    contrasena = str((data or {}).get("contrasena", ""))

    if not correo or not contrasena:
        if request.is_json:
            return jsonify({"ok": False, "msg": "Correo y contrasena son requeridos."}), 400
        flash("Correo y contrasena son requeridos.", "error")
        return redirect(url_for("auth.login"))
    if len(correo) > 150 or not is_valid_email(correo):
        if request.is_json:
            return jsonify({"ok": False, "msg": "Correo invalido."}), 400
        flash("Correo invalido.", "error")
        return redirect(url_for("auth.login"))
    if len(contrasena) > 128:
        if request.is_json:
            return jsonify({"ok": False, "msg": "La contrasena supera el maximo permitido."}), 400
        flash("La contrasena supera el maximo permitido.", "error")
        return redirect(url_for("auth.login"))

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT u.id_usuario, u.id_tienda, u.nombre_completo, u.clave_hash, u.rol, "
            "u.estado_activo, COALESCE(t.es_restaurante, 0) AS es_restaurante "
            "FROM usuarios u "
            "LEFT JOIN tiendas t ON t.id_tienda = u.id_tienda "
            "WHERE u.correo = %s LIMIT 1",
            (correo,),
        )
        user = cur.fetchone()
    finally:
        conn.close()

    # Mismo mensaje y mismo coste de hash exista o no el correo.
    clave_ok = check_password_hash(user["clave_hash"] if user else _HASH_SENUELO, contrasena)
    if not user or not clave_ok:
        log_seguridad("login_fallido", correo=correo, existe=bool(user))
        if request.is_json:
            return jsonify({"ok": False, "field": "contrasena", "msg": _CREDENCIALES_INVALIDAS}), 401
        flash(_CREDENCIALES_INVALIDAS, "error")
        return redirect(url_for("auth.login"))

    if not user["estado_activo"]:
        if request.is_json:
            return jsonify({"ok": False, "msg": "Cuenta desactivada. Contacta al administrador."}), 403
        flash("Cuenta desactivada. Contacta al administrador.", "error")
        return redirect(url_for("auth.login"))

    initialize_user_session(session, user)
    # ID de sesion nuevo al autenticarse: anula una fijacion de sesion previa.
    # (Solo Flask-Session lo tiene; el app.py heredado usa cookie firmada.)
    if hasattr(current_app.session_interface, "regenerate"):
        current_app.session_interface.regenerate(session)
    # Admin must always land on dashboard after login.
    if str(user.get("rol") or "").strip().lower() == "admin":
        redirect_url = "/dashboard"
    else:
        redirect_url = resolve_post_login_redirect(user["rol"])

    if request.is_json:
        return jsonify({"ok": True, "redirect": redirect_url})
    return redirect(redirect_url)


@auth.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth.route("/api/auth/login", methods=["POST"])
@limiter.limit(LOGIN_RATE_LIMIT)
def api_login():
    return login()


@auth.route("/api/auth/logout", methods=["POST"])
@login_required
def api_logout():
    session.clear()
    return jsonify({"ok": True, "redirect": "/login"})


@auth.route("/registro", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def registro():
    if request.method == "GET":
        return render_template("auth/registro.html")

    try:
        nombre_dueno = sanitize_text(request.form.get("nombre_dueno"), "Nombre del dueno", max_len=150)
        nombre_negocio = sanitize_text(request.form.get("nombre_negocio"), "Nombre del negocio", max_len=150)
        nit = sanitize_optional_text(request.form.get("nit"), "NIT", max_len=30)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.registro"))

    telefono_raw = re.sub(r"\D", "", str(request.form.get("telefono", "")).strip())
    if telefono_raw and len(telefono_raw) > 25:
        flash("El telefono no puede superar 25 digitos.", "error")
        return redirect(url_for("auth.registro"))
    telefono = telefono_raw or None
    correo = str(request.form.get("correo", "")).strip().lower()
    contrasena = str(request.form.get("contrasena", ""))
    acepta_terminos = bool(request.form.get("acepta_terminos"))

    if not nombre_dueno or not nombre_negocio:
        flash("Nombre del dueno y nombre del negocio son requeridos.", "error")
        return redirect(url_for("auth.registro"))
    if not correo or len(correo) > 150 or not is_valid_email(correo):
        flash("Debes ingresar un correo valido.", "error")
        return redirect(url_for("auth.registro"))
    if len(contrasena) > 128:
        flash("La contrasena supera el maximo permitido.", "error")
        return redirect(url_for("auth.registro"))
    pwd_error = first_password_policy_error(contrasena)
    if pwd_error:
        flash(pwd_error, "error")
        return redirect(url_for("auth.registro"))
    if not acepta_terminos:
        flash("Debes aceptar terminos y condiciones.", "error")
        return redirect(url_for("auth.registro"))

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        liberar_datos_inactivos(cur, correo, nit)
        cur.execute("SELECT id_usuario FROM usuarios WHERE correo = %s LIMIT 1", (correo,))
        if cur.fetchone():
            flash("Ya existe una cuenta con ese correo.", "error")
            return redirect(url_for("auth.registro"))

        cur.execute(
            "INSERT INTO tiendas (nombre_negocio, nit, telefono, estado_suscripcion) VALUES (%s, %s, %s, 'activa')",
            (nombre_negocio, nit, telefono),
        )
        id_tienda = cur.lastrowid

        cur.execute(
            "INSERT INTO usuarios (id_tienda, nombre_completo, correo, clave_hash, rol, cc) "
            "VALUES (%s, %s, %s, %s, 'Admin', %s)",
            (id_tienda, nombre_dueno, correo, generate_password_hash(contrasena), nit),
        )
        conn.commit()
    except mysql.connector.IntegrityError:
        conn.rollback()
        flash("No fue posible completar el registro. Verifica la informacion.", "error")
        return redirect(url_for("auth.registro"))
    finally:
        conn.close()

    flash("Cuenta creada exitosamente. Ya puedes iniciar sesion.", "success")
    return redirect(url_for("auth.login"))


@auth.route("/olvide_password", methods=["GET", "POST"])
@auth.route("/olvide-password", methods=["GET", "POST"])
@limiter.limit("3 per minute; 10 per hour", methods=["POST"])
def olvide_password():
    if request.method == "POST":
        correo = str(request.form.get("correo", "")).strip().lower()
        if correo:
            if len(correo) > 150 or not is_valid_email(correo):
                flash("Debes ingresar un correo valido.", "error")
                return redirect(url_for("auth.olvide_password"))
            conn = get_db()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT correo, clave_hash FROM usuarios WHERE correo = %s AND estado_activo = 1 LIMIT 1",
                    (correo,),
                )
                user = cur.fetchone()
            finally:
                conn.close()

            if user:
                token = create_reset_token(current_app.secret_key, correo, user["clave_hash"])
                enlace = url_for("auth.reset_password", token=token, _external=True)
                # Fire-and-forget: mail is dispatched in background and failures are logged.
                send_recovery_email(correo, enlace)

        flash("Si el correo existe, recibiras un enlace de recuperacion.", "success")
        return redirect(url_for("auth.olvide_password"))

    return render_template("auth/olvide_password.html")


@auth.route("/reset_password/<token>", methods=["GET", "POST"])
@auth.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def reset_password(token):
    try:
        correo, huella = decode_reset_token(current_app.secret_key, token)
    except (SignatureExpired, BadSignature):
        flash("Enlace inválido o expirado", "error")
        return redirect(url_for("auth.login"))

    if not correo:
        flash("Enlace inválido o expirado", "error")
        return redirect(url_for("auth.login"))

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_usuario, correo, estado_activo, clave_hash FROM usuarios WHERE correo = %s LIMIT 1",
            (correo,),
        )
        user = cur.fetchone()
    finally:
        conn.close()

    if (
        not user
        or not user.get("estado_activo")
        or not hmac.compare_digest(huella, huella_clave(user["clave_hash"]))
    ):
        flash("Enlace inválido o expirado", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = str(request.form.get("password", ""))
        confirm = str(request.form.get("confirm_password", ""))

        if password != confirm:
            flash("Las contrasenas no coinciden.", "error")
            return redirect(url_for("auth.reset_password", token=token))
        if len(password) > 128:
            flash("La contrasena supera el maximo permitido.", "error")
            return redirect(url_for("auth.reset_password", token=token))
        pwd_error = first_password_policy_error(password)
        if pwd_error:
            flash(pwd_error, "error")
            return redirect(url_for("auth.reset_password", token=token))

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE usuarios SET clave_hash = %s WHERE id_usuario = %s AND correo = %s",
                (generate_password_hash(password), user["id_usuario"], user["correo"]),
            )
            conn.commit()
        finally:
            conn.close()

        flash("Tu contrasena fue actualizada correctamente.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)
