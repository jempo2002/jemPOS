"""Aplica un archivo .sql de migrations/ usando las credenciales de .env.

Existe porque en Windows no siempre hay cliente `mysql` en el PATH, que es lo
que asume scripts/README.md. Ejecuta sentencia por sentencia y trata como
no-op los errores de "ya existe" (duplicate key/column/constraint), asi la
migracion es idempotente igual que los `IF NOT EXISTS` del propio SQL.

    python scripts/run_migration.py migrations/2026-09-22_cartera_b2b.sql
"""

from __future__ import annotations

import os
import re
import sys

import mysql.connector
from dotenv import load_dotenv

# Errores que significan "ya estaba aplicado", no un fallo real.
_YA_EXISTE = {1050, 1060, 1061, 1022, 1826, 121, 1091}


def _ya_aplicada(exc: mysql.connector.Error) -> bool:
    if exc.errno in _YA_EXISTE:
        return True
    # MariaDB envuelve "constraint duplicada" en 1005 + errno 121 en el mensaje.
    return exc.errno == 1005 and ("121" in (exc.msg or "") or "Duplicate key" in (exc.msg or ""))


def _sentencias(sql: str):
    """Divide en sentencias por ';' al final de linea, ignorando comentarios."""
    sin_comentarios = re.sub(r"^\s*--.*$", "", sql, flags=re.MULTILINE)
    for bloque in sin_comentarios.split(";"):
        limpio = bloque.strip()
        if limpio:
            yield limpio


def main(ruta: str) -> int:
    load_dotenv()
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT") or 3306),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        autocommit=True,
    )
    with open(ruta, "r", encoding="utf-8") as fh:
        sql = fh.read()

    cur = conn.cursor()
    aplicadas = omitidas = 0
    try:
        for sentencia in _sentencias(sql):
            try:
                cur.execute(sentencia)
                cur.fetchall() if cur.with_rows else None
                aplicadas += 1
            except mysql.connector.Error as exc:
                if _ya_aplicada(exc):
                    omitidas += 1
                    continue
                print(f"ERROR {exc.errno}: {exc.msg}\n  en: {sentencia[:120]}...")
                return 1
    finally:
        cur.close()
        conn.close()

    print(f"OK {ruta}: {aplicadas} sentencias aplicadas, {omitidas} ya existian.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
