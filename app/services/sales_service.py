from __future__ import annotations

from datetime import date, datetime, timedelta

from mysql.connector import IntegrityError

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


def get_dashboard_financial_summary(id_tienda: int, since: datetime, until: datetime) -> dict:
    flow = get_money_flow_summary(id_tienda, since, until)
    ventas = float(flow["entradas"])
    gastos = float(flow["salidas"])

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        cur.execute(
            "SELECT DATE(v.fecha_creacion) AS d, COALESCE(SUM(v.total_final),0) AS total "
            "FROM ventas v "
            "WHERE v.id_tienda=%s AND v.estado_venta='Pagada' "
            "AND v.fecha_creacion >= %s AND v.fecha_creacion < %s "
            "GROUP BY DATE(v.fecha_creacion) "
            "ORDER BY DATE(v.fecha_creacion)",
            (id_tienda, since, until),
        )
        ingresos_por_dia = {r["d"]: float(r["total"] or 0) for r in cur.fetchall()}

        cur.execute(
            "SELECT DATE(g.fecha_creacion) AS d, COALESCE(SUM(g.monto),0) AS total "
            "FROM gastos_caja g "
            "WHERE g.id_tienda=%s AND g.fecha_creacion >= %s AND g.fecha_creacion < %s "
            "GROUP BY DATE(g.fecha_creacion) "
            "ORDER BY DATE(g.fecha_creacion)",
            (id_tienda, since, until),
        )
        gastos_por_dia = {r["d"]: float(r["total"] or 0) for r in cur.fetchall()}
    finally:
        conn.close()

    chart_labels: list[str] = []
    chart_ingresos: list[float] = []
    chart_gastos: list[float] = []
    d = since.date()
    end_day = until.date()
    while d <= end_day:
        chart_labels.append(d.strftime("%d/%m"))
        chart_ingresos.append(ingresos_por_dia.get(d, 0.0))
        chart_gastos.append(gastos_por_dia.get(d, 0.0))
        d += timedelta(days=1)

    return {
        "ventas": ventas,
        "gastos": gastos,
        "chart": {
            "labels": chart_labels,
            "ingresos": chart_ingresos,
            "gastos": chart_gastos,
        },
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

PERIODOS = ("hoy", "ayer", "semana", "mes", "todas")


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
) -> tuple[list[dict], str, dict]:
    """Pagina del historial de ventas + filtro aplicado + metadatos del paginador.

    El Cajero sigue viendo solo sus propias ventas de las ultimas 24 horas: las
    capsulas y el buscador de fecha se ignoran para ese rol.
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
            "SELECT v.id_venta, v.total_final, v.estado_venta, v.fecha_creacion, "
            "COALESCE(c.nombre, 'Mostrador') AS nombre_cliente, "
            "u.nombre_completo AS nombre_cajero "
            "FROM ventas v "
            "LEFT JOIN clientes c ON v.id_cliente = c.id_cliente "
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
        }
        for fila in filas
    ]
    return lista, filtro_final, meta


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


def get_caja_productos(id_tienda: int, q: str) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if q:
            cur.execute(
                "SELECT id_producto, nombre, codigo_barras, precio_venta, stock_actual "
                "FROM productos "
                "WHERE id_tienda = %s AND estado_activo = 1 "
                "AND (nombre LIKE %s OR codigo_barras = %s) "
                "ORDER BY codigo_barras = %s DESC, nombre LIMIT 20",
                (id_tienda, f"%{q}%", q, q),
            )
        else:
            cur.execute(
                "SELECT id_producto, nombre, codigo_barras, precio_venta, stock_actual "
                "FROM productos "
                "WHERE id_tienda = %s AND estado_activo = 1 "
                "ORDER BY nombre LIMIT 50",
                (id_tienda,),
            )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        {
            "id": r["id_producto"],
            "name": r["nombre"],
            "barcode": r.get("codigo_barras") or "",
            "price": float(r["precio_venta"]),
            "stock": r["stock_actual"],
        }
        for r in rows
    ]


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
) -> dict:
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
        if es_fiado:
            id_cliente = _resolver_cliente_fiado(cur, id_tienda, cliente)

        lineas_validas = []
        for item in items:
            try:
                id_producto = int(item["id"])
                cantidad = float(item["qty"])
                precio = float(item["price"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SalesValidationError("Detalle de item invalido.") from exc

            if cantidad <= 0:
                raise SalesValidationError("La cantidad debe ser mayor a cero.")
            if precio < 0:
                raise SalesValidationError("El precio no puede ser negativo.")
            if id_producto <= 0:
                raise SalesValidationError("Producto invalido.")

            cur.execute(
                "SELECT id_producto, nombre, stock_actual, stock_minimo_alerta, COALESCE(es_preparado, 0) AS es_preparado "
                "FROM productos WHERE id_producto = %s AND id_tienda = %s LIMIT 1 FOR UPDATE",
                (id_producto, id_tienda),
            )
            producto = cur.fetchone()
            if not producto:
                raise SalesNotFoundError("Producto no encontrado.")

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

                    consumo_total = cantidad * cantidad_necesaria
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
            else:
                stock_actual = float(producto.get("stock_actual") or 0)
                if stock_actual < cantidad:
                    raise SalesConflictError(
                        f"Stock insuficiente para {producto.get('nombre') or 'producto'}"
                    )

            lineas_validas.append(
                {
                    "id_producto": id_producto,
                    "cantidad": cantidad,
                    "precio": precio,
                    "producto": producto,
                    "recetas": recetas,
                }
            )

        # Descuento mayorista B2B: se resuelve en el servidor a partir de la
        # lista asignada al cliente. El navegador nunca decide el porcentaje.
        # Import local: cartera_service importa de este modulo.
        from app.services.cartera_service import descuento_b2b_para_venta

        descuento_b2b = descuento_b2b_para_venta(cur, id_tienda, id_cliente)
        if descuento_b2b:
            monto_b2b = round(monto_total * descuento_b2b["pct"] / 100, 2)
            monto_total = max(0.0, round(monto_total - monto_b2b, 2))
        else:
            monto_b2b = 0.0

        notas = []
        if es_fiado:
            notas.append("Fiado desde caja")
        if descuento_b2b:
            notas.append(f"Mayorista {descuento_b2b['nombre']} -{descuento_b2b['pct']:g}%")
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
                "PORCENTAJE" if descuento_b2b else "NINGUNO",
                descuento_b2b["pct"] if descuento_b2b else 0,
                monto_b2b,
                monto_total,
                metodo_pago_db,
                "Fiada/Pendiente" if es_fiado else "Pagada",
                observaciones,
            ),
        )
        id_venta = cur.lastrowid

        for linea in lineas_validas:
            id_producto = linea["id_producto"]
            cantidad = linea["cantidad"]
            precio = linea["precio"]

            cur.execute(
                "INSERT INTO detalle_ventas "
                "(id_venta, id_producto, cantidad, precio_unitario_historico, subtotal_linea) "
                "VALUES (%s,%s,%s,%s,%s)",
                (id_venta, id_producto, cantidad, precio, precio * cantidad),
            )

            if bool(linea["producto"].get("es_preparado") or 0):
                for receta in linea["recetas"]:
                    id_insumo = receta.get("id_insumo")
                    cantidad_necesaria = float(receta.get("cantidad_necesaria") or 0)
                    if not id_insumo or cantidad_necesaria <= 0:
                        continue
                    consumo_total = cantidad * cantidad_necesaria
                    cur.execute(
                        "UPDATE insumos SET stock_actual = stock_actual - %s "
                        "WHERE id_insumo = %s AND id_tienda = %s",
                        (consumo_total, id_insumo, id_tienda),
                    )
            else:
                cur.execute(
                    "UPDATE productos SET stock_actual = stock_actual - %s "
                    "WHERE id_producto = %s AND id_tienda = %s",
                    (cantidad, id_producto, id_tienda),
                )

                cur.execute(
                    "SELECT nombre, stock_actual, stock_minimo_alerta "
                    "FROM productos WHERE id_producto = %s AND id_tienda = %s LIMIT 1",
                    (id_producto, id_tienda),
                )
                producto_actualizado = cur.fetchone()
                if producto_actualizado:
                    stock_actual = int(producto_actualizado.get("stock_actual") or 0)
                    stock_minimo = int(producto_actualizado.get("stock_minimo_alerta") or 0)
                    if stock_minimo > 0 and stock_actual <= stock_minimo:
                        if id_producto not in claves_alerta:
                            claves_alerta.add(id_producto)
                            alertas_stock.append(
                                f"Stock bajo: {producto_actualizado.get('nombre') or 'Producto'} ({stock_actual} und)."
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
        "descuento_b2b": monto_b2b,
        "lista_b2b": descuento_b2b["nombre"] if descuento_b2b else "",
    }


def get_detalle_venta(id_tienda: int, id_venta: int) -> dict:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_venta, numero_venta, total_final "
            "FROM ventas "
            "WHERE id_venta = %s AND id_tienda = %s "
            "LIMIT 1",
            (id_venta, id_tienda),
        )
        venta = cur.fetchone()
        if not venta:
            raise SalesNotFoundError("Venta no encontrada.")

        cur.execute(
            "SELECT p.nombre AS producto, dv.cantidad, dv.subtotal_linea "
            "FROM detalle_ventas dv "
            "INNER JOIN ventas v ON v.id_venta = dv.id_venta "
            "INNER JOIN productos p ON p.id_producto = dv.id_producto AND p.id_tienda = v.id_tienda "
            "WHERE dv.id_venta = %s AND v.id_tienda = %s "
            "ORDER BY dv.id_detalle_venta ASC",
            (id_venta, id_tienda),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    detalles = [
        {
            "producto": f.get("producto") or "Producto",
            "cantidad": float(f.get("cantidad") or 0),
            "subtotal": float(f.get("subtotal_linea") or 0),
        }
        for f in filas
    ]
    return {
        "id_venta": venta["id_venta"],
        "numero_venta": venta.get("numero_venta") or f"V-{venta['id_venta']}",
        "items": detalles,
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
