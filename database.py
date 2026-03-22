"""database.py — pool de conexiones MySQL para jemPOS.

Uso:
    from database import init_pool, get_db

    # Al arrancar:
    init_pool(host, port, user, password, database)

    # En cada request:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT ...', (param,))
        rows = cur.fetchall()
    finally:
        conn.close()   # devuelve la conexion al pool
"""

from __future__ import annotations
import mysql.connector
from mysql.connector import pooling

_pool: pooling.MySQLConnectionPool | None = None


def init_pool(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    pool_size: int = 5,
) -> None:
    """Crea el pool de conexiones. Llama esto una sola vez al iniciar la app."""
    global _pool
    _pool = pooling.MySQLConnectionPool(
        pool_name="jempos",
        pool_size=pool_size,
        pool_reset_session=True,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        autocommit=False,
        connection_timeout=10,
    )


def init_pool_from_app(app) -> None:
    """Inicializa el pool usando app.config (patron application factory)."""
    init_pool(
        host=app.config["DB_HOST"],
        port=app.config["DB_PORT"],
        user=app.config["DB_USER"],
        password=app.config["DB_PASSWORD"],
        database=app.config["DB_NAME"],
    )


def get_db() -> mysql.connector.MySQLConnection:
    """Obtiene una conexion del pool. Siempre cierrala en un bloque finally."""
    if _pool is None:
        raise RuntimeError(
            "El pool de conexiones no esta inicializado. Llama init_pool() primero."
        )
    return _pool.get_connection()
