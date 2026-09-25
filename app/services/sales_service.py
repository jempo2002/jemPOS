from __future__ import annotations

from datetime import date, datetime, timedelta

from mysql.connector import IntegrityError

from app.services.inventory_service import UNIDADES_FRACCIONABLES
from app.utils.helpers import normalize_payment_method, only_digits
from app.utils.validation import parse_float, parse_int, sanitize_optional_text, sanitize_text
from database import get_db


class SalesServiceError(ValueError):
    pass


class SalesValidationError(SalesServiceError):
    pass


class SalesNotFoundError(SalesServiceError):
    pass


class SalesConflictError(SalesServiceError):
    pass


def _raise_validation(exc: ValueError) -> None:
    raise SalesValidationError(str(exc)) from exc


def _registrar_auditoria(id_tienda, id_usuario, accion, detalles) -> None:
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auditoria (id_tienda, id_usuario, accion, detalles) "
            "VALUES (%s, %s, %s, %s)",
            (id_tienda, id_usuario, accion, detalles),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _obtener_turno_abierto(id_tienda: int, cur) -> int | None:
    cur.execute(
        "SELECT id_turno FROM turnos_caja "
        "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
        "ORDER BY fecha_apertura DESC LIMIT 1",
        (id_tienda,),
    )
    fila = cur.fetchone()
    return fila["id_turno"] if fila else None


def get_dias_restantes(id_tienda: int) -> int:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT fecha_fin_suscripcion FROM tiendas WHERE id_tienda = %s LIMIT 1",
            (id_tienda,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if not row or not row.get("fecha_fin_suscripcion"):
        return 999
    return (row["fecha_fin_suscripcion"] - date.today()).days


def get_categorias_gastos(id_tienda: int) -> list[str]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT concepto FROM gastos_caja WHERE id_tienda = %s ORDER BY concepto",
            (id_tienda,),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    return [r[0] for r in filas if r and r[0]]


def get_money_flow_summary(id_tienda: int, since: datetime, until: datetime) -> dict:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        cur.execute(
            "SELECT COALESCE(SUM(v.total_final),0) AS entradas "
            "FROM ventas v "
            "WHERE v.id_tienda=%s AND v.estado_venta='Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s",
            (id_tienda, since, until),
        )
        entradas = float((cur.fetchone() or {}).get("entradas") or 0)

        cur.execute(
            "SELECT COALESCE(SUM(g.monto),0) AS salidas "
            "FROM gastos_caja g "
            "WHERE g.id_tienda=%s AND g.fecha_creacion >= %s AND g.fecha_creacion < %s",
            (id_tienda, since, until),
        )
        salidas = float((cur.fetchone() or {}).get("salidas") or 0)
    finally:
        conn.close()

    return {
        "entradas": entradas,
        "salidas": salidas,
    }


def get_top_vendidos(id_tienda: int, since: datetime, until: datetime, limit: int = 5) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT p.nombre, SUM(dv.cantidad) AS total "
            "FROM detalle_ventas dv "
            "INNER JOIN ventas v ON dv.id_venta = v.id_venta "
            "INNER JOIN productos p ON dv.id_producto = p.id_producto AND p.id_tienda = v.id_tienda "
            "WHERE v.id_tienda=%s AND v.estado_venta='Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s "
            "GROUP BY dv.id_producto, p.nombre "
            "ORDER BY total DESC LIMIT %s",
            (id_tienda, since, until, limit),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    return [
        {
            "name": r.get("nombre") or "Producto",
            "total": float(r.get("total") or 0),
        }
        for r in filas
    ]


def get_stock_alerts(id_tienda: int, limit: int = 10) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT nombre, stock_actual, stock_minimo_alerta "
            "FROM productos "
            "WHERE id_tienda=%s AND estado_activo=1 "
            "AND stock_minimo_alerta IS NOT NULL "
            "AND stock_actual <= stock_minimo_alerta "
            "ORDER BY stock_actual ASC "
            "LIMIT %s",
            (id_tienda, limit),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    return [
        {
            "name": r.get("nombre") or "Producto",
            "stock": float(r.get("stock_actual") or 0),
            "min": float(r.get("stock_minimo_alerta") or 0),
        }
        for r in filas
    ]


# Saldo pendiente de un cliente `c`: ventas fiadas menos sus abonos.
_DEUDA_CLIENTE_SQL = """
  COALESCE((
    SELECT SUM(
      GREATEST(
        v.total_final - COALESCE((
          SELECT SUM(ab.monto_abonado)
          FROM abonos_fiados ab
          WHERE ab.id_venta = v.id_venta
        ), 0),
        0
      )
    )
    FROM ventas v
    WHERE v.id_cliente = c.id_cliente
      AND v.id_tienda  = c.id_tienda
      AND v.estado_venta = 'Fiada/Pendiente'
  ), 0)
"""


def get_fiados_clientes(id_tienda: int) -> list[dict]:
    """Cuentas por cobrar: deuda por cliente + indicador de mora.

    `dias_mora` son los dias desde la deuda pendiente mas antigua; la vista lo
    traduce a las etiquetas Al dia / En riesgo / En mora.
    """
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT c.id_cliente, c.nombre, c.telefono, c.tipo,
              {_DEUDA_CLIENTE_SQL} AS deuda_total,
              (SELECT MIN(v.fecha_creacion) FROM ventas v
                WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
                  AND v.estado_venta = 'Fiada/Pendiente') AS deuda_desde
            FROM clientes c
            WHERE c.id_tienda = %s AND c.estado_activo = 1
            ORDER BY c.nombre
            """,
            (id_tienda,),
        )
        filas = cur.fetchall()
    finally:
        conn.close()

    hoy = date.today()
    clientes = []
    for f in filas:
        desde = f.get("deuda_desde")
        deuda = max(0.0, float(f["deuda_total"] or 0))
        if desde and deuda > 0:
            inicio = desde.date() if isinstance(desde, datetime) else desde
            dias_mora = max(0, (hoy - inicio).days)
        else:
            dias_mora = 0
        clientes.append(
            {
                "id": f["id_cliente"],
                "name": f["nombre"],
                "phone": f["telefono"] or "-",
                "debt": deuda,
                "tipo": f.get("tipo") or "B2C",
                "dias_mora": dias_mora,
            }
        )
    return clientes


def buscar_clientes_fiado(id_tienda: int, q: str, limit: int = 8) -> list[dict]:
    """Live search de clientes por nombre, cedula o telefono, con su deuda actual."""
    q = str(q or "").strip()[:60]
    if len(q) < 2:
        return []

    like = f"%{q}%"
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT c.id_cliente, c.nombre, c.cedula, c.telefono,
              {_DEUDA_CLIENTE_SQL} AS deuda_total
            FROM clientes c
            WHERE c.id_tienda = %s AND c.estado_activo = 1
              AND (c.nombre LIKE %s OR c.cedula LIKE %s OR c.telefono LIKE %s)
            ORDER BY deuda_total DESC, c.nombre
            LIMIT %s
            """,
            (id_tienda, like, like, like, limit),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    return [
        {
            "id": f["id_cliente"],
            "name": f["nombre"],
            "cedula": f.get("cedula") or "",
            "phone": f.get("telefono") or "",
            "debt": max(0.0, float(f["deuda_total"] or 0)),
        }
        for f in filas
    ]


def _resolver_cliente_fiado(cur, id_tienda: int, cliente) -> int:
    """Id del cliente de una venta fiada: el seleccionado en el live search
    (`id`) o uno nuevo. Corre dentro de la transaccion de la venta."""
    if not isinstance(cliente, dict):
        raise SalesValidationError("Indica el cliente al que se le fia.")
    try:
        nombre = sanitize_text(cliente.get("nombre"), "El nombre del cliente", max_len=150)
        id_cliente = cliente.get("id") or None
        if id_cliente is not None:
            id_cliente = parse_int(id_cliente, "Cliente", min_value=1)
    except ValueError as exc:
        _raise_validation(exc)
    telefono = only_digits(cliente.get("telefono"))
    cedula = only_digits(cliente.get("cedula")) or None
    if not 7 <= len(telefono) <= 25:
        raise SalesValidationError("El telefono debe tener entre 7 y 25 digitos.")
    if cedula and not 5 <= len(cedula) <= 20:
        raise SalesValidationError("La cedula debe tener entre 5 y 20 digitos.")

    if id_cliente is None:
        cur.execute(
            "SELECT id_cliente, nombre, estado_activo FROM clientes "
            "WHERE id_tienda = %s AND (telefono = %s OR cedula = %s) LIMIT 1",
            (id_tienda, telefono, cedula),
        )
    else:
        cur.execute(
            "SELECT id_cliente, nombre, estado_activo FROM clientes "
            "WHERE id_cliente = %s AND id_tienda = %s LIMIT 1",
            (id_cliente, id_tienda),
        )
    fila = cur.fetchone()

    if id_cliente is not None and not fila:
        raise SalesNotFoundError("Cliente no encontrado.")
    if id_cliente is None and fila and fila["estado_activo"]:
        # Sin seleccion explicita no se carga deuda a un cliente existente:
        # un digito mal escrito le sumaria la cuenta a otra persona.
        raise SalesConflictError(
            f"{fila['nombre']} ya tiene ese telefono o cedula. Buscalo y seleccionalo en la lista."
        )

    try:
        if fila:
            # Seleccionado (o inactivo con esos datos, que se reactiva).
            cur.execute(
                "UPDATE clientes SET telefono = %s, cedula = COALESCE(%s, cedula), estado_activo = 1 "
                "WHERE id_cliente = %s",
                (telefono, cedula, fila["id_cliente"]),
            )
            return fila["id_cliente"]
        cur.execute(
            "INSERT INTO clientes (id_tienda, nombre, cedula, telefono) VALUES (%s, %s, %s, %s)",
            (id_tienda, nombre, cedula, telefono),
        )
        return cur.lastrowid
    except IntegrityError as exc:
        raise SalesConflictError("Ese telefono o cedula ya pertenece a otro cliente.") from exc


# ══════════════════════════════════════════════════════════════
# FILTROS TEMPORALES Y PAGINACION (Ventas y Gastos)
# ══════════════════════════════════════════════════════════════

PERIODOS = ("hoy", "ayer", "semana", "mes", "anio", "todas")


def periodo_bounds(filtro: str | None, fecha: str | None = None) -> tuple[str, datetime | None, datetime | None]:
    """Traduce una capsula de tiempo a un rango [desde, hasta) concreto.

    Los limites se calculan en Python, con la hora local del servidor de la app,
    y viajan a SQL como parametros. Asi el corte de "hoy" es el del negocio y no
    depende de CURDATE()/NOW() del motor, que puede estar en otra zona horaria.

    El rango es semiabierto (>= desde AND < hasta) a proposito: con BETWEEN un
    registro de las 23:59:59.4 se quedaria fuera del dia.

    `fecha` (YYYY-MM-DD) tiene prioridad sobre la capsula y acota a ese dia.
    """
    ahora = datetime.now()
    hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    manana = hoy + timedelta(days=1)

    texto_fecha = str(fecha or "").strip()
    if texto_fecha:
        if len(texto_fecha) > 10:
            raise SalesValidationError("Fecha invalida.")
        try:
            dia = date.fromisoformat(texto_fecha)
        except ValueError as exc:
            raise SalesValidationError("Fecha invalida.") from exc
        desde = datetime(dia.year, dia.month, dia.day)
        return "fecha", desde, desde + timedelta(days=1)

    filtro = str(filtro or "").strip().lower()
    if filtro not in PERIODOS:
        filtro = "mes"

    if filtro == "todas":
        return "todas", None, None
    if filtro == "hoy":
        return "hoy", hoy, manana
    if filtro == "ayer":
        return "ayer", hoy - timedelta(days=1), hoy
    if filtro == "semana":
        # Semana corrida desde el lunes, igual que el filtro del dashboard.
        return "semana", hoy - timedelta(days=hoy.weekday()), manana
    if filtro == "anio":
        return "anio", hoy.replace(month=1, day=1), manana
    return "mes", hoy.replace(day=1), manana


def paginacion(page, limit, *, defecto: int = 20, maximo: int = 100) -> tuple[int, int]:
    """Normaliza ?page=&limit= a enteros seguros para LIMIT/OFFSET."""
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = defecto
    return max(1, page), min(max(1, limit), maximo)


def _meta_paginacion(total: int, page: int, limit: int) -> dict:
    """Metadatos del paginador, con la pagina acotada al rango real."""
    paginas = max(1, -(-total // limit))  # techo de total/limit
    page = min(page, paginas)
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "pages": paginas,
        "offset": (page - 1) * limit,
        "has_prev": page > 1,
        "has_next": page < paginas,
    }


def get_ventas(
    id_tienda: int,
    rol: str,
    id_usuario: int | None,
    filtro: str | None,
    fecha: str | None = None,
    page=1,
    limit=20,
    id_cajero: int | None = None,
) -> tuple[list[dict], str, dict]:
    """Pagina del historial de ventas + filtro aplicado + metadatos del paginador.

    El Cajero sigue viendo solo sus propias ventas de las ultimas 24 horas: las
    capsulas y el buscador de fecha se ignoran para ese rol. Admin/Master
    pueden acotar a un trabajador con `id_cajero` (modal del Panel de Control).
    """
    page, limit = paginacion(page, limit)

    condiciones = ["v.id_tienda = %s"]
    parametros: list = [id_tienda]

    if rol == "Cajero":
        filtro_final = "24h"
        condiciones.append("v.id_cajero = %s")
        parametros.append(id_usuario)
        condiciones.append("v.fecha_creacion >= %s")
        parametros.append(datetime.now() - timedelta(days=1))
    elif rol in {"Admin", "Master"}:
        filtro_final, desde, hasta = periodo_bounds(filtro, fecha)
        if desde is not None:
            condiciones.append("v.fecha_creacion >= %s AND v.fecha_creacion < %s")
            parametros.extend([desde, hasta])
        if id_cajero is not None:
            condiciones.append("v.id_cajero = %s")
            parametros.append(id_cajero)
    else:
        return [], "mes", _meta_paginacion(0, 1, limit)

    where = " AND ".join(condiciones)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(f"SELECT COUNT(*) AS total FROM ventas v WHERE {where}", tuple(parametros))
        total = int((cur.fetchone() or {}).get("total") or 0)

        meta = _meta_paginacion(total, page, limit)
        cur.execute(
            "SELECT v.id_venta, v.numero_venta, v.metodo_pago, v.total_final, v.estado_venta, v.fecha_creacion, "
            "COALESCE(c.nombre, 'Mostrador') AS nombre_cliente, "
            "u.nombre_completo AS nombre_cajero "
            "FROM ventas v "
            "LEFT JOIN clientes c ON v.id_cliente = c.id_cliente AND c.id_tienda = v.id_tienda "
            "LEFT JOIN usuarios u ON v.id_cajero = u.id_usuario "
            f"WHERE {where} "
            "ORDER BY v.id_venta DESC LIMIT %s OFFSET %s",
            tuple(parametros) + (meta["limit"], meta["offset"]),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    lista = [
        {
            "id_venta": fila.get("id_venta"),
            "total_final": float(fila.get("total_final") or 0),
            "estado_venta": (fila.get("estado_venta") or "Pagada").strip() or "Pagada",
            "fecha_creacion": fila.get("fecha_creacion"),
            "nombre_cliente": fila.get("nombre_cliente") or "Mostrador",
            "nombre_cajero": fila.get("nombre_cajero") or "Sin cajero",
            "metodo_pago": _metodo_visible(fila.get("numero_venta"), fila.get("metodo_pago")),
        }
        for fila in filas
    ]
    return lista, filtro_final, meta


def get_totales_ventas(id_tienda: int, rol: str, id_usuario: int | None) -> dict:
    """Tarjetas "Ventas de hoy" y "Ventas del mes" del historial.

    Como en Gastos, se suman en SQL sobre todas las ventas y no sobre la pagina
    ni la capsula: filtrar por Ayer no deja "hoy" en 0. Anuladas no cuentan;
    los fiados si, son ventas hechas. El Cajero ve solo las suyas.
    """
    ahora = datetime.now()
    inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_mes = inicio_dia.replace(day=1)
    fin_dia = inicio_dia + timedelta(days=1)

    where = "v.id_tienda = %s AND v.estado_venta <> 'Anulada' AND v.fecha_creacion >= %s AND v.fecha_creacion < %s"
    params: tuple = (id_tienda, inicio_mes, fin_dia)
    if rol == "Cajero":
        where += " AND v.id_cajero = %s"
        params += (id_usuario,)
    elif rol not in {"Admin", "Master"}:
        return {"hoy": 0.0, "mes": 0.0}

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT COALESCE(SUM(CASE WHEN v.fecha_creacion >= %s THEN v.total_final ELSE 0 END), 0) AS hoy, "
            "       COALESCE(SUM(v.total_final), 0) AS mes "
            f"FROM ventas v WHERE {where}",
            (inicio_dia,) + params,
        )
        fila = cur.fetchone() or {}
    finally:
        conn.close()
    return {"hoy": float(fila.get("hoy") or 0), "mes": float(fila.get("mes") or 0)}


def get_resumen_ventas_cajero(id_tienda: int, id_cajero: int, filtro: str | None, fecha: str | None = None) -> dict:
    """Cifras de un trabajador en el periodo del modal del Panel de Control.

    Mismo reparto que get_rendimiento_personal: anuladas aparte; el fiado se
    reconoce por el prefijo F del consecutivo (ver _metodo_visible) y lo que
    no es fiado ni efectivo va a "otros" (Nequi, tarjeta, transferencia...).
    """
    _filtro, desde, hasta = periodo_bounds(filtro, fecha)
    where = "v.id_tienda = %s AND v.id_cajero = %s"
    params: tuple = (id_tienda, id_cajero)
    if desde is not None:
        where += " AND v.fecha_creacion >= %s AND v.fecha_creacion < %s"
        params += (desde, hasta)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT COUNT(CASE WHEN v.estado_venta <> 'Anulada' THEN 1 END) AS cantidad, "
            "       COUNT(CASE WHEN v.estado_venta = 'Anulada' THEN 1 END) AS anuladas, "
            "       COALESCE(SUM(CASE WHEN v.estado_venta <> 'Anulada' THEN v.total_final END), 0) AS total, "
            "       COALESCE(SUM(CASE WHEN v.estado_venta <> 'Anulada' "
            "                          AND COALESCE(v.numero_venta, '') LIKE 'F%%' "
            "                         THEN v.total_final END), 0) AS fiado, "
            "       COALESCE(SUM(CASE WHEN v.estado_venta <> 'Anulada' "
            "                          AND COALESCE(v.numero_venta, '') NOT LIKE 'F%%' "
            "                          AND v.metodo_pago = 'Efectivo' "
            "                         THEN v.total_final END), 0) AS efectivo "
            f"FROM ventas v WHERE {where}",
            params,
        )
        fila = cur.fetchone() or {}
    finally:
        conn.close()

    cantidad = int(fila.get("cantidad") or 0)
    total = float(fila.get("total") or 0)
    fiado = float(fila.get("fiado") or 0)
    efectivo = float(fila.get("efectivo") or 0)
    return {
        "cantidad": cantidad,
        "anuladas": int(fila.get("anuladas") or 0),
        "total": round(total, 2),
        "efectivo": round(efectivo, 2),
        "fiado": round(fiado, 2),
        "otros": round(total - efectivo - fiado, 2),
        "ticket_promedio": round(total / cantidad, 2) if cantidad else 0.0,
    }


def _resumen_turno(cur, id_tienda: int, turno: dict) -> dict:
    """Desglose del arqueo del turno abierto, con el cursor de quien llama.

    El total se calcula sumando sus componentes, no leyendo
    `monto_final_esperado`, para que la cifra grande y el desglose que la
    acompana en pantalla no puedan contradecirse:

        esperado = base + ventas en efectivo + abonos en efectivo
                        - gastos pagados con la base o la caja menor

    La columna se sigue manteniendo transaccionalmente y se devuelve aparte
    como `esperado_registrado`. Difieren solo cuando hay filas que entraron a
    la base sin pasar por la aplicacion (una carga manual, un volcado), y en
    ese caso el calculo de aqui es el fiel: la columna nunca se entero de esos
    movimientos.

    Dos precisiones que cambian el resultado:

    * Las ventas en efectivo excluyen las que tienen abonos. Un fiado se
      guarda con metodo_pago 'Efectivo' y, al terminar de pagarse, su
      estado_venta pasa a 'Pagada'. Contarlo como venta ademas de contar sus
      abonos mete el mismo dinero dos veces en el arqueo.
    * Los abonos se filtran por `abonos_fiados.id_turno`, que se graba al
      registrarlos. Antes se deducian por fecha, y como `fecha_creacion` tiene
      precision de segundos, un abono hecho en el mismo segundo en que se abre
      un turno entraba en el arqueo de dos turnos distintos.
    """
    id_turno = turno["id_turno"]
    base = float(turno["monto_inicial"] or 0)

    cur.execute(
        "SELECT COALESCE(SUM(v.total_final), 0) AS total, "
        "       COALESCE(SUM(CASE WHEN v.metodo_pago = 'Efectivo' "
        "                          AND NOT EXISTS (SELECT 1 FROM abonos_fiados a "
        "                                          WHERE a.id_venta = v.id_venta) "
        "                         THEN v.total_final ELSE 0 END), 0) AS efectivo "
        "FROM ventas v "
        "WHERE v.id_tienda = %s AND v.id_turno = %s AND v.estado_venta = 'Pagada'",
        (id_tienda, id_turno),
    )
    ventas = cur.fetchone() or {}

    cur.execute(
        "SELECT COALESCE(SUM(a.monto_abonado), 0) AS efectivo "
        "FROM abonos_fiados a "
        "WHERE a.id_tienda = %s AND a.id_turno = %s AND a.metodo_pago = 'Efectivo'",
        (id_tienda, id_turno),
    )
    abonos = cur.fetchone() or {}

    marcadores = ", ".join(["%s"] * len(FUENTES_QUE_SALEN_DE_CAJA))
    cur.execute(
        "SELECT COALESCE(SUM(monto), 0) AS total, "
        f"       COALESCE(SUM(CASE WHEN fuente_dinero IN ({marcadores}) "
        "                         THEN monto ELSE 0 END), 0) AS de_caja, "
        "       COALESCE(SUM(CASE WHEN fuente_dinero = 'Base' "
        "                         THEN monto ELSE 0 END), 0) AS de_base "
        "FROM gastos_caja "
        "WHERE id_tienda = %s AND id_turno = %s",
        (*FUENTES_QUE_SALEN_DE_CAJA, id_tienda, id_turno),
    )
    gastos = cur.fetchone() or {}

    registrado = turno.get("monto_final_esperado")
    registrado = float(registrado) if registrado is not None else base

    ventas_efectivo = float(ventas.get("efectivo") or 0)
    abonos_efectivo = float(abonos.get("efectivo") or 0)
    gastos_de_caja = float(gastos.get("de_caja") or 0)
    total_esperado = round(base + ventas_efectivo + abonos_efectivo - gastos_de_caja, 2)

    return {
        "base": base,
        "ventas_total": float(ventas.get("total") or 0),
        "ventas_efectivo": ventas_efectivo,
        "abonos_efectivo": abonos_efectivo,
        "gastos_total": float(gastos.get("total") or 0),
        "gastos_de_caja": gastos_de_caja,
        "gastos_de_base": float(gastos.get("de_base") or 0),
        "total_esperado": total_esperado,
        "esperado_registrado": registrado,
    }


def get_turno_estado(id_tienda: int) -> dict | None:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno, fecha_apertura, monto_inicial, monto_final_esperado "
            "FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
            "ORDER BY fecha_apertura DESC LIMIT 1",
            (id_tienda,),
        )
        turno = cur.fetchone()
        if not turno:
            return None
        resumen = _resumen_turno(cur, id_tienda, turno)
    finally:
        conn.close()

    return {
        "id_turno": turno["id_turno"],
        "hora_apertura": turno["fecha_apertura"].strftime("%I:%M %p"),
        "monto_inicial": float(turno["monto_inicial"]),
        **resumen,
    }


def _hora(valor) -> str | None:
    return valor.strftime("%I:%M %p") if valor else None


def get_rendimiento_personal(id_tienda: int, max_ventas: int = 30) -> list[dict]:
    """Tarjetas del personal en el Panel de Control: lo de hoy, en vivo.

    Por trabajador activo: el turno que abrio (el abierto, o si no el ultimo
    de hoy), su hora y su base, el cuadre, y sus ventas de hoy con lo que
    llevo cada una.

    El turno es de la tienda (uno abierto a la vez) y lo firma quien lo abre,
    asi que el cuadre va en la tarjeta de quien lo abrio y cuenta todo el
    cajon. Sale de _resumen_turno, el mismo calculo del cierre: base + ventas
    en efectivo + abonos en efectivo - gastos pagados con la base o la caja
    menor. Abierto aun no hay conteo: "En curso" con lo esperado a esta hora.
    Cerrado: contado - esperado; cuadrada solo si la diferencia es 0.
    """
    hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_usuario, nombre_completo, rol FROM usuarios "
            "WHERE id_tienda = %s AND estado_activo = 1 AND rol IN ('Admin', 'Cajero') "
            "ORDER BY rol = 'Cajero' DESC, nombre_completo",
            (id_tienda,),
        )
        usuarios = cur.fetchall() or []
        if not usuarios:
            return []

        # Abiertos al final: el ultimo que se asigna por usuario es su turno
        # abierto si lo tiene, y si no el mas reciente de hoy.
        cur.execute(
            "SELECT id_turno, id_usuario_apertura, fecha_apertura, fecha_cierre, monto_inicial, "
            "       monto_final_esperado, monto_final_real, estado_turno "
            "FROM turnos_caja "
            "WHERE id_tienda = %s AND (estado_turno = 'Abierto' OR fecha_apertura >= %s) "
            "ORDER BY estado_turno = 'Abierto', fecha_apertura",
            (id_tienda, hoy),
        )
        turno_de = {t["id_usuario_apertura"]: t for t in cur.fetchall() or []}
        cuadres = {uid: _resumen_turno(cur, id_tienda, t) for uid, t in turno_de.items()}

        cur.execute(
            "SELECT v.id_venta, v.id_cajero, v.numero_venta, v.metodo_pago, v.estado_venta, "
            "       v.total_final, v.fecha_creacion, COALESCE(c.nombre, 'Mostrador') AS cliente "
            "FROM ventas v "
            "LEFT JOIN clientes c ON c.id_cliente = v.id_cliente AND c.id_tienda = v.id_tienda "
            "WHERE v.id_tienda = %s AND v.fecha_creacion >= %s "
            "ORDER BY v.id_venta DESC",
            (id_tienda, hoy),
        )
        ventas = cur.fetchall() or []

        cur.execute(
            "SELECT dv.id_venta, dv.cantidad, dv.unidad_venta, p.nombre "
            "FROM detalle_ventas dv "
            "INNER JOIN ventas v ON v.id_venta = dv.id_venta "
            "INNER JOIN productos p ON p.id_producto = dv.id_producto AND p.id_tienda = v.id_tienda "
            "WHERE v.id_tienda = %s AND v.fecha_creacion >= %s "
            "ORDER BY dv.id_detalle_venta",
            (id_tienda, hoy),
        )
        items_de: dict[int, list[str]] = {}
        for d in cur.fetchall() or []:
            unidad = d.get("unidad_venta")
            sufijo = f" {unidad}" if unidad and unidad != "Unidad" else ""
            items_de.setdefault(d["id_venta"], []).append(
                f"{float(d['cantidad']):g}{sufijo} x {d['nombre']}"
            )

        cur.execute(
            "SELECT id_usuario, COALESCE(SUM(monto), 0) AS total FROM gastos_caja "
            "WHERE id_tienda = %s AND fecha_creacion >= %s GROUP BY id_usuario",
            (id_tienda, hoy),
        )
        gastos_de = {g["id_usuario"]: float(g["total"] or 0) for g in cur.fetchall() or []}
    finally:
        conn.close()

    personal = []
    for u in usuarios:
        uid = u["id_usuario"]
        suyas = [v for v in ventas if v["id_cajero"] == uid]
        validas = [v for v in suyas if v["estado_venta"] != "Anulada"]
        resumen = {"cantidad": len(validas), "total": 0.0, "efectivo": 0.0, "otros": 0.0,
                   "fiado": 0.0, "anuladas": len(suyas) - len(validas)}
        detalle = []
        for v in suyas:
            metodo = _metodo_visible(v["numero_venta"], v["metodo_pago"])
            total = float(v["total_final"] or 0)
            if v["estado_venta"] != "Anulada":
                resumen["total"] += total
                clave = "fiado" if metodo == "Fiado" else "efectivo" if metodo == "Efectivo" else "otros"
                resumen[clave] += total
            if len(detalle) < max_ventas:
                detalle.append({
                    "hora": _hora(v["fecha_creacion"]),
                    "numero": v["numero_venta"] or f"#{v['id_venta']}",
                    "cliente": v["cliente"],
                    "metodo": metodo,
                    "estado": v["estado_venta"],
                    "total": total,
                    "items": ", ".join(items_de.get(v["id_venta"], [])),
                })

        turno = None
        t = turno_de.get(uid)
        if t:
            cuadre = cuadres[uid]
            abierto = t["estado_turno"] == "Abierto"
            contado = None if abierto or t["monto_final_real"] is None else float(t["monto_final_real"])
            diferencia = None if contado is None else round(contado - cuadre["total_esperado"], 2)
            turno = {
                "abierto": abierto,
                "apertura": _hora(t["fecha_apertura"]),
                "cierre": _hora(t["fecha_cierre"]),
                "base": cuadre["base"],
                "ventas_efectivo": cuadre["ventas_efectivo"],
                "abonos_efectivo": cuadre["abonos_efectivo"],
                "gastos_de_caja": cuadre["gastos_de_caja"],
                "gastos_de_base": cuadre["gastos_de_base"],
                "esperado": cuadre["total_esperado"],
                "contado": contado,
                "diferencia": diferencia,
                "estado": "En curso" if diferencia is None else "Cuadrada" if diferencia == 0 else "Descuadrada",
            }

        personal.append({
            "id": uid,
            "nombre": u["nombre_completo"],
            "rol": u["rol"],
            "en_turno": bool(turno and turno["abierto"]),
            "turno": turno,
            "ventas": {k: round(val, 2) if isinstance(val, float) else val for k, val in resumen.items()},
            "ultima_venta": _hora(suyas[0]["fecha_creacion"]) if suyas else None,
            "gastos_hoy": gastos_de.get(uid, 0.0),
            "detalle": detalle,
        })
    # En turno primero, luego quien mas ha vendido hoy.
    personal.sort(key=lambda p: (not p["en_turno"], -p["ventas"]["total"]))
    return personal


def abrir_turno(id_tienda: int, id_usuario: int, monto_inicial: float) -> int:
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        monto_inicial = parse_float(monto_inicial, "Monto inicial", min_value=0, allow_zero=False)
    except ValueError as exc:
        _raise_validation(exc)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' LIMIT 1",
            (id_tienda,),
        )
        if cur.fetchone():
            raise SalesConflictError("Ya hay un turno abierto para esta tienda.")

        cur.execute(
            "INSERT INTO turnos_caja "
            "(id_tienda, id_usuario_apertura, monto_inicial, monto_final_esperado) "
            "VALUES (%s, %s, %s, %s)",
            (id_tienda, id_usuario, monto_inicial, monto_inicial),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cerrar_turno(id_tienda: int, id_usuario: int, monto_final: float) -> dict:
    """Cierra el turno abierto y devuelve el arqueo.

    Devuelve el desglose ademas de cerrar para que la pantalla pueda decir si
    la caja quedo cuadrada sin tener que volver a pedirlo: despues del cierre
    ya no hay turno abierto que consultar.

    La diferencia se calcula contra el `monto_final_esperado` leido dentro de
    la misma transaccion que hace el UPDATE. Leerlo antes, fuera de ella,
    dejaria una ventana en la que una venta simultanea cambia el esperado y el
    cajero recibe un descuadre que no existe.
    """
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        monto_final = parse_float(monto_final, "Monto final", min_value=0)
    except ValueError as exc:
        _raise_validation(exc)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno, fecha_apertura, monto_inicial, monto_final_esperado "
            "FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
            "ORDER BY fecha_apertura DESC LIMIT 1 FOR UPDATE",
            (id_tienda,),
        )
        turno = cur.fetchone()
        if not turno:
            raise SalesNotFoundError("No hay turno abierto.")

        resumen = _resumen_turno(cur, id_tienda, turno)

        cur.execute(
            "UPDATE turnos_caja "
            "SET estado_turno = 'Cerrado', fecha_cierre = NOW(), "
            "    monto_final_real = %s, id_usuario_cierre = %s "
            "WHERE id_turno = %s",
            (monto_final, id_usuario, turno["id_turno"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    diferencia = round(monto_final - resumen["total_esperado"], 2)
    return {
        **resumen,
        "monto_reportado": monto_final,
        "diferencia": diferencia,
        # El redondeo a 2 decimales evita que un centavo de coma flotante
        # marque descuadre en una caja que en pesos esta perfecta.
        "cuadrado": diferencia == 0,
    }


_COLUMNAS_CAJA = (
    "SELECT id_producto, nombre, tipo, unidad_medida, codigo_barras, precio_venta, precio_mayorista, "
    "empaque_nombre, empaque_cantidad, precio_empaque, stock_actual FROM productos "
)


def get_caja_productos(id_tienda: int, q: str, mayorista: bool = False) -> list[dict]:
    """Resultados del buscador de Caja o de Venta Mayorista.

    En mayorista solo salen los productos con precio mayorista fijo y ese es el
    precio que viaja; sin empaque: al por mayor se vende por unidad de medida.
    """
    # Constante, no dato del usuario: el f-string no abre inyeccion.
    solo_mayorista = "AND precio_mayorista > 0 " if mayorista else ""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if q:
            cur.execute(
                _COLUMNAS_CAJA
                + "WHERE id_tienda = %s AND estado_activo = 1 "
                + solo_mayorista
                + "AND (nombre LIKE %s OR codigo_barras = %s) "
                "ORDER BY codigo_barras = %s DESC, nombre LIMIT 20",
                (id_tienda, f"%{q}%", q, q),
            )
        else:
            cur.execute(
                _COLUMNAS_CAJA
                + "WHERE id_tienda = %s AND estado_activo = 1 "
                + solo_mayorista
                + "ORDER BY nombre LIMIT 50",
                (id_tienda,),
            )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    productos = []
    for r in rows:
        empaque = None
        if not mayorista and r["empaque_nombre"] and r["empaque_cantidad"] and r["precio_empaque"]:
            empaque = {
                "nombre": r["empaque_nombre"],
                "cantidad": float(r["empaque_cantidad"]),
                "price": float(r["precio_empaque"]),
            }
        productos.append(
            {
                "id": r["id_producto"],
                "name": r["nombre"],
                "barcode": r.get("codigo_barras") or "",
                "price": float(r["precio_mayorista"] if mayorista else r["precio_venta"]),
                "stock": float(r["stock_actual"]) if r["stock_actual"] is not None else None,
                "servicio": r["tipo"] == "Servicio",
                "unidad": r["unidad_medida"],
                "fraccionable": r["unidad_medida"] in UNIDADES_FRACCIONABLES,
                "empaque": empaque,
            }
        )
    return productos


def registrar_venta(
    id_tienda: int,
    id_usuario: int,
    items: list,
    metodo_pago_ui: str,
    id_cliente,
    subtotal: float,
    monto_total: float,
    descuento: float,
    cliente: dict | None = None,
    mayorista: bool = False,
) -> dict:
    """Registra una venta de Caja o de Venta Mayorista.

    Cada item es {id, qty, pres}: `pres` es 'unidad' (unidad base, admite
    fraccion si la unidad lo permite) o 'empaque' (la presentacion cerrada,
    que descuenta empaque_cantidad del stock por cada una).

    Con `mayorista` el precio es el precio_mayorista fijo del producto y la
    venta exige un cliente B2B activo, que es lo que alimenta el dashboard
    del modulo Mayorista.
    """
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        if not isinstance(items, list) or not items:
            raise SalesValidationError("No hay productos en la venta.")
        if len(items) > 200:
            raise SalesValidationError("La venta supera el limite de items permitido.")
        subtotal = parse_float(subtotal, "Subtotal", min_value=0)
        monto_total = parse_float(monto_total, "Total", min_value=0)
        descuento = parse_float(descuento, "Descuento", min_value=0)
        if id_cliente not in (None, ""):
            id_cliente = parse_int(id_cliente, "Cliente", min_value=1)
        else:
            id_cliente = None
    except ValueError as exc:
        _raise_validation(exc)
    metodo_pago_db = normalize_payment_method(metodo_pago_ui, allow_fiado=True)
    if not metodo_pago_db:
        raise SalesValidationError("Metodo de pago invalido.")
    # Venta fiada = deuda del cliente. La columna metodo_pago es NOT NULL; se
    # guarda 'Efectivo' igual que sumar_fiado, pero no entra dinero a la caja.
    es_fiado = metodo_pago_db == "fiado"
    if es_fiado:
        metodo_pago_db = "Efectivo"

    conn = get_db()
    alertas_stock: list[str] = []
    claves_alerta: set[int] = set()

    try:
        cur = conn.cursor(dictionary=True)
        id_turno = _obtener_turno_abierto(id_tienda, cur)
        if not id_turno:
            raise SalesConflictError("Abre un turno antes de registrar ventas.")
        if mayorista:
            # El cliente mayorista ya existe: tambien un fiado va a su nombre,
            # sin pasar por el alta de clientes del modal "Fiar".
            if id_cliente is None:
                raise SalesValidationError("Selecciona el cliente mayorista.")
            cur.execute(
                "SELECT 1 FROM clientes WHERE id_cliente = %s AND id_tienda = %s "
                "AND estado_activo = 1 AND tipo = 'B2B' LIMIT 1",
                (id_cliente, id_tienda),
            )
            if not cur.fetchone():
                raise SalesNotFoundError("Cliente mayorista no encontrado.")
        elif es_fiado:
            id_cliente = _resolver_cliente_fiado(cur, id_tienda, cliente)
        elif id_cliente is not None:
            # Sin esto se podia colgar la venta de un cliente de otra tienda y
            # leer su nombre despues en el historial (IDOR por enumeracion).
            cur.execute(
                "SELECT 1 FROM clientes WHERE id_cliente = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
                (id_cliente, id_tienda),
            )
            if not cur.fetchone():
                raise SalesNotFoundError("Cliente no encontrado.")

        lineas_validas = []
        # Stock pedido por producto sumando lineas: el mismo producto puede
        # venir suelto y en empaque, y cada linea por separado cabria.
        consumo_por_producto: dict[int, float] = {}
        for item in items:
            try:
                id_producto = int(item["id"])
                cantidad = round(parse_float(item["qty"], "Cantidad"), 3)
            except (KeyError, TypeError, ValueError) as exc:
                raise SalesValidationError("Detalle de item invalido.") from exc
            presentacion = str(item.get("pres") or "unidad")

            if cantidad <= 0:
                raise SalesValidationError("La cantidad debe ser mayor a cero.")
            if id_producto <= 0:
                raise SalesValidationError("Producto invalido.")
            if presentacion not in ("unidad", "empaque"):
                raise SalesValidationError("Presentacion invalida.")

            cur.execute(
                "SELECT id_producto, nombre, tipo, unidad_medida, precio_venta, precio_mayorista, "
                "empaque_nombre, empaque_cantidad, precio_empaque, "
                "stock_actual, stock_minimo_alerta, COALESCE(es_preparado, 0) AS es_preparado "
                "FROM productos WHERE id_producto = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1 FOR UPDATE",
                (id_producto, id_tienda),
            )
            producto = cur.fetchone()
            if not producto:
                raise SalesNotFoundError("Producto no encontrado.")
            nombre_producto = producto.get("nombre") or "producto"

            # El precio lo pone la base, nunca el navegador: con item["price"]
            # un cajero podia cobrar $1 por cualquier producto.
            factor_stock = 1.0
            unidad_venta = producto["unidad_medida"]
            if mayorista:
                if presentacion == "empaque":
                    raise SalesValidationError("En venta mayorista se vende por unidad de medida.")
                precio = float(producto["precio_mayorista"] or 0)
                if precio <= 0:
                    raise SalesValidationError(f"{nombre_producto} no tiene precio mayorista.")
            elif presentacion == "empaque":
                if not (producto["empaque_nombre"] and producto["empaque_cantidad"] and producto["precio_empaque"]):
                    raise SalesValidationError(f"{nombre_producto} no se vende por empaque.")
                precio = float(producto["precio_empaque"])
                factor_stock = float(producto["empaque_cantidad"])
                unidad_venta = producto["empaque_nombre"]
            else:
                precio = float(producto["precio_venta"] or 0)

            fraccionable = presentacion == "unidad" and producto["unidad_medida"] in UNIDADES_FRACCIONABLES
            if not fraccionable and cantidad != int(cantidad):
                raise SalesValidationError(f"{nombre_producto} se vende por {unidad_venta} entero.")

            es_servicio = producto["tipo"] == "Servicio"
            consumo_stock = round(cantidad * factor_stock, 3)

            recetas = []
            if bool(producto.get("es_preparado") or 0):
                try:
                    cur.execute(
                        "SELECT rp.id_insumo, rp.cantidad_necesaria "
                        "FROM recetas_productos rp "
                        "INNER JOIN productos p ON p.id_producto = rp.id_producto "
                        "WHERE rp.id_producto = %s AND p.id_tienda = %s",
                        (id_producto, id_tienda),
                    )
                except Exception:
                    cur.execute(
                        "SELECT rp.id_insumo, rp.cantidad_requerida AS cantidad_necesaria "
                        "FROM recetas_productos rp "
                        "INNER JOIN productos p ON p.id_producto = rp.id_producto "
                        "WHERE rp.id_producto = %s AND p.id_tienda = %s",
                        (id_producto, id_tienda),
                    )
                recetas = cur.fetchall() or []

                for receta in recetas:
                    id_insumo = receta.get("id_insumo")
                    cantidad_necesaria = float(receta.get("cantidad_necesaria") or 0)
                    if not id_insumo or cantidad_necesaria <= 0:
                        continue

                    consumo_total = consumo_stock * cantidad_necesaria
                    cur.execute(
                        "SELECT nombre, stock_actual FROM insumos "
                        "WHERE id_insumo = %s AND id_tienda = %s LIMIT 1 FOR UPDATE",
                        (id_insumo, id_tienda),
                    )
                    insumo = cur.fetchone()
                    if not insumo:
                        raise SalesNotFoundError("Insumo de receta no encontrado.")
                    if float(insumo.get("stock_actual") or 0) < consumo_total:
                        raise SalesConflictError(
                            f"Stock insuficiente de insumo: {insumo.get('nombre') or 'Insumo'}"
                        )
            elif not es_servicio:
                consumo_por_producto[id_producto] = round(
                    consumo_por_producto.get(id_producto, 0.0) + consumo_stock, 3
                )
                stock_actual = float(producto.get("stock_actual") or 0)
                if stock_actual < consumo_por_producto[id_producto]:
                    raise SalesConflictError(f"Stock insuficiente para {nombre_producto}")

            lineas_validas.append(
                {
                    "id_producto": id_producto,
                    "cantidad": cantidad,
                    "precio": precio,
                    "subtotal": round(precio * cantidad, 2),
                    "unidad_venta": unidad_venta,
                    "consumo_stock": consumo_stock,
                    "es_servicio": es_servicio,
                    "producto": producto,
                    "recetas": recetas,
                }
            )

        # Totales recalculados en el servidor; los del navegador se ignoran.
        # `descuento` no se resta: la caja no tiene descuento manual y restarlo
        # dejaria cobrar $0 con discount=subtotal. Solo alimenta la auditoria.
        # Tampoco hay descuento porcentual mayorista: el precio mayorista es un
        # valor fijo por producto, ya aplicado linea a linea.
        subtotal = round(sum(l["subtotal"] for l in lineas_validas), 2)
        monto_total = subtotal

        notas = []
        if mayorista:
            notas.append("Venta mayorista")
        if es_fiado:
            notas.append("Fiado desde caja")
        observaciones = " | ".join(notas)[:255] or None

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
            (id_tienda,),
        )
        consecutivo = cur.fetchone()["cnt"]
        numero_venta = f"{'F' if es_fiado else 'V'}{id_tienda:04d}-{consecutivo + 1:06d}"

        cur.execute(
            "INSERT INTO ventas "
            "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
            " subtotal, tipo_descuento, valor_descuento, descuento_aplicado, "
            " total_final, metodo_pago, estado_venta, observaciones) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                id_tienda,
                id_turno,
                id_usuario,
                id_cliente,
                numero_venta,
                subtotal,
                "NINGUNO",
                0,
                0,
                monto_total,
                metodo_pago_db,
                "Fiada/Pendiente" if es_fiado else "Pagada",
                observaciones,
            ),
        )
        id_venta = cur.lastrowid

        for linea in lineas_validas:
            id_producto = linea["id_producto"]
            consumo_stock = linea["consumo_stock"]

            cur.execute(
                "INSERT INTO detalle_ventas "
                "(id_venta, id_producto, cantidad, unidad_venta, precio_unitario_historico, subtotal_linea) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (id_venta, id_producto, linea["cantidad"], linea["unidad_venta"], linea["precio"], linea["subtotal"]),
            )

            if linea["es_servicio"]:
                continue
            if bool(linea["producto"].get("es_preparado") or 0):
                for receta in linea["recetas"]:
                    id_insumo = receta.get("id_insumo")
                    cantidad_necesaria = float(receta.get("cantidad_necesaria") or 0)
                    if not id_insumo or cantidad_necesaria <= 0:
                        continue
                    consumo_total = consumo_stock * cantidad_necesaria
                    cur.execute(
                        "UPDATE insumos SET stock_actual = stock_actual - %s "
                        "WHERE id_insumo = %s AND id_tienda = %s",
                        (consumo_total, id_insumo, id_tienda),
                    )
            else:
                cur.execute(
                    "UPDATE productos SET stock_actual = stock_actual - %s "
                    "WHERE id_producto = %s AND id_tienda = %s",
                    (consumo_stock, id_producto, id_tienda),
                )

                cur.execute(
                    "SELECT nombre, unidad_medida, stock_actual, stock_minimo_alerta "
                    "FROM productos WHERE id_producto = %s AND id_tienda = %s LIMIT 1",
                    (id_producto, id_tienda),
                )
                producto_actualizado = cur.fetchone()
                if producto_actualizado:
                    stock_actual = float(producto_actualizado.get("stock_actual") or 0)
                    stock_minimo = float(producto_actualizado.get("stock_minimo_alerta") or 0)
                    if stock_minimo > 0 and stock_actual <= stock_minimo:
                        if id_producto not in claves_alerta:
                            claves_alerta.add(id_producto)
                            alertas_stock.append(
                                f"Stock bajo: {producto_actualizado.get('nombre') or 'Producto'} "
                                f"({stock_actual:g} {producto_actualizado.get('unidad_medida') or 'und'})."
                            )

        if metodo_pago_db == "Efectivo" and not es_fiado:
            cur.execute(
                "UPDATE turnos_caja "
                "SET monto_final_esperado = COALESCE(monto_final_esperado, monto_inicial, 0) + %s "
                "WHERE id_turno = %s",
                (monto_total, id_turno),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if descuento >= 20000:
        _registrar_auditoria(
            id_tienda,
            id_usuario,
            "descuento_manual_alto",
            f"Venta {numero_venta}: descuento manual de {descuento}",
        )

    return {
        "id_venta": id_venta,
        "numero_venta": numero_venta,
        "id_cliente": id_cliente,
        "stock_alerts": alertas_stock,
        "total_final": monto_total,
    }


def _metodo_visible(numero_venta: str | None, metodo_pago: str | None) -> str:
    """Metodo de pago tal como lo entiende quien lee la factura.

    Un fiado se guarda con metodo_pago 'Efectivo' (la columna es NOT NULL) pero
    no entro dinero al cobrarlo: se reconoce por el prefijo F del consecutivo,
    que ponen todos los caminos que crean deuda.
    """
    if str(numero_venta or "").startswith("F"):
        return "Fiado"
    return metodo_pago or "Efectivo"


def get_detalle_venta(id_tienda: int, id_venta: int) -> dict:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT v.id_venta, v.numero_venta, v.subtotal, v.total_final, v.metodo_pago, "
            "       v.estado_venta, v.fecha_creacion, v.observaciones, "
            "       COALESCE(c.nombre, 'Mostrador') AS cliente, c.nit, "
            "       u.nombre_completo AS cajero "
            "FROM ventas v "
            "LEFT JOIN clientes c ON c.id_cliente = v.id_cliente AND c.id_tienda = v.id_tienda "
            "LEFT JOIN usuarios u ON u.id_usuario = v.id_cajero "
            "WHERE v.id_venta = %s AND v.id_tienda = %s "
            "LIMIT 1",
            (id_venta, id_tienda),
        )
        venta = cur.fetchone()
        if not venta:
            raise SalesNotFoundError("Venta no encontrada.")

        cur.execute(
            "SELECT p.nombre AS producto, dv.cantidad, dv.unidad_venta, "
            "       dv.precio_unitario_historico, dv.subtotal_linea "
            "FROM detalle_ventas dv "
            "INNER JOIN ventas v ON v.id_venta = dv.id_venta "
            "INNER JOIN productos p ON p.id_producto = dv.id_producto AND p.id_tienda = v.id_tienda "
            "WHERE dv.id_venta = %s AND v.id_tienda = %s "
            "ORDER BY dv.id_detalle_venta ASC",
            (id_venta, id_tienda),
        )
        filas = cur.fetchall() or []

        metodo = _metodo_visible(venta["numero_venta"], venta["metodo_pago"])
        if metodo == "Fiado":
            # Si ya se abono, la factura dice con que se fue pagando la deuda.
            cur.execute(
                "SELECT DISTINCT metodo_pago FROM abonos_fiados "
                "WHERE id_venta = %s AND id_tienda = %s ORDER BY metodo_pago",
                (id_venta, id_tienda),
            )
            abonos = [r["metodo_pago"] for r in (cur.fetchall() or []) if r["metodo_pago"]]
            if abonos:
                metodo += f" (abonos: {', '.join(abonos)})"
    finally:
        conn.close()

    detalles = [
        {
            "producto": f.get("producto") or "Producto",
            "cantidad": float(f.get("cantidad") or 0),
            "unidad": f.get("unidad_venta") or "",
            "precio_unitario": float(f.get("precio_unitario_historico") or 0),
            "subtotal": float(f.get("subtotal_linea") or 0),
        }
        for f in filas
    ]
    fecha = venta.get("fecha_creacion")
    return {
        "id_venta": venta["id_venta"],
        "numero_venta": venta.get("numero_venta") or f"V-{venta['id_venta']}",
        "fecha": fecha.strftime("%Y-%m-%d %H:%M") if fecha else "",
        "cliente": venta.get("cliente") or "Mostrador",
        "nit": venta.get("nit") or "",
        "cajero": venta.get("cajero") or "",
        "metodo_pago": metodo,
        "estado": venta.get("estado_venta") or "Pagada",
        "mayorista": "Venta mayorista" in (venta.get("observaciones") or ""),
        "items": detalles,
        "subtotal": float(venta.get("subtotal") or 0),
        "total": float(venta.get("total_final") or 0),
    }


def crear_cliente_fiado(id_tienda: int, id_usuario: int, nombre: str, telefono: str, deuda_inicial: float) -> int:
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        nombre = sanitize_text(nombre, "El nombre del cliente", max_len=150)
        telefono_raw = str(telefono or "").strip()
        telefono_digits = only_digits(telefono_raw)
        if not telefono_digits:
            raise SalesValidationError("El telefono es requerido.")
        if len(telefono_digits) < 7 or len(telefono_digits) > 25:
            raise SalesValidationError("El telefono es invalido.")
        deuda_inicial = parse_float(deuda_inicial, "Deuda inicial", min_value=0)
    except ValueError as exc:
        _raise_validation(exc)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        id_turno = None
        if deuda_inicial > 0:
            id_turno = _obtener_turno_abierto(id_tienda, cur)
            if not id_turno:
                raise SalesConflictError("Debes abrir un turno para registrar deuda inicial.")

        cur.execute(
            "INSERT INTO clientes (id_tienda, nombre, telefono) VALUES (%s, %s, %s)",
            (id_tienda, nombre, telefono_digits),
        )
        nuevo_id = cur.lastrowid

        if deuda_inicial > 0:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
                (id_tienda,),
            )
            cnt = cur.fetchone()["cnt"]
            numero_venta = f"F{id_tienda:04d}-{cnt + 1:06d}"

            cur.execute(
                "INSERT INTO ventas "
                "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
                " subtotal, total_final, metodo_pago, estado_venta, observaciones) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'Efectivo','Fiada/Pendiente',%s)",
                (
                    id_tienda,
                    id_turno,
                    id_usuario,
                    nuevo_id,
                    numero_venta,
                    deuda_inicial,
                    deuda_inicial,
                    "Saldo inicial",
                ),
            )

        conn.commit()
        return nuevo_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_cliente_fiado(id_tienda: int, id_usuario: int, id_cliente: int) -> None:
    """Soft delete a fiado client preserving historical sales integrity."""
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        id_cliente = parse_int(id_cliente, "Cliente", min_value=1)
    except ValueError as exc:
        _raise_validation(exc)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE clientes SET estado_activo = 0 "
            "WHERE id_cliente = %s AND id_tienda = %s AND estado_activo = 1",
            (id_cliente, id_tienda),
        )
        if cur.rowcount == 0:
            raise SalesNotFoundError("Cliente no encontrado.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _registrar_auditoria(id_tienda, id_usuario, "eliminar_cliente", f"Cliente desactivado id={id_cliente}")


def sumar_fiado(id_tienda: int, id_usuario: int, id_cliente: int, monto: float, concepto: str) -> None:
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        id_cliente = parse_int(id_cliente, "Cliente", min_value=1)
        monto = parse_float(monto, "Monto", min_value=0, allow_zero=False)
        concepto = sanitize_text(concepto, "El concepto", max_len=255)
    except ValueError as exc:
        _raise_validation(exc)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_cliente FROM clientes "
            "WHERE id_cliente = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
            (id_cliente, id_tienda),
        )
        if not cur.fetchone():
            raise SalesNotFoundError("Cliente no encontrado.")

        id_turno = _obtener_turno_abierto(id_tienda, cur)
        if not id_turno:
            raise SalesConflictError("No hay turno abierto.")

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
            (id_tienda,),
        )
        cnt = cur.fetchone()["cnt"]
        numero_venta = f"F{id_tienda:04d}-{cnt + 1:06d}"

        cur.execute(
            "INSERT INTO ventas "
            "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
            " subtotal, total_final, metodo_pago, estado_venta, observaciones) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'Efectivo','Fiada/Pendiente',%s)",
            (id_tienda, id_turno, id_usuario, id_cliente, numero_venta, monto, monto, concepto),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def abonar_fiado(id_tienda: int, id_usuario: int, id_cliente: int, monto: float, metodo_ui: str) -> None:
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        id_cliente = parse_int(id_cliente, "Cliente", min_value=1)
        monto = parse_float(monto, "Monto", min_value=0, allow_zero=False)
    except ValueError as exc:
        _raise_validation(exc)
    metodo = normalize_payment_method(metodo_ui)
    if not metodo:
        raise SalesValidationError("Metodo invalido.")

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_cliente FROM clientes "
            "WHERE id_cliente = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
            (id_cliente, id_tienda),
        )
        if not cur.fetchone():
            raise SalesNotFoundError("Cliente no encontrado.")

        cur.execute(
            "SELECT v.id_venta, v.total_final, "
            "COALESCE((SELECT SUM(ab.monto_abonado) FROM abonos_fiados ab "
            "WHERE ab.id_venta = v.id_venta), 0) AS abonado "
            "FROM ventas v "
            "WHERE v.id_cliente = %s AND v.id_tienda = %s "
            "AND v.estado_venta = 'Fiada/Pendiente' "
            "ORDER BY v.id_venta ASC LIMIT 1",
            (id_cliente, id_tienda),
        )
        venta = cur.fetchone()
        if not venta:
            raise SalesNotFoundError("Este cliente no tiene deuda pendiente.")

        deuda_actual = max(0.0, float(venta.get("total_final") or 0) - float(venta.get("abonado") or 0))
        if monto <= 0 or monto > deuda_actual:
            raise SalesValidationError("El monto debe ser mayor a 0 y no puede superar la deuda actual.")

        # El turno se resuelve ANTES de insertar para poder grabarlo en la
        # fila. El arqueo lo lee de ahi en vez de deducirlo por fecha:
        # fecha_creacion tiene precision de segundos y un abono hecho en el
        # mismo segundo en que se abre un turno caia dentro de la ventana de
        # dos turnos, contando el mismo dinero dos veces.
        id_turno = _obtener_turno_abierto(id_tienda, cur)
        if metodo == "Efectivo" and not id_turno:
            raise SalesConflictError("No hay turno abierto para registrar abonos en efectivo.")

        cur.execute(
            "INSERT INTO abonos_fiados "
            "(id_tienda, id_venta, id_turno, id_usuario, monto_abonado, metodo_pago) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (id_tienda, venta["id_venta"], id_turno, id_usuario, monto, metodo),
        )

        if metodo == "Efectivo":
            cur.execute(
                "UPDATE turnos_caja "
                "SET monto_final_esperado = COALESCE(monto_final_esperado, monto_inicial, 0) + %s "
                "WHERE id_turno = %s",
                (monto, id_turno),
            )

        if float(venta["abonado"]) + monto >= float(venta["total_final"]):
            cur.execute(
                "UPDATE ventas SET estado_venta = 'Pagada' "
                "WHERE id_venta = %s AND id_tienda = %s",
                (venta["id_venta"], id_tienda),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_gastos(
    id_tienda: int,
    id_usuario: int,
    filtro: str | None = None,
    fecha: str | None = None,
    page=1,
    limit=20,
) -> tuple[list[dict], str, dict, dict]:
    """Pagina de gastos del usuario + filtro, metadatos y totales.

    Los totales de hoy y del mes se calculan en SQL sobre todos los gastos, no
    sobre la pagina: con paginacion el frontend ya no puede sumarlos.
    """
    page, limit = paginacion(page, limit)
    filtro_final, desde, hasta = periodo_bounds(filtro, fecha)

    # Base = alcance del usuario (no negociable). Periodo = la capsula elegida.
    where_base = "gc.id_tienda = %s AND gc.id_usuario = %s"
    params_base: tuple = (id_tienda, id_usuario)

    where = where_base
    parametros = params_base
    if desde is not None:
        where += " AND gc.fecha_creacion >= %s AND gc.fecha_creacion < %s"
        parametros = params_base + (desde, hasta)

    ahora = datetime.now()
    inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_mes = inicio_dia.replace(day=1)
    fin_dia = inicio_dia + timedelta(days=1)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(f"SELECT COUNT(*) AS total FROM gastos_caja gc WHERE {where}", parametros)
        total = int((cur.fetchone() or {}).get("total") or 0)

        meta = _meta_paginacion(total, page, limit)
        cur.execute(
            "SELECT gc.id_gasto, gc.concepto, gc.descripcion, gc.monto, gc.fuente_dinero, "
            "UNIX_TIMESTAMP(gc.fecha_creacion) * 1000 AS ts "
            f"FROM gastos_caja gc WHERE {where} "
            "ORDER BY gc.id_gasto DESC LIMIT %s OFFSET %s",
            parametros + (meta["limit"], meta["offset"]),
        )
        filas = cur.fetchall() or []

        # Tarjetas de resumen: sobre TODOS los gastos del usuario, sin la capsula,
        # para que "Gastos de Hoy" no quede en 0 al filtrar por Ayer.
        cur.execute(
            "SELECT "
            "  COALESCE(SUM(CASE WHEN gc.fecha_creacion >= %s AND gc.fecha_creacion < %s "
            "                    THEN gc.monto ELSE 0 END), 0) AS hoy, "
            "  COALESCE(SUM(CASE WHEN gc.fecha_creacion >= %s AND gc.fecha_creacion < %s "
            "                    THEN gc.monto ELSE 0 END), 0) AS mes "
            "FROM gastos_caja gc "
            f"WHERE {where_base}",
            (inicio_dia, fin_dia, inicio_mes, fin_dia) + params_base,
        )
        sumas = cur.fetchone() or {}
    finally:
        conn.close()

    gastos = [
        {
            "id": r["id_gasto"],
            "category": r["concepto"],
            "desc": str(r.get("descripcion") or "").strip(),
            "origen": r.get("fuente_dinero") or "Bancos",
            "amount": float(r["monto"]),
            "ts": int(r["ts"] or 0),
        }
        for r in filas
    ]
    totales = {
        "hoy": float(sumas.get("hoy") or 0),
        "mes": float(sumas.get("mes") or 0),
    }
    return gastos, filtro_final, meta, totales


# Fuentes de dinero de un gasto.
#
# Las dos que salen del cajon fisico y por tanto mueven el cuadre del turno:
#   Base       -> el cajero pago con los billetes de la apertura
#   Caja Menor -> salio del efectivo acumulado durante el turno
# Las otras dos no tocan el cajon: 'Caja Fuerte' y 'Bancos'.
FUENTES_DINERO = ("Caja Menor", "Caja Fuerte", "Bancos", "Base")

# Subconjunto que descuenta del efectivo esperado al cerrar. Se define aparte
# para que la regla viva en un solo sitio: insertar_gasto la usa para decidir
# si baja monto_final_esperado, y get_turno_resumen para sumar los gastos que
# el cajero vera restados en su arqueo. Si divergen, el arqueo miente.
FUENTES_QUE_SALEN_DE_CAJA = ("Base", "Caja Menor")


def insertar_gasto(
    cur,
    id_tienda: int,
    id_usuario: int,
    concepto: str,
    descripcion: str | None,
    metodo_pago: str,
    fuente_dinero: str,
    monto: float,
) -> int:
    """Inserta el gasto usando el cursor de quien llama, sin commit.

    Existe aparte de crear_gasto para que otra operacion (el pago de una cuenta
    por pagar) pueda registrar su gasto DENTRO de la misma transaccion: si algo
    falla despues, el gasto tampoco queda.

    Quien llama valida y sanitiza antes; aqui solo se comprueba la fuente contra
    el enum de la tabla y se resuelve el turno.
    """
    if fuente_dinero not in FUENTES_DINERO:
        raise SalesValidationError("Fuente de dinero invalida.")

    id_turno = _obtener_turno_abierto(id_tienda, cur)

    sale_de_caja = metodo_pago == "Efectivo" and fuente_dinero in FUENTES_QUE_SALEN_DE_CAJA
    if sale_de_caja and not id_turno:
        raise SalesConflictError(
            f"No hay turno activo para cargar gastos de {fuente_dinero}."
        )

    if not id_turno:
        cur.execute(
            "SELECT id_turno FROM turnos_caja "
            "WHERE id_tienda = %s "
            "ORDER BY fecha_apertura DESC LIMIT 1",
            (id_tienda,),
        )
        fila_turno = cur.fetchone()
        if not fila_turno:
            raise SalesConflictError("No existe ningun turno para registrar el gasto.")
        id_turno = fila_turno["id_turno"]

    cur.execute(
        "INSERT INTO gastos_caja "
        "(id_tienda, id_turno, id_usuario, concepto, descripcion, monto, fuente_dinero) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (id_tienda, id_turno, id_usuario, concepto, descripcion, monto, fuente_dinero),
    )
    nuevo_id = int(cur.lastrowid or 0)

    if sale_de_caja:
        # Un gasto pagado con la base o con la caja menor saca billetes del
        # cajon, asi que baja el efectivo que debe aparecer en el arqueo.
        # 'Caja Fuerte' y 'Bancos' no entran aqui: ese dinero nunca estuvo en
        # el cajon del turno.
        cur.execute(
            "UPDATE turnos_caja "
            "SET monto_final_esperado = COALESCE(monto_final_esperado, monto_inicial, 0) - %s "
            "WHERE id_turno = %s AND id_tienda = %s",
            (monto, id_turno, id_tienda),
        )

    return nuevo_id


def crear_gasto(
    id_tienda: int,
    id_usuario: int,
    concepto: str,
    descripcion: str,
    metodo_pago: str,
    fuente_dinero: str,
    monto: float,
) -> int:
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        concepto = sanitize_text(concepto, "La categoria", max_len=150)
        descripcion = sanitize_optional_text(descripcion, "La descripcion", max_len=255)
        fuente_dinero = sanitize_text(fuente_dinero, "Fuente de dinero", max_len=20)
        if fuente_dinero not in FUENTES_DINERO:
            raise SalesValidationError("Fuente de dinero invalida.")
        monto = parse_float(monto, "Monto", min_value=0, allow_zero=False)
    except ValueError as exc:
        _raise_validation(exc)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        nuevo_id = insertar_gasto(
            cur, id_tienda, id_usuario, concepto, descripcion, metodo_pago, fuente_dinero, monto
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _registrar_auditoria(
        id_tienda,
        id_usuario,
        "registrar_gasto",
        f"Gasto id={nuevo_id}, categoria={concepto}, monto={monto}, fuente={fuente_dinero}",
    )
    return nuevo_id
