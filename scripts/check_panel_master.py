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
  7) Tienda al crear/editar: se guarda en Admin/Cajero, un Master nunca queda
     atado a una tienda, tiendas eliminadas o inexistentes -> 400. La CC no
     se puede cambiar por API; el correo si, sin duplicados.
  8) Finanzas del SaaS: registrar/borrar ingresos y gastos, validaciones y
     tarjetas del panel. Solo Master.
  9) Paginacion del panel (tiendas, proximos a vencer, usuarios) con paginas
     fuera de rango acotadas y enlaces que conservan la pagina de los otros.

    python scripts/check_panel_master.py
"""

from __future__ import annotations

import math
import os
import re
import sys
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

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


def crear(cc, correo, rol="Cajero", **extra):
    return client.post("/api/crear_usuario", json={
        "nombre": "QA " + correo, "correo": correo, "cc": cc, "rol": rol,
        "password": PWD, "confirm_password": PWD, **extra,
    })


def tienda_de(correo):
    return q("SELECT id_tienda FROM usuarios WHERE correo=%s", (correo,))[0]["id_tienda"]


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

    usuarios = {u["correo"]: u for u in client.get("/api/master/usuarios?limit=50").get_json()["usuarios"]}
    nuevo = usuarios["qa_uno@test.com"]
    otro_master = usuarios["qa_master@test.com"]
    assert nuevo["cc"] == "9990001" and usuarios["qa_cajero4@test.com"]["id_tienda"] == 4
    assert usuarios[q("SELECT correo FROM usuarios WHERE id_usuario=1")[0]["correo"]]["es_actual"]
    assert "bs5349764@gmail.com" not in usuarios, "usuarios de tienda eliminada no se listan"

    # 4) Editar
    url = f"/api/master/usuarios/{nuevo['id_usuario']}"
    # La CC es inmutable: ni otra libre ni una ajena; la misma o ninguna, si.
    check(client.put(url, json={"nombre": "Q", "cc": "9990011", "rol": "Cajero"}), 400, "no se puede modificar")
    check(client.put(url, json={"nombre": "Q", "cc": "9990002", "rol": "Cajero"}), 400, "no se puede modificar")
    check(client.put(url, json={"nombre": "Nuevo Nombre", "cc": "9990001", "rol": "Admin",
                                "password": PWD, "confirm_password": PWD}), 200)
    check(client.put(url, json={"nombre": "Nuevo Nombre", "rol": "Admin"}), 200)
    fila = q("SELECT nombre_completo, cc, rol FROM usuarios WHERE id_usuario=%s", (nuevo["id_usuario"],))[0]
    assert fila == {"nombre_completo": "Nuevo Nombre", "cc": "9990001", "rol": "Admin"}, fila
    check(client.put(url, json={"nombre": "X", "rol": "Admin", "password": "123", "confirm_password": "123"}), 400)
    check(client.put(url, json={"nombre": "X", "rol": "Admin", "password": PWD, "confirm_password": "otra"}), 400, "no coinciden")
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

    # 7) Tienda al crear y editar
    check(crear("9990101", "qa_t1@test.com", id_tienda=4), 200)
    assert tienda_de("qa_t1@test.com") == 4
    check(crear("9990102", "qa_t2@test.com", "Master", id_tienda=4), 200)
    assert tienda_de("qa_t2@test.com") is None, "un Master no se ata a una tienda"
    check(crear("9990103", "qa_t3@test.com", "Admin", id_tienda=""), 200)
    assert tienda_de("qa_t3@test.com") is None
    check(crear("9990104", "qa_t4@test.com", "Admin", id_tienda=2), 400, "tienda")      # eliminada en 2)
    check(crear("9990105", "qa_t5@test.com", "Admin", id_tienda=999999), 400, "tienda")
    check(crear("9990106", "qa_t6@test.com", "Admin", id_tienda="abc"), 400, "Tienda")
    assert not q("SELECT 1 FROM usuarios WHERE correo IN ('qa_t4@test.com','qa_t5@test.com','qa_t6@test.com')")

    q("INSERT INTO tiendas (nombre_negocio) VALUES ('QA Destino')")
    destino = q("SELECT LAST_INSERT_ID() AS id")[0]["id"]
    t1 = q("SELECT id_usuario FROM usuarios WHERE correo='qa_t1@test.com'")[0]["id_usuario"]
    url1 = f"/api/master/usuarios/{t1}"
    check(client.put(url1, json={"nombre": "QA", "rol": "Cajero", "id_tienda": destino}), 200)
    assert tienda_de("qa_t1@test.com") == destino
    check(client.put(url1, json={"nombre": "QA", "rol": "Cajero"}), 200)                # sin la clave: no cambia
    assert tienda_de("qa_t1@test.com") == destino
    check(client.put(url1, json={"nombre": "QA", "rol": "Cajero", "id_tienda": ""}), 200)
    assert tienda_de("qa_t1@test.com") is None
    check(client.put(url1, json={"nombre": "QA", "rol": "Cajero", "id_tienda": 2}), 400, "tienda")
    # Correo editable, validado y sin duplicados
    check(client.put(url1, json={"nombre": "QA", "rol": "Cajero", "correo": "QA_T1_Nuevo@Test.com"}), 200)
    assert q("SELECT correo FROM usuarios WHERE id_usuario=%s", (t1,))[0]["correo"] == "qa_t1_nuevo@test.com"
    check(client.put(url1, json={"nombre": "QA", "rol": "Cajero", "correo": "qa_uno@test.com"}), 409, "correo")
    check(client.put(url1, json={"nombre": "QA", "rol": "Cajero", "correo": "no-es-correo"}), 400, "correo")
    # El unico Admin no se va de su tienda; el Master conserva la suya (y su sesion)
    check(client.put("/api/master/usuarios/6", json={"nombre": "A", "cc": "9990098", "rol": "Admin", "id_tienda": destino}), 400, "unico Admin")
    assert tienda_de(q("SELECT correo FROM usuarios WHERE id_usuario=6")[0]["correo"]) == 4
    check(client.put("/api/master/usuarios/1", json={"nombre": "Juanes", "cc": "9990097", "rol": "Master", "id_tienda": destino}), 200)
    assert q("SELECT id_tienda FROM usuarios WHERE id_usuario=1")[0]["id_tienda"] == 1
    assert client.get("/api/master/usuarios").status_code == 200, "la sesion del Master sigue viva"
    # Una vez registrada, la CC de una cuenta antigua tambien queda bloqueada
    check(client.put("/api/master/usuarios/1", json={"nombre": "Juanes", "cc": "9990096", "rol": "Master"}), 400, "no se puede modificar")

    # 8) Finanzas del SaaS
    def mov(**d):
        return client.post("/api/master/movimientos", json=d)

    hoy = date.today()
    antes = core._get_master_resumen()
    check(mov(tipo="Ingreso", concepto="Mensualidad QA", monto=65000), 200, "Ingreso")
    check(mov(tipo="Gasto", concepto="Hosting QA", monto=100000, fecha=hoy.isoformat()), 200)
    check(mov(tipo="Otro", concepto="x", monto=1), 400, "Tipo")
    check(mov(tipo="Gasto", concepto="", monto=5), 400, "concepto")
    check(mov(tipo="Gasto", concepto="x", monto=0), 400, "monto")
    check(mov(tipo="Gasto", concepto="x", monto="NaN"), 400, "monto")
    check(mov(tipo="Gasto", concepto="x", monto=5, fecha=(hoy + timedelta(days=1)).isoformat()), 400, "futura")
    check(mov(tipo="Gasto", concepto="x", monto=5, fecha="2026-13-01"), 400, "Fecha")
    despues = core._get_master_resumen()

    def pesos(texto):
        return int(texto.replace("$", "").replace(".", ""))

    assert pesos(despues["ingresos_mes"]) - pesos(antes["ingresos_mes"]) == 65000, despues
    assert pesos(despues["gastos_mes"]) - pesos(antes["gastos_mes"]) == 100000, despues
    panel = client.get("/panel-master").get_data(as_text=True)
    assert "Mensualidad QA" in panel and "+$65.000" in panel and "−$100.000" in panel
    id_mov = q("SELECT id_movimiento FROM master_movimientos WHERE concepto='Hosting QA'")[0]["id_movimiento"]
    login(6, 4, "Admin")
    check(mov(tipo="Ingreso", concepto="x", monto=1), 403)
    check(client.delete(f"/api/master/movimientos/{id_mov}"), 403)
    login(1, 1, "Master")
    check(client.delete(f"/api/master/movimientos/{id_mov}"), 200)
    check(client.delete(f"/api/master/movimientos/{id_mov}"), 404)

    # 9) Paginacion
    for i in range(12):
        q("INSERT INTO tiendas (nombre_negocio, estado_suscripcion, fecha_fin_suscripcion) "
          "VALUES (%s, 'activa', CURDATE() + INTERVAL 2 DAY)", (f"ZZ QA Pag {i:02d}",))
    total_t = q("SELECT COUNT(*) n FROM tiendas WHERE estado <> 'Eliminado'")[0]["n"]
    total_v = q("SELECT COUNT(*) n FROM tiendas WHERE estado <> 'Eliminado' AND fecha_fin_suscripcion IS NOT NULL "
                "AND fecha_fin_suscripcion <= CURDATE() + INTERVAL 5 DAY")[0]["n"]
    pags_t, pags_v = math.ceil(total_t / 10), math.ceil(total_v / 5)

    def seccion(html, ancla):
        return re.search(rf'<section id="{ancla}".*?</section>', html, re.S).group(0)

    def filas(html, ancla):  # cada tienda sale dos veces: tarjeta movil + fila de tabla
        return seccion(html, ancla).count("data-tienda-row=") // 2

    html = client.get("/panel-master").get_data(as_text=True)
    assert filas(html, "tiendas") == 10 and filas(html, "vencer") == 5
    assert f"1 / {pags_t}" in seccion(html, "tiendas") and f"1 / {pags_v}" in seccion(html, "vencer")
    enlace = re.search(r'href="([^"]*pt=2[^"]*)"', seccion(html, "tiendas")).group(1)
    assert "pv=1" in enlace and "pm=1" in enlace and enlace.endswith("#tiendas"), enlace
    html = client.get("/panel-master?pt=2&pv=2").get_data(as_text=True)
    assert filas(html, "tiendas") == min(10, total_t - 10) and filas(html, "vencer") == min(5, total_v - 5)
    enlace = re.search(r'href="([^"]*pv=1[^"]*)"', seccion(html, "vencer")).group(1)
    assert "pt=2" in enlace, "moverse en un listado conserva la pagina del otro"
    html = client.get("/panel-master?pt=999&pv=-4&pm=xyz").get_data(as_text=True)
    assert f"{pags_t} / {pags_t}" in seccion(html, "tiendas"), "pagina fuera de rango -> la ultima"
    assert filas(html, "vencer") == 5
    # Usuarios: paginado y buscable en el servidor
    r = client.get("/api/master/usuarios?limit=2&page=2").get_json()
    assert r["meta"]["page"] == 2 and len(r["usuarios"]) == 2 and r["meta"]["has_prev"], r["meta"]
    r = client.get("/api/master/usuarios?limit=2&page=999").get_json()
    assert r["meta"]["page"] == r["meta"]["pages"], r["meta"]
    r = client.get("/api/master/usuarios?q=qa_t1_nuevo").get_json()
    assert [u["correo"] for u in r["usuarios"]] == ["qa_t1_nuevo@test.com"], r
    r = client.get("/api/master/usuarios?q=9990101").get_json()          # la CC no se ve, pero se busca
    assert r["meta"]["total"] == 1, r
    # Sin columna CC en la tabla del modal
    modal = re.search(r'id="modal-gestion-usuarios".*?</table>', html, re.S).group(0)
    assert ">CC<" not in modal and "Cedula" not in modal
    js = open(os.path.join(RAIZ, "static", "js", "panel_master.js"), encoding="utf-8").read()
    assert "Sin CC" not in js and "$('usr-cc').disabled = ccBloqueada;" in js

    print("OK check_panel_master: todos los casos pasan.")
finally:
    conn.rollback()
    conn.close()
