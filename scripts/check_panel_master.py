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
  6) Eliminar libera correo, cc y NIT (prefijo deleted_<ts>_): se pueden
     reutilizar en el panel y en el registro publico, el id y el historial
     no cambian, y un correo activo sigue bloqueado.

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
from app.routes import auth, core  # noqa: E402

core.get_db = auth.get_db = lambda: _NoCommit()
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
    q("UPDATE tiendas SET nit='900123999' WHERE id_tienda=2")
    brayan = q("SELECT correo FROM usuarios WHERE id_usuario=3")[0]["correo"]
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

    # 5a) Sin historial: se borra de verdad y el correo/cc se reusan al instante
    check(crear("9990055", "qa_borrar@test.com"), 200)
    id_borrar = q("SELECT id_usuario FROM usuarios WHERE correo='qa_borrar@test.com'")[0]["id_usuario"]
    check(client.delete(f"/api/master/usuarios/{id_borrar}"), 200)
    assert not q("SELECT 1 FROM usuarios WHERE id_usuario=%s", (id_borrar,)), "fila borrada"
    check(client.delete(f"/api/master/usuarios/{id_borrar}"), 404)
    check(crear("9990055", "qa_borrar@test.com"), 200)

    # 5b) Con historial (turnos de caja): no se puede borrar sin romper la
    # contabilidad -> se desactiva, se libera correo/cc y el historial sigue
    q("UPDATE usuarios SET id_tienda=1, cc='9990022' WHERE id_usuario IN (%s)", (nuevo["id_usuario"],))
    q("UPDATE usuarios SET cc='9990088' WHERE id_usuario=2")
    ximena = q("SELECT correo FROM usuarios WHERE id_usuario=2")[0]["correo"]
    turnos_2 = q("SELECT COUNT(*) n FROM turnos_caja WHERE id_usuario_apertura=2")[0]["n"]
    assert turnos_2 > 0
    check(client.delete("/api/master/usuarios/2"), 200)
    fila2 = q("SELECT correo, cc, estado_activo FROM usuarios WHERE id_usuario=2")[0]
    assert fila2["estado_activo"] == 0 and fila2["correo"].endswith("_" + ximena), fila2
    assert fila2["correo"].startswith("deleted_") and fila2["cc"].startswith("deleted_"), fila2
    assert q("SELECT COUNT(*) n FROM turnos_caja WHERE id_usuario_apertura=2")[0]["n"] == turnos_2
    check(crear("9990088", ximena), 200)

    # 5c) Eliminado con el codigo viejo (inactivo, correo sin prefijo): se
    # libera al volver a registrarlo en vez de responder "ya existe"
    q("UPDATE usuarios SET estado_activo=0, cc='9990044' WHERE id_usuario=8")
    cajero8 = q("SELECT correo FROM usuarios WHERE id_usuario=8")[0]["correo"]
    check(crear("9990044", cajero8), 200)

    # 6) Correo/cc/NIT de la tienda eliminada liberados
    assert q("SELECT nit FROM tiendas WHERE id_tienda=2")[0]["nit"].startswith("deleted_")
    borrado = q("SELECT correo FROM usuarios WHERE id_usuario=3")[0]["correo"]
    assert borrado.startswith("deleted_") and borrado.endswith("_" + brayan), borrado
    ventas_3 = q("SELECT COUNT(*) n FROM ventas WHERE id_cajero=3")[0]["n"]
    assert ventas_3 > 0, "historial de ventas del usuario eliminado sigue ligado a su id"

    def registro(correo, nit):
        return client.post("/registro", data={
            "nombre_dueno": "QA Dueno", "nombre_negocio": "QA Reuso", "nit": nit,
            "telefono": "3000000000", "correo": correo, "contrasena": PWD, "acepta_terminos": "1",
        })

    r = registro(brayan, "900123999")  # registro publico: reusar correo y NIT
    assert r.status_code == 302 and r.location.endswith("/login"), (r.status_code, r.location)
    assert q("SELECT COUNT(*) n FROM usuarios WHERE correo=%s AND estado_activo=1", (brayan,))[0]["n"] == 1
    r = registro(brayan, "900123998")  # ahora esta activo: bloquea
    assert r.status_code == 302 and r.location.endswith("/registro"), r.location
    check(crear("9990066", brayan), 409, "correo")

    print("OK check_panel_master: todos los casos pasan.")
finally:
    conn.rollback()
    conn.close()
