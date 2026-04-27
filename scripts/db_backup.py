#!/usr/bin/env python3
"""
Daily MySQL backup for jemPOS using mysqldump.
Creates compressed file: backup_jempos_YYYYMMDD_HHMM.sql.gz
Reads DB credentials from project .env file.
Keeps only the last 7 days of backups.

Usage:
  python3 scripts/db_backup.py            # runs backup using .env from project root
  python3 scripts/db_backup.py /path/to/.env  # optional custom .env path

Requirements:
  - mysqldump must be installed and in PATH
  - Python 3.8+

This script is safe to run from cron. It writes logs to stdout/stderr.
"""

from __future__ import annotations

import gzip
import os
import smtplib
import subprocess
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, Optional


def read_env(env_path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not env_path.exists():
        raise FileNotFoundError(f".env not found at {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        data[key.strip()] = val.strip()
    return data


def find_project_root(script_path: Path) -> Path:
    # scripts/ is expected to be inside project; project root = parent of scripts/
    return script_path.resolve().parent.parent


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def send_alert_email(
    smtp_host: str,
    smtp_port: str,
    sender_email: str,
    sender_password: str,
    recipient_email: str,
    error_message: str,
    db_name: str,
) -> bool:
    """
    Send alert email when backup fails.
    Returns True if successful, False otherwise.
    """
    if not all([smtp_host, smtp_port, sender_email, sender_password, recipient_email]):
        print("Warning: Email config incomplete, skipping alert")
        return False

    try:
        # Parse port as int
        port_int = int(smtp_port)
    except ValueError:
        print(f"Warning: Invalid SMTP_PORT '{smtp_port}', skipping alert")
        return False

    subject = f"[ALERT] jemPOS Database Backup Failed - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    
    # Plain text body
    body_text = f"""
Dear Administrator,

The automated backup for database '{db_name}' FAILED at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC.

ERROR DETAILS:
{error_message}

ACTION REQUIRED:
Please investigate immediately and verify your database backups manually.
Contact your DevOps team if this is a recurring issue.

---
jemPOS Automated Backup System
"""

    # HTML body
    body_html = f"""
<html>
  <body style="font-family: Arial, sans-serif; background-color: #f8fafc; color: #0f172a; padding: 24px;">
    <div style="max-width: 600px; margin: 0 auto; background-color: white; border-radius: 8px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
      <h2 style="color: #dc2626;">Database Backup Alert</h2>
      <p>The automated backup for database <strong>{db_name}</strong> <span style="color: #dc2626; font-weight: bold;">FAILED</span></p>
      <p><strong>Timestamp:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
      
      <h3 style="color: #7c3aed;">Error Details:</h3>
      <pre style="background-color: #f3f4f6; padding: 12px; border-radius: 4px; overflow-x: auto;">{error_message}</pre>
      
      <h3 style="color: #ea580c;">Action Required:</h3>
      <ul>
        <li>Investigate the backup failure immediately</li>
        <li>Verify your database backups manually</li>
        <li>Contact your DevOps team if this is a recurring issue</li>
      </ul>
      
      <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
      <p style="font-size: 12px; color: #6b7280;">jemPOS Automated Backup System</p>
    </div>
  </body>
</html>
"""

    try:
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = recipient_email

        # Attach plain text and HTML parts
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        # Send via SMTP
        with smtplib.SMTP(smtp_host, port_int, timeout=10) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())

        print(f"Alert email sent to {recipient_email}")
        return True

    except smtplib.SMTPAuthenticationError:
        print(f"Error: SMTP authentication failed (check EMAIL_SENDER and EMAIL_PASSWORD)")
        return False
    except smtplib.SMTPException as e:
        print(f"Error: SMTP error: {e}")
        return False
    except Exception as e:
        print(f"Error: Failed to send alert email: {e}")
        return False


def run_mysqldump_stream(host: str, port: str, user: str, password: str, db: str, out_gz_path: Path) -> int:
    # Build command without exposing password in args; pass via env MYSQL_PWD
    cmd = [
        "mysqldump",
        "-h",
        host,
        "-P",
        str(port),
        "-u",
        user,
        "--single-transaction",
        "--quick",
        "--skip-lock-tables",
        db,
    ]

    env = os.environ.copy()
    env["MYSQL_PWD"] = password or ""

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as proc:
        if proc.stdout is None:
            raise RuntimeError("Failed to open mysqldump stdout")
        # Stream stdout into gzip file
        with gzip.open(out_gz_path, "wb") as gz:
            for chunk in iter(lambda: proc.stdout.read(8192), b""):
                gz.write(chunk)
        _, stderr = proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="ignore") if stderr else ""
            raise RuntimeError(f"mysqldump failed (code={proc.returncode}): {err}")
    return 0


def cleanup_old_backups(backups_dir: Path, keep_days: int = 7) -> None:
    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    for p in sorted(backups_dir.glob("backup_jempos_*.sql.gz")):
        try:
            mtime = datetime.utcfromtimestamp(p.stat().st_mtime)
            if mtime < cutoff:
                p.unlink()
                print(f"Removed old backup: {p}")
        except Exception as e:
            print(f"Warning: could not remove {p}: {e}")


def main(argv: Optional[list[str]] = None) -> int:
    argv = argv or sys.argv[1:]
    script_path = Path(__file__).resolve()
    project_root = find_project_root(script_path)

    # .env path: argument or project root .env
    env_path = Path(argv[0]) if argv else project_root / ".env"

    print(f"Using .env: {env_path}")

    cfg = read_env(env_path)

    host = cfg.get("DB_HOST", "127.0.0.1")
    port = cfg.get("DB_PORT", "3306")
    user = cfg.get("DB_USER", "root")
    password = cfg.get("DB_PASSWORD", "")
    db = cfg.get("DB_NAME", "jempos")

    # Email config for alerts
    email_sender = cfg.get("EMAIL_SENDER", "")
    email_password = cfg.get("EMAIL_PASSWORD", "")
    smtp_host = cfg.get("EMAIL_SMTP_HOST", "")
    smtp_port = cfg.get("EMAIL_SMTP_PORT", "587")
    recipient_email = cfg.get("BACKUP_ALERT_EMAIL", email_sender)  # Use BACKUP_ALERT_EMAIL if set, else sender

    backups_dir = project_root / "backups"
    ensure_dir(backups_dir)

    now = datetime.utcnow()
    ts = now.strftime("%Y%m%d_%H%M")
    fname = f"backup_jempos_{ts}.sql.gz"
    out_gz = backups_dir / fname

    print(f"Starting backup of database '{db}' to {out_gz}")

    try:
        run_mysqldump_stream(host=host, port=port, user=user, password=password, db=db, out_gz_path=out_gz)
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR: Backup failed: {error_msg}")
        
        # Do not leave a zero-sized/incomplete file
        try:
            if out_gz.exists() and out_gz.stat().st_size == 0:
                out_gz.unlink()
        except Exception:
            pass

        # Send alert email
        if email_sender and email_password and smtp_host and recipient_email:
            send_alert_email(
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                sender_email=email_sender,
                sender_password=email_password,
                recipient_email=recipient_email,
                error_message=error_msg,
                db_name=db,
            )
        else:
            print("Warning: Email config incomplete, skipping alert")

        return 2

    print(f"Backup completed successfully: {out_gz}")

    # Cleanup older backups
    try:
        cleanup_old_backups(backups_dir, keep_days=7)
    except Exception as e:
        print(f"Warning: cleanup failed: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
