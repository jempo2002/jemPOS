"""Chequeo de filtros temporales y paginacion de Ventas y Gastos.

Dos bloques:
  1) Servicios + BD dentro de UNA transaccion que se revierte: limites de las
     capsulas, cortes de dia en hora local, paginacion sin solapes ni huecos,
     totales del encabezado y rechazo de entradas manipuladas.
  2) Rutas HTTP: contrato de /pos/api/ventas y /pos/api/gastos, y que el Cajero
     siga acotado a sus ultimas 24 horas aunque mande otra capsula.

    python scripts/check_filtros_paginacion.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

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
_real_rollback = conn.rollback


class _NoCommit:
    def __getattr__(self, name):
        return getattr(conn, name)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


from app.services import sales_service as svc  # noqa: E402

_get_db_real = svc.get_db
svc.get_db = lambda: _NoCommit()

Validacion = svc.SalesValidationError


def espera(excs, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except excs:
        return
    raise AssertionError(f"{fn.__name__} debio fallar con {excs}: {args}")


try:
    cur = conn.cursor(dictionary=True)

    # ── 0) Zona horaria: el corte del dia debe ser el del negocio ──
    # Los limites se calculan en Python y viajan como parametros, asi que app y
    # motor tienen que coincidir o "hoy" se corre de dia.
    cur.execute("SELECT NOW() AS motor")
    desfase = abs((cur.fetchone()["motor"] - datetime.now()).total_seconds())
    assert desfase < 120, f"app y MySQL difieren {desfase:.0f}s: el corte de 'hoy' se desplazaria"

    # ── 1) Limites de cada capsula ──────────────────────────
    ahora = datetime.now()
    hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    manana = hoy + timedelta(days=1)

    assert svc.periodo_bounds("hoy") == ("hoy", hoy, manana)
    assert svc.periodo_bounds("ayer") == ("ayer", hoy - timedelta(days=1), hoy)
    assert svc.periodo_bounds("semana") == ("semana", hoy - timedelta(days=hoy.weekday()), manana)
    assert svc.periodo_bounds("mes") == ("mes", hoy.replace(day=1), manana)
    assert svc.periodo_bounds("todas") == ("todas", None, None)

    # Capsula desconocida -> mes (nunca "sin filtro" por accidente).
    for basura in (None, "", "HOY_HACK", "'; DROP TABLE ventas;--", "24h", 7, ["mes"]):
        filtro, desde, hasta = svc.periodo_bounds(basura)
        assert filtro == "mes" and desde is not None, (basura, filtro)

    # Mayusculas y espacios si se aceptan.
    assert svc.periodo_bounds("  Ayer ")[0] == "ayer"

    # ── 2) Buscador de fecha ────────────────────────────────
    filtro, desde, hasta = svc.periodo_bounds("mes", "2026-03-13")
    assert filtro == "fecha", filtro
    assert desde == datetime(2026, 3, 13) and hasta == datetime(2026, 3, 14), (desde, hasta)

    # La fecha manda sobre la capsula.
    assert svc.periodo_bounds("todas", "2026-03-13")[1] == datetime(2026, 3, 13)

    # Fechas invalidas: error explicito, nunca se cuelan a la consulta.
    for mala in ("2026-13-40", "ayer", "13/03/2026", "2026-03-13' OR 1=1--", "0000-00-00", "x" * 40):
        espera(Validacion, svc.periodo_bounds, "mes", mala)

    # Vacio o espacios = sin fecha, se usa la capsula.
    assert svc.periodo_bounds("hoy", "")[0] == "hoy"
    assert svc.periodo_bounds("hoy", "   ")[0] == "hoy"

    # ── 3) Normalizacion de page y limit ────────────────────
    assert svc.paginacion(1, 20) == (1, 20)
    assert svc.paginacion(3, 50) == (3, 50)
    assert svc.paginacion(0, 20) == (1, 20)          # page < 1 -> 1
    assert svc.paginacion(-9, 20) == (1, 20)
    assert svc.paginacion(2, 0) == (2, 1)            # limit < 1 -> 1
    assert svc.paginacion(2, 99999) == (2, 100)      # techo: no se puede pedir todo
    assert svc.paginacion("abc", "xyz") == (1, 20)   # basura -> defaults
    assert svc.paginacion(None, None) == (1, 20)
    assert svc.paginacion("2", "5") == (2, 5)        # strings numericos del query string

    # ── 4) Metadatos del paginador ──────────────────────────
    m = svc._meta_paginacion(45, 1, 20)
    assert (m["pages"], m["offset"], m["has_prev"], m["has_next"]) == (3, 0, False, True), m
    m = svc._meta_paginacion(45, 3, 20)
    assert (m["page"], m["offset"], m["has_prev"], m["has_next"]) == (3, 40, True, False), m
    # Pagina fuera de rango: se acota a la ultima, sin OFFSET imposible.
    m = svc._meta_paginacion(45, 99, 20)
    assert (m["page"], m["offset"], m["has_next"]) == (3, 40, False), m
    # Sin registros: una pagina vacia, no cero paginas.
    m = svc._meta_paginacion(0, 5, 20)
    assert (m["pages"], m["page"], m["offset"], m["has_prev"], m["has_next"]) == (1, 1, 0, False, False), m
    # Multiplo exacto: 40/20 = 2 paginas, no 3.
    assert svc._meta_paginacion(40, 1, 20)["pages"] == 2

    # ── 5) Paginacion real de ventas: sin solapes ni huecos ─
    cur.execute(
        "SELECT v.id_tienda, COUNT(*) AS n FROM ventas v GROUP BY v.id_tienda "
        "ORDER BY n DESC LIMIT 1"
    )
    base = cur.fetchone()
    if not base:
        sys.exit("SKIP: no hay ventas registradas.")
    tienda = base["id_tienda"]

    todas, filtro, meta = svc.get_ventas(tienda, "Admin", None, "todas", None, 1, 100)
    assert filtro == "todas", filtro
    total = meta["total"]
    assert total == len(todas), (total, len(todas))

    # Recorrer de 2 en 2 debe reconstruir exactamente el mismo conjunto.
    recogidas, page = [], 1
    while True:
        pagina, _f, m_pag = svc.get_ventas(tienda, "Admin", None, "todas", None, page, 2)
        if not pagina:
            break
        assert len(pagina) <= 2, len(pagina)
        recogidas.extend(v["id_venta"] for v in pagina)
        if not m_pag["has_next"]:
            break
        page += 1
    assert len(recogidas) == len(set(recogidas)), "una venta salio en dos paginas"
    assert recogidas == [v["id_venta"] for v in todas], "la paginacion perdio o reordeno ventas"

    # Pedir una pagina inexistente devuelve la ultima, no un error de indice.
    ultima, _f, m_ultima = svc.get_ventas(tienda, "Admin", None, "todas", None, 9999, 2)
    assert m_ultima["page"] == m_ultima["pages"] and ultima, m_ultima

    # ── 6) El Cajero sigue acotado, mande lo que mande ──────
    cur.execute(
        "SELECT id_cajero FROM ventas WHERE id_tienda = %s AND fecha_creacion >= %s LIMIT 1",
        (tienda, datetime.now() - timedelta(days=1)),
    )
    fila_cajero = cur.fetchone()
    for capsula in ("todas", "mes", "hack"):
        lista_caj, filtro_caj, _m = svc.get_ventas(
            tienda, "Cajero", (fila_cajero or {}).get("id_cajero", 0), capsula, "2020-01-01", 1, 50
        )
        assert filtro_caj == "24h", (capsula, filtro_caj)
        for v in lista_caj:
            assert v["fecha_creacion"] >= datetime.now() - timedelta(days=2), v

    # Rol desconocido: lista vacia, sin filtrarse nada.
    vacio, _f, m_vacio = svc.get_ventas(tienda, "Fantasma", 1, "todas", None, 1, 20)
    assert vacio == [] and m_vacio["total"] == 0, m_vacio

    # ── 7) Gastos: cortes de dia y totales del encabezado ───
    cur.execute(
        "SELECT g.id_tienda, g.id_usuario, g.id_turno FROM gastos_caja g LIMIT 1"
    )
    g_base = cur.fetchone()
    if not g_base:
        sys.exit("SKIP: no hay gastos registrados.")
    gt, gu, g_turno = g_base["id_tienda"], g_base["id_usuario"], g_base["id_turno"]

    def insertar(fecha_creacion, monto, concepto):
        cur.execute(
            "INSERT INTO gastos_caja (id_tienda, id_turno, id_usuario, concepto, monto, fuente_dinero) "
            "VALUES (%s,%s,%s,%s,%s,'Bancos')",
            (gt, g_turno, gu, concepto, monto),
        )
        nuevo = cur.lastrowid
        # El trigger bi_gastos_caja_fecha_creacion fuerza CURRENT_TIMESTAMP:
        # la fecha de prueba se fija con un UPDATE posterior.
        cur.execute(
            "UPDATE gastos_caja SET fecha_creacion = %s WHERE id_gasto = %s",
            (fecha_creacion, nuevo),
        )
        return nuevo

    # Bordes del dia: el primer y el ultimo instante de hoy y de ayer.
    id_hoy_inicio = insertar(hoy, 111, "QA borde hoy 00:00")
    id_hoy_fin = insertar(manana - timedelta(seconds=1), 222, "QA borde hoy 23:59")
    id_ayer_fin = insertar(hoy - timedelta(seconds=1), 333, "QA borde ayer 23:59")

    def ids(filtro, fecha=None, page=1, limit=100):
        lista, _f, _m, _t = svc.get_gastos(gt, gu, filtro, fecha, page, limit)
        return {g["id"] for g in lista}

    en_hoy = ids("hoy")
    en_ayer = ids("ayer")
    assert id_hoy_inicio in en_hoy and id_hoy_fin in en_hoy, "los bordes de hoy quedaron fuera"
    assert id_ayer_fin not in en_hoy, "un gasto de ayer 23:59 se conto como hoy"
    assert id_ayer_fin in en_ayer, "el borde de ayer 23:59 quedo fuera de ayer"
    assert id_hoy_inicio not in en_ayer, "hoy 00:00 se conto como ayer"

    # El buscador de fecha acota exactamente a ese dia.
    en_fecha_hoy = ids("todas", hoy.date().isoformat())
    assert en_fecha_hoy == en_hoy, (en_fecha_hoy ^ en_hoy)

    # Las tarjetas de resumen NO siguen la capsula: al filtrar por Ayer, el
    # total de hoy debe seguir contando los gastos de hoy.
    _l, _f, _m, t_ayer = svc.get_gastos(gt, gu, "ayer", None, 1, 20)
    _l, _f, _m, t_hoy = svc.get_gastos(gt, gu, "hoy", None, 1, 20)
    assert t_ayer["hoy"] == t_hoy["hoy"], (t_ayer["hoy"], t_hoy["hoy"])
    assert t_ayer["mes"] == t_hoy["mes"], (t_ayer["mes"], t_hoy["mes"])
    assert t_ayer["hoy"] >= 111 + 222, t_ayer  # incluye los dos gastos de hoy

    # El WHERE del periodo si acota el listado: total y filas deben coincidir
    # cuando todo cabe en una pagina.
    for capsula in ("hoy", "ayer", "mes", "todas"):
        lista_p, _f, meta_p, _t = svc.get_gastos(gt, gu, capsula, None, 1, 100)
        assert not meta_p["has_next"], f"subir el limite: {capsula} no cabe en una pagina"
        assert meta_p["total"] == len(lista_p), (capsula, meta_p["total"], len(lista_p))
    # Y las capsulas son subconjuntos coherentes: hoy y ayer caben en el mes.
    assert ids("hoy") <= ids("mes") and ids("ayer") <= ids("todas")

    # Paginacion de gastos: sin solapes.
    p1 = ids("todas", None, 1, 2)
    p2 = ids("todas", None, 2, 2)
    assert not (p1 & p2), "un gasto salio en dos paginas"

    # Fecha invalida en gastos tambien se rechaza antes de tocar SQL.
    espera(Validacion, svc.get_gastos, gt, gu, "mes", "2026-99-99", 1, 20)

    print("OK bloque 1: capsulas, bordes de dia, fecha, paginacion sin solapes, totales del encabezado")
finally:
    _real_rollback()
    conn.close()
    svc.get_db = _get_db_real


# ══════════════════════════════════════════════════════════════
# BLOQUE 2 — RUTAS HTTP
# ══════════════════════════════════════════════════════════════
from app import create_app  # noqa: E402

app = create_app()
app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)


def sesion(cliente, rol, id_usuario=1, id_tienda=1):
    # login_required relee rol y tienda de la base: la sesion tiene que ser de
    # un usuario real (1 = Master de la tienda 1, 8 = Cajero de la tienda 4).
    with cliente.session_transaction() as s:
        s["id_usuario"] = id_usuario
        s["id_tienda"] = id_tienda
        s["rol"] = rol


META_CLAVES = {"page", "limit", "total", "pages", "offset", "has_prev", "has_next"}

with app.test_client() as c:
    # Sin sesion: 401 en las dos APIs.
    for ruta in ("/pos/api/ventas", "/pos/api/gastos"):
        assert c.get(ruta, headers={"X-Requested-With": "XMLHttpRequest"}).status_code == 401, ruta

with app.test_client() as c:
    sesion(c, "Admin")

    # Contrato de ventas.
    data = c.get("/pos/api/ventas?filtro=todas&page=1&limit=5").get_json()
    assert data["ok"] and set(data["meta"]) == META_CLAVES, data.get("meta")
    assert len(data["ventas"]) <= 5, len(data["ventas"])
    assert data["filtro"] == "todas", data["filtro"]
    if data["ventas"]:
        # Solo los campos que pinta la vista (el metodo de pago ya es columna):
        # ni turno ni ids internos.
        assert set(data["ventas"][0]) == {
            "id_venta", "total_final", "estado_venta", "fecha", "nombre_cliente", "nombre_cajero",
            "metodo_pago",
        }, sorted(data["ventas"][0])

    # Contrato de gastos.
    data = c.get("/pos/api/gastos?filtro=mes&page=1&limit=5").get_json()
    assert data["ok"] and set(data["meta"]) == META_CLAVES, data.get("meta")
    assert set(data["totales"]) == {"hoy", "mes"}, data["totales"]
    assert len(data["gastos"]) <= 5, len(data["gastos"])

    # Capsulas validas devuelven el filtro que se pidio.
    for capsula in ("hoy", "ayer", "semana", "mes", "todas"):
        for ruta in ("/pos/api/ventas", "/pos/api/gastos"):
            d = c.get(f"{ruta}?filtro={capsula}").get_json()
            assert d["ok"] and d["filtro"] == capsula, (ruta, capsula, d.get("filtro"))

    # Fecha concreta -> filtro 'fecha'.
    for ruta in ("/pos/api/ventas", "/pos/api/gastos"):
        d = c.get(f"{ruta}?fecha=2026-03-13").get_json()
        assert d["ok"] and d["filtro"] == "fecha", (ruta, d.get("filtro"))

    # Entradas manipuladas: 400 limpio o fallback, nunca 500 ni SQL crudo.
    for qs in (
        "fecha=2026-13-40",
        "fecha=' OR 1=1--",
        "fecha=2026-03-13'; DROP TABLE ventas;--",
    ):
        for ruta in ("/pos/api/ventas", "/pos/api/gastos"):
            r = c.get(f"{ruta}?{qs}")
            assert r.status_code == 400, (ruta, qs, r.status_code)
            assert r.get_json()["ok"] is False

    for qs in (
        "filtro='; DROP TABLE ventas;--",
        "page=-5&limit=0",
        "page=abc&limit=xyz",
        "limit=999999",
        "page=99999999",
    ):
        for ruta in ("/pos/api/ventas", "/pos/api/gastos"):
            r = c.get(f"{ruta}?{qs}")
            assert r.status_code == 200, (ruta, qs, r.status_code)
            meta = r.get_json()["meta"]
            assert meta["limit"] <= 100 and meta["page"] >= 1 and meta["offset"] >= 0, (qs, meta)

    # La pagina pedida fuera de rango vuelve acotada: el frontend se sincroniza.
    d = c.get("/pos/api/ventas?filtro=todas&page=99999&limit=5").get_json()
    assert d["meta"]["page"] == d["meta"]["pages"], d["meta"]

    # Las paginas HTML siguen renderizando.
    for ruta in ("/pos/ventas", "/pos/gastos"):
        assert c.get(ruta).status_code == 200, ruta

with app.test_client() as c:
    sesion(c, "Cajero", id_usuario=8, id_tienda=4)
    # El Cajero no puede ampliar su ventana con la capsula ni con la fecha.
    for qs in ("filtro=todas", "filtro=mes", "fecha=2020-01-01"):
        d = c.get(f"/pos/api/ventas?{qs}").get_json()
        assert d["ok"] and d["filtro"] == "24h", (qs, d.get("filtro"))
    assert c.get("/pos/ventas").status_code == 200
    assert c.get("/pos/api/gastos").get_json()["ok"] is True

print("OK bloque 2: contrato de /api/ventas y /api/gastos, entradas manipuladas y limites del Cajero")
