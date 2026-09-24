"""Chequeo del Panel Master: eliminar tienda y gestion de usuarios.

Todo corre en UNA transaccion que se revierte al final: no deja datos.
Requiere migrations/2026-09-23_tiendas_estado_eliminado.sql y el volcado
base (Master id=1 en tienda 1, tienda 2 con ventas, tienda 4 con un unico
Admin id=6 y un Cajero id=8).

  1) Un Admin no puede tocar las APIs del Panel Master.
  2) Eliminar una tienda con ventas funciona (soft delete), la saca del panel
     y desactiva a sus usuarios. La tienda propia no se puede eliminar.
  3) Crear usuario exige cedula y rechaza cedulas duplicadas.
  4) Editar: nombre/cc/rol, sin cc duplicada, sin cambiar el rol propio ni
     dejar una tienda sin Admin.
  5) Eliminar: ni a uno mismo, ni a un Master, ni al ultimo Admin.

    python scripts/check_panel_master.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector
from dotenv import load_dotenv

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT") or 3306),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    autocommit=False,
)


class _NoCommit:
    """La misma conexion para todo; commit/rollback/close no hacen nada."""

    def __getattr__(self, name):
        return getattr(conn, name)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


from app import create_app  # noqa: E402
from app.routes import core  # noqa: E402

core.get_db = lambda: _NoCommit()
app = create_app()
app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
client = app.test_client()
PWD = "Clave#Segura123"


def login(id_usuario, id_tienda, rol):
    with client.session_transaction() as s:
        s.update(id_usuario=id_usuario, id_tienda=id_tienda, rol=rol, nombre_completo="QA")


def q(sql, params=()):
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    return cur.fetchall()


def check(resp, status, texto=""):
    body = resp.get_json()
    assert resp.status_code == status, (resp.status_code, body)
    assert texto in (body or {}).get("msg", ""), body
    return body


def crear(cc, correo, rol="Cajero"):
    return client.post("/api/crear_usuario", json={
        "nombre": "QA " + correo, "correo": correo, "cc": cc, "rol": rol,
        "password": PWD, "confirm_password": PWD,
    })


try:
    # 1) Admin fuera del panel
    login(2, 1, "Admin")
    check(client.delete("/api/master/tiendas/2"), 403)
    check(client.get("/api/master/usuarios"), 403)

    login(1, 1, "Master")

    # 2) Eliminar tienda
    check(client.delete("/api/master/tiendas/1"), 400, "propia")
    check(client.delete("/api/master/tiendas/2"), 200, "eliminada")
    assert q("SELECT estado FROM tiendas WHERE id_tienda=2")[0]["estado"] == "Eliminado"
    assert not q("SELECT 1 FROM usuarios WHERE id_tienda=2 AND estado_activo=1")
    assert q("SELECT COUNT(*) n FROM ventas WHERE id_tienda=2")[0]["n"] > 0, "historial intacto"
    assert b"puppifresh" not in client.get("/panel-master").data
    check(client.delete("/api/master/tiendas/2"), 404)
    check(client.put("/api/master/tiendas/2", json={"nombre_negocio": "x"}), 404)

    # 3) Crear con cedula
    check(crear("", "qa_sin_cc@test.com"), 400, "cedula")
    check(crear("12", "qa_corta@test.com"), 400, "entre 5 y 15")
    check(crear("9990001", "qa_uno@test.com"), 200)
    check(crear("9.990.001", "qa_dos@test.com"), 409, "cedula")
    check(crear("9990002", "qa_master@test.com", "Master"), 200)
    # Admin creando cajero desde su dashboard tambien manda cc
    login(6, 4, "Admin")
    check(crear("9990003", "qa_cajero4@test.com"), 200)
    login(1, 1, "Master")

    usuarios = {u["correo"]: u for u in client.get("/api/master/usuarios").get_json()["usuarios"]}
    nuevo = usuarios["qa_uno@test.com"]
    otro_master = usuarios["qa_master@test.com"]
    assert nuevo["cc"] == "9990001" and usuarios["qa_cajero4@test.com"]["id_tienda"] == 4
    assert usuarios[q("SELECT correo FROM usuarios WHERE id_usuario=1")[0]["correo"]]["es_actual"]
    assert "bs5349764@gmail.com" not in usuarios, "usuarios de tienda eliminada no se listan"

    # 4) Editar
    url = f"/api/master/usuarios/{nuevo['id_usuario']}"
    check(client.put(url, json={"nombre": "Q", "cc": "9990002", "rol": "Cajero"}), 409, "cedula")
    check(client.put(url, json={"nombre": "Nuevo Nombre", "cc": "9990011", "rol": "Admin", "password": PWD}), 200)
    fila = q("SELECT nombre_completo, cc, rol FROM usuarios WHERE id_usuario=%s", (nuevo["id_usuario"],))[0]
    assert fila == {"nombre_completo": "Nuevo Nombre", "cc": "9990011", "rol": "Admin"}, fila
    check(client.put(url, json={"nombre": "X", "cc": "9990011", "rol": "Admin", "password": "123"}), 400)
    check(client.put("/api/master/usuarios/1", json={"nombre": "Yo", "cc": "9990099", "rol": "Admin"}), 400, "propio rol")
    check(client.put("/api/master/usuarios/6", json={"nombre": "A", "cc": "9990098", "rol": "Cajero"}), 400, "unico Admin")

    # 5) Eliminar
    check(client.delete("/api/master/usuarios/1"), 400, "propia cuenta")
    check(client.delete(f"/api/master/usuarios/{otro_master['id_usuario']}"), 403, "Master")
    check(client.delete("/api/master/usuarios/6"), 400, "unico Admin")
    check(client.delete("/api/master/usuarios/8"), 200)
    assert q("SELECT estado_activo FROM usuarios WHERE id_usuario=8")[0]["estado_activo"] == 0
    check(client.delete("/api/master/usuarios/8"), 404)

    print("OK check_panel_master: todos los casos pasan.")
finally:
    conn.rollback()
    conn.close()
