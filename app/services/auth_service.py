from __future__ import annotations

import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
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


def resolve_post_login_redirect(rol: str) -> str:
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
    return serializer.dumps(str(email or "").strip().lower(), salt=salt)


def decode_reset_token(
    secret_key: str,
    token: str,
    salt: str = "password-reset-salt",
    max_age: int = 1800,
) -> str:
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.loads(token, salt=salt, max_age=max_age)


def send_recovery_email(destinatario: str, enlace: str) -> bool:
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    smtp_host = os.getenv("EMAIL_SMTP_HOST")
    smtp_port_raw = os.getenv("EMAIL_SMTP_PORT")

    if not sender or not password or not smtp_host or not smtp_port_raw:
        return False

    smtp_port_str = smtp_port_raw.strip()
    if not smtp_port_str.isdigit():
        return False

    smtp_port = int(smtp_port_str)

    subject = "Recupera tu acceso a jemPOS"
    cuerpo_texto = (
        "Hola, recibimos una solicitud para cambiar tu contraseña en jemPOS.\n"
        "Haz clic en el enlace para continuar:\n\n"
        f"{enlace}\n\n"
        "El enlace es válido por 30 minutos.\n"
        "Si no fuiste tú, ignora este mensaje.\n"
    )
    cuerpo_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f8fafc; color: #0f172a; padding: 24px;">
        <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0;
                    border-radius: 16px; padding: 24px;">
          <h2 style="margin: 0 0 12px; color: #0f172a;">Recupera tu acceso a jemPOS</h2>
          <p style="margin: 0 0 16px; color: #475569; line-height: 1.5;">
            Hola, recibimos una solicitud para cambiar tu contraseña en jemPOS.
            Haz clic en el enlace para continuar:
          </p>
          <div style="text-align: center; margin: 24px 0;">
            <a href="{enlace}"
               style="background: #2563eb; color: #ffffff; text-decoration: none; padding: 12px 24px;
                      border-radius: 12px; display: inline-block; font-weight: 600;">
              Recuperar acceso
            </a>
          </div>
          <p style="margin: 0 0 8px; color: #475569; line-height: 1.5;">
            El enlace es válido por 30 minutos.
          </p>
          <p style="margin: 0; color: #94a3b8; font-size: 13px;">
            Si no fuiste tú, ignora este mensaje.
          </p>
        </div>
      </body>
    </html>
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = destinatario
    msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

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
