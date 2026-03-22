from __future__ import annotations

import os
import re
import smtplib
from email.mime.text import MIMEText

from itsdangerous import URLSafeTimedSerializer

from database import get_db

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PWD_UPPER_RE = re.compile(r"[A-Z]")
_PWD_LOWER_RE = re.compile(r"[a-z]")
_PWD_NUMBER_RE = re.compile(r"\d")


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(str(email or "").strip().lower()))


def first_password_policy_error(password: str) -> str | None:
    raw = str(password or "")
    if not raw:
        return "La contrasena es requerida."
    if len(raw) < 8:
        return "La contrasena debe tener al menos 8 caracteres."
    if not _PWD_UPPER_RE.search(raw):
        return "La contrasena debe incluir al menos una letra mayuscula."
    if not _PWD_LOWER_RE.search(raw):
        return "La contrasena debe incluir al menos una letra minuscula."
    if not _PWD_NUMBER_RE.search(raw):
        return "La contrasena debe incluir al menos un numero."
    return None


def initialize_user_session(session_obj, user: dict) -> None:
    session_obj.clear()
    session_obj.permanent = True
    session_obj["id_usuario"] = user["id_usuario"]
    session_obj["id_tienda"] = user["id_tienda"]
    session_obj["nombre_completo"] = user["nombre_completo"]
    session_obj["rol"] = user["rol"]
    session_obj["foto_perfil"] = user.get("foto_perfil") or None
    session_obj["es_restaurante"] = bool(user.get("es_restaurante"))


def resolve_post_login_redirect(rol: str, id_tienda: int | None) -> str:
    role = str(rol or "").strip().lower()
    if role == "master":
        return "/panel-master"
    if role == "admin":
        return "/dashboard"
    if role == "cajero":
        return "/pos/caja"
    return "/pos/turno"


def create_reset_token(secret_key: str, email: str, salt: str = "password-reset-salt") -> str:
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.dumps(email, salt=salt)


def decode_reset_token(
    secret_key: str,
    token: str,
    salt: str = "password-reset-salt",
    max_age: int = 900,
) -> str:
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.loads(token, salt=salt, max_age=max_age)


def send_recovery_email(destinatario: str, enlace: str) -> bool:
    sender = os.environ.get("EMAIL_SENDER", "")
    password = os.environ.get("EMAIL_PASSWORD", "")
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", 587))

    if not sender or not password:
        return False

    cuerpo = (
        "Hola,\n\n"
        "Recibimos una solicitud para restablecer tu contrasena en jemPOS.\n"
        "Haz clic en el siguiente enlace (valido por 15 minutos):\n\n"
        f"{enlace}\n\n"
        "Si no solicitaste este cambio, ignora este correo.\n"
    )
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = "Recuperacion de contrasena - jemPOS"
    msg["From"] = sender
    msg["To"] = destinatario

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(sender, password)
            smtp.sendmail(sender, [destinatario], msg.as_string())
        return True
    except Exception:
        return False


def get_profile_for_user(id_usuario: int) -> dict | None:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT u.nombre_completo, u.correo, u.rol, u.foto_perfil, t.nombre_negocio "
            "FROM usuarios u "
            "LEFT JOIN tiendas t ON t.id_tienda = u.id_tienda "
            "WHERE u.id_usuario = %s LIMIT 1",
            (id_usuario,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return None

    foto_url = None
    if row.get("foto_perfil"):
        foto_url = f"/static/uploads/perfiles/{row['foto_perfil']}"

    return {
        "nombre_completo": row["nombre_completo"],
        "correo": row["correo"],
        "rol": row["rol"],
        "nombre_negocio": row.get("nombre_negocio") or "",
        "telefono": "",
        "foto_url": foto_url,
    }


def update_profile_basic(id_usuario: int, id_tienda: int, nombre: str, negocio: str) -> None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE usuarios SET nombre_completo = %s WHERE id_usuario = %s",
            (nombre, id_usuario),
        )
        if negocio:
            cur.execute(
                "UPDATE tiendas SET nombre_negocio = %s WHERE id_tienda = %s",
                (negocio, id_tienda),
            )
        conn.commit()
    finally:
        conn.close()
