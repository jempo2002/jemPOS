from __future__ import annotations

import re

import mysql.connector
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired
from werkzeug.security import check_password_hash, generate_password_hash

from app import limiter
from app.services.auth_service import (
    create_reset_token,
    decode_reset_token,
    first_password_policy_error,
    initialize_user_session,
    is_valid_email,
    resolve_post_login_redirect,
    send_recovery_email,
)
from app.utils.decorators import login_required
from database import get_db

auth = Blueprint("auth", __name__)


@auth.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if request.method == "GET":
        if "id_usuario" in session:
            redirect_url = resolve_post_login_redirect(session.get("rol", ""), session.get("id_tienda"))
            return redirect(redirect_url)
        return render_template("auth/login.html")

    data = request.get_json(silent=True) if request.is_json else request.form
    correo = str((data or {}).get("correo", "")).strip().lower()
    contrasena = str((data or {}).get("contrasena", ""))

    if not correo or not contrasena:
        if request.is_json:
            return jsonify({"ok": False, "msg": "Correo y contrasena son requeridos."}), 400
        flash("Correo y contrasena son requeridos.", "error")
        return redirect(url_for("auth.login"))

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT u.id_usuario, u.id_tienda, u.nombre_completo, u.clave_hash, u.rol, "
            "u.estado_activo, u.foto_perfil, COALESCE(t.es_restaurante, 0) AS es_restaurante "
            "FROM usuarios u "
            "LEFT JOIN tiendas t ON t.id_tienda = u.id_tienda "
            "WHERE u.correo = %s LIMIT 1",
            (correo,),
        )
        user = cur.fetchone()
    finally:
        conn.close()

    if not user:
        if request.is_json:
            return jsonify({"ok": False, "field": "correo", "msg": "Usuario no encontrado."}), 401
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("auth.login"))

    if not check_password_hash(user["clave_hash"], contrasena):
        if request.is_json:
            return jsonify({"ok": False, "field": "contrasena", "msg": "Contrasena incorrecta."}), 401
        flash("Contrasena incorrecta.", "error")
        return redirect(url_for("auth.login"))

    if not user["estado_activo"]:
        if request.is_json:
            return jsonify({"ok": False, "msg": "Cuenta desactivada. Contacta al administrador."}), 403
        flash("Cuenta desactivada. Contacta al administrador.", "error")
        return redirect(url_for("auth.login"))

    initialize_user_session(session, user)
    redirect_url = resolve_post_login_redirect(user["rol"], user.get("id_tienda"))

    if request.is_json:
        return jsonify({"ok": True, "redirect": redirect_url})
    return redirect(redirect_url)


@auth.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth.route("/api/auth/login", methods=["POST"])
def api_login():
    return login()


@auth.route("/api/auth/logout", methods=["POST"])
@login_required
def api_logout():
    session.clear()
    return jsonify({"ok": True, "redirect": "/login"})


@auth.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "GET":
        return render_template("auth/registro.html")

    nombre_dueno = str(request.form.get("nombre_dueno", "")).strip()
    nombre_negocio = str(request.form.get("nombre_negocio", "")).strip()
    nit = str(request.form.get("nit", "")).strip() or None
    telefono = re.sub(r"\D", "", str(request.form.get("telefono", "")).strip())[:10] or None
    correo = str(request.form.get("correo", "")).strip().lower()
    contrasena = str(request.form.get("contrasena", ""))
    acepta_terminos = bool(request.form.get("acepta_terminos"))

    if not nombre_dueno or not nombre_negocio:
        flash("Nombre del dueno y nombre del negocio son requeridos.", "error")
        return redirect(url_for("auth.registro"))
    if not correo or not is_valid_email(correo):
        flash("Debes ingresar un correo valido.", "error")
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
                token = create_reset_token(current_app.secret_key, correo)
                enlace = url_for("auth.reset_password", token=token, _external=True)
                send_recovery_email(correo, enlace)

        flash("Si el correo existe, recibiras un enlace de recuperacion.", "success")
        return redirect(url_for("auth.olvide_password"))

    return render_template("auth/olvide_password.html")


@auth.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        correo = decode_reset_token(current_app.secret_key, token)
    except (SignatureExpired, BadSignature):
        flash("El enlace de recuperacion es invalido o ha expirado.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = str(request.form.get("password", ""))
        confirm = str(request.form.get("confirm_password", ""))

        if password != confirm:
            flash("Las contrasenas no coinciden.", "error")
            return redirect(url_for("auth.reset_password", token=token))
        pwd_error = first_password_policy_error(password)
        if pwd_error:
            flash(pwd_error, "error")
            return redirect(url_for("auth.reset_password", token=token))

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
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)
