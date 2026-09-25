"""cartera_service.py — Cartera del negocio y clientes B2B.

Dos dominios que comparten la misma pantalla de Cartera:

  * Cuentas por cobrar: la deuda de clientes sigue viviendo en `ventas`
    (estado 'Fiada/Pendiente') + `abonos_fiados`; aqui solo se agregan los
    indicadores de mora y la vista B2B. Ver sales_service.get_fiados_clientes.
  * Cuentas por pagar: obligaciones del negocio en `cuentas_por_pagar`.

Todas las consultas van parametrizadas (%s) y filtradas por id_tienda, que
siempre llega de la sesion del servidor, nunca del cliente.
"""

from __future__ import annotations

from datetime import date, datetime

from mysql.connector import IntegrityError

from app.services.sales_service import (
    SalesConflictError,
    SalesNotFoundError,
    SalesValidationError,
    _registrar_auditoria as registrar_auditoria,
    insertar_gasto,
)
from app.utils.helpers import only_digits
from app.utils.validation import parse_float, parse_int, sanitize_optional_text, sanitize_text
from database import get_db

CATEGORIAS_POR_PAGAR = ("Proveedor", "Nomina", "Servicios", "Arriendo", "Impuestos", "Otro")

# Un pedido cuenta como venta real del cliente: ni anulada, ni saldo de apertura.
_VENTAS_REALES = "v.estado_venta <> 'Anulada'"


def _raise_validation(exc: ValueError) -> None:
    raise SalesValidationError(str(exc)) from exc


def _dias_desde(valor) -> int | None:
    """Dias transcurridos desde un datetime/date de la BD, o None."""
    if not valor:
        return None
    referencia = valor.date() if isinstance(valor, datetime) else valor
    return max(0, (date.today() - referencia).days)


# ══════════════════════════════════════════════════════════════
# CLIENTES MAYORISTAS (B2B)
#
# El precio mayorista es un valor fijo por producto (productos.precio_mayorista)
# que se cobra en Venta Mayorista. Las listas con descuento porcentual
# (listas_precios) quedaron sin uso: la tabla se conserva por historial.
# ══════════════════════════════════════════════════════════════

_DEUDA_CLIENTE = """
  COALESCE((
    SELECT SUM(GREATEST(
      v.total_final - COALESCE((
        SELECT SUM(ab.monto_abonado) FROM abonos_fiados ab WHERE ab.id_venta = v.id_venta
      ), 0), 0))
    FROM ventas v
    WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
      AND v.estado_venta = 'Fiada/Pendiente'
  ), 0)
"""


def get_clientes_b2b(id_tienda: int) -> list[dict]:
    """Tarjetas del modulo B2B: solo los campos que pinta la vista."""
    id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT c.id_cliente, c.nombre, c.telefono, c.nit,
                   {_DEUDA_CLIENTE} AS deuda,
                   (SELECT COUNT(*) FROM ventas v
                     WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
                       AND {_VENTAS_REALES}) AS pedidos,
                   (SELECT COALESCE(SUM(v.total_final), 0) FROM ventas v
                     WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
                       AND {_VENTAS_REALES}) AS comprado,
                   (SELECT MAX(v.fecha_creacion) FROM ventas v
                     WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
                       AND {_VENTAS_REALES}) AS ultima_compra,
                   (SELECT MIN(v.fecha_creacion) FROM ventas v
                     WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
                       AND {_VENTAS_REALES}) AS primera_compra
            FROM clientes c
            WHERE c.id_tienda = %s AND c.estado_activo = 1 AND c.tipo = 'B2B'
            ORDER BY comprado DESC, c.nombre
            """,
            (id_tienda,),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    return [_fila_cliente_b2b(f) for f in filas]


def _fila_cliente_b2b(f: dict) -> dict:
    pedidos = int(f["pedidos"] or 0)
    comprado = float(f["comprado"] or 0)
    return {
        "id": f["id_cliente"],
        "name": f["nombre"],
        "phone": f.get("telefono") or "-",
        "nit": f.get("nit") or "",
        "debt": max(0.0, float(f["deuda"] or 0)),
        "pedidos": pedidos,
        "comprado": comprado,
        "ticket_promedio": (comprado / pedidos) if pedidos else 0.0,
        "frecuencia_dias": _frecuencia_dias(f.get("primera_compra"), f.get("ultima_compra"), pedidos),
        "dias_sin_comprar": _dias_desde(f.get("ultima_compra")),
    }


def _frecuencia_dias(primera, ultima, pedidos: int) -> float | None:
    """Dias promedio entre pedidos. None con menos de 2 pedidos (no hay intervalo)."""
    if pedidos < 2 or not primera or not ultima:
        return None
    inicio = primera.date() if isinstance(primera, datetime) else primera
    fin = ultima.date() if isinstance(ultima, datetime) else ultima
    span = (fin - inicio).days
    if span <= 0:
        return 0.0
    return round(span / (pedidos - 1), 1)


def get_cliente_b2b_dashboard(id_tienda: int, id_cliente: int) -> dict:
    """Detalle de un cliente comercial: KPIs + top productos comprados."""
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_cliente = parse_int(id_cliente, "Cliente", min_value=1)
    except ValueError as exc:
        _raise_validation(exc)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT c.id_cliente, c.nombre, c.telefono, c.nit,
                   {_DEUDA_CLIENTE} AS deuda,
                   (SELECT COUNT(*) FROM ventas v
                     WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
                       AND {_VENTAS_REALES}) AS pedidos,
                   (SELECT COALESCE(SUM(v.total_final), 0) FROM ventas v
                     WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
                       AND {_VENTAS_REALES}) AS comprado,
                   (SELECT MAX(v.fecha_creacion) FROM ventas v
                     WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
                       AND {_VENTAS_REALES}) AS ultima_compra,
                   (SELECT MIN(v.fecha_creacion) FROM ventas v
                     WHERE v.id_cliente = c.id_cliente AND v.id_tienda = c.id_tienda
                       AND {_VENTAS_REALES}) AS primera_compra
            FROM clientes c
            WHERE c.id_cliente = %s AND c.id_tienda = %s AND c.estado_activo = 1
            LIMIT 1
            """,
            (id_cliente, id_tienda),
        )
        fila = cur.fetchone()
        if not fila:
            raise SalesNotFoundError("Cliente no encontrado.")

        cur.execute(
            f"""
            SELECT p.nombre,
                   SUM(dv.cantidad) AS unidades,
                   SUM(dv.subtotal_linea) AS importe
            FROM detalle_ventas dv
            INNER JOIN ventas v ON v.id_venta = dv.id_venta
            INNER JOIN productos p
              ON p.id_producto = dv.id_producto AND p.id_tienda = v.id_tienda
            WHERE v.id_cliente = %s AND v.id_tienda = %s AND {_VENTAS_REALES}
            GROUP BY dv.id_producto, p.nombre
            ORDER BY importe DESC
            LIMIT 5
            """,
            (id_cliente, id_tienda),
        )
        top = [
            {
                "nombre": r["nombre"] or "Producto",
                "unidades": float(r["unidades"] or 0),
                "importe": float(r["importe"] or 0),
            }
            for r in (cur.fetchall() or [])
        ]
    finally:
        conn.close()

    cliente = _fila_cliente_b2b(fila)
    cliente["top_productos"] = top
    return cliente


def upsert_cliente_b2b(
    id_tienda: int,
    id_usuario: int,
    nombre: str,
    telefono: str,
    nit: str | None,
    id_cliente: int | None = None,
) -> int:
    """Crea un cliente comercial o convierte uno existente a B2B."""
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        nombre = sanitize_text(nombre, "El nombre del cliente", max_len=150)
        nit_limpio = sanitize_optional_text(nit, "El NIT", max_len=30)
        if id_cliente is not None:
            id_cliente = parse_int(id_cliente, "Cliente", min_value=1)
    except ValueError as exc:
        _raise_validation(exc)

    telefono_digits = only_digits(telefono)
    if not 7 <= len(telefono_digits) <= 25:
        raise SalesValidationError("El telefono debe tener entre 7 y 25 digitos.")

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            if id_cliente is None:
                cur.execute(
                    "INSERT INTO clientes (id_tienda, nombre, telefono, tipo, nit) "
                    "VALUES (%s, %s, %s, 'B2B', %s)",
                    (id_tienda, nombre, telefono_digits, nit_limpio),
                )
                id_cliente = cur.lastrowid
                accion = "crear_cliente_b2b"
            else:
                cur.execute(
                    "UPDATE clientes "
                    "SET nombre = %s, telefono = %s, tipo = 'B2B', nit = %s "
                    "WHERE id_cliente = %s AND id_tienda = %s AND estado_activo = 1",
                    (nombre, telefono_digits, nit_limpio, id_cliente, id_tienda),
                )
                if cur.rowcount == 0:
                    cur.execute(
                        "SELECT id_cliente FROM clientes "
                        "WHERE id_cliente = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
                        (id_cliente, id_tienda),
                    )
                    if not cur.fetchone():
                        raise SalesNotFoundError("Cliente no encontrado.")
                accion = "editar_cliente_b2b"
        except IntegrityError as exc:
            raise SalesConflictError("Ese telefono ya pertenece a otro cliente.") from exc

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    registrar_auditoria(
        id_tienda, id_usuario, accion, f"Cliente B2B id={id_cliente}"
    )
    return id_cliente


def get_clientes_mayoristas_min(id_tienda: int) -> list[dict]:
    """id + nombre + NIT de los clientes B2B: el selector de Venta Mayorista.

    Aparte de get_clientes_b2b porque ese trae compras y deuda (dashboard de
    admin) y Venta Mayorista la usa tambien el Cajero.
    """
    id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_cliente, nombre, nit FROM clientes "
            "WHERE id_tienda = %s AND estado_activo = 1 AND tipo = 'B2B' "
            "ORDER BY nombre LIMIT 500",
            (id_tienda,),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    return [{"id": f["id_cliente"], "name": f["nombre"], "nit": f.get("nit") or ""} for f in filas]


# ══════════════════════════════════════════════════════════════
# CUENTAS POR PAGAR
# ══════════════════════════════════════════════════════════════

def get_cuentas_por_pagar(id_tienda: int) -> list[dict]:
    """Obligaciones vigentes (Pendiente) + las pagadas recientes."""
    id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT cp.id_cuenta, cp.categoria, cp.concepto, cp.descripcion,
                   cp.monto_total, cp.monto_pagado, cp.fecha_vencimiento, cp.estado,
                   pr.nombre_empresa AS proveedor
            FROM cuentas_por_pagar cp
            LEFT JOIN proveedores pr
              ON pr.id_proveedor = cp.id_proveedor AND pr.id_tienda = cp.id_tienda
            WHERE cp.id_tienda = %s AND cp.estado <> 'Anulada'
            ORDER BY FIELD(cp.estado, 'Pendiente', 'Pagada'),
                     cp.fecha_vencimiento IS NULL, cp.fecha_vencimiento ASC,
                     cp.id_cuenta DESC
            LIMIT 200
            """,
            (id_tienda,),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    hoy = date.today()
    cuentas = []
    for f in filas:
        total = float(f["monto_total"] or 0)
        pagado = float(f["monto_pagado"] or 0)
        vence = f.get("fecha_vencimiento")
        pendiente = f["estado"] == "Pendiente"
        cuentas.append(
            {
                "id": f["id_cuenta"],
                "categoria": f["categoria"],
                "concepto": f["concepto"],
                "descripcion": f.get("descripcion") or "",
                "proveedor": f.get("proveedor") or "",
                "total": total,
                "pagado": pagado,
                "saldo": max(0.0, total - pagado),
                "estado": f["estado"],
                "vence": vence.isoformat() if vence else "",
                # Positivo = dias vencidos; negativo = dias que faltan.
                "dias_mora": (hoy - vence).days if (vence and pendiente) else 0,
            }
        )
    return cuentas


def get_proveedores_min(id_tienda: int) -> list[dict]:
    """id + nombre de proveedores activos: lo unico que necesita el <select>.

    No se reutiliza /api/proveedores porque esa respuesta trae correo,
    telefonos y detalles que esta vista no pinta.
    """
    id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor, nombre_empresa FROM proveedores "
            "WHERE id_tienda = %s AND estado_activo = 1 "
            "ORDER BY nombre_empresa LIMIT 200",
            (id_tienda,),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    return [{"id": f["id_proveedor"], "nombre": f["nombre_empresa"]} for f in filas]


def crear_cuenta_por_pagar(
    id_tienda: int,
    id_usuario: int,
    categoria: str,
    concepto: str,
    descripcion: str | None,
    monto_total: float,
    fecha_vencimiento: str | None,
    id_proveedor: int | None,
) -> int:
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        concepto = sanitize_text(concepto, "El concepto", max_len=150)
        descripcion_limpia = sanitize_optional_text(descripcion, "La descripcion", max_len=255)
        monto_total = parse_float(monto_total, "El monto", min_value=0, allow_zero=False)
        if id_proveedor is not None:
            id_proveedor = parse_int(id_proveedor, "Proveedor", min_value=1)
    except ValueError as exc:
        _raise_validation(exc)

    categoria = str(categoria or "").strip()
    if categoria not in CATEGORIAS_POR_PAGAR:
        raise SalesValidationError("Categoria invalida.")
    if monto_total > 999_999_999:
        raise SalesValidationError("El monto supera el maximo permitido.")

    vence = _parse_fecha_opcional(fecha_vencimiento)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if id_proveedor is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores "
                "WHERE id_proveedor = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
                (id_proveedor, id_tienda),
            )
            if not cur.fetchone():
                raise SalesNotFoundError("Proveedor no encontrado.")

        cur.execute(
            "INSERT INTO cuentas_por_pagar "
            "(id_tienda, id_proveedor, categoria, concepto, descripcion, monto_total, "
            " fecha_vencimiento, id_usuario_creador) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                id_tienda, id_proveedor, categoria, concepto, descripcion_limpia,
                monto_total, vence, id_usuario,
            ),
        )
        nuevo_id = cur.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    registrar_auditoria(
        id_tienda, id_usuario, "crear_cuenta_por_pagar",
        f"{categoria}: {concepto} por {monto_total} (id={nuevo_id})",
    )
    return nuevo_id


def _parse_fecha_opcional(valor: str | None) -> date | None:
    texto = str(valor or "").strip()
    if not texto:
        return None
    if len(texto) > 10:
        raise SalesValidationError("Fecha de vencimiento invalida.")
    try:
        return date.fromisoformat(texto)
    except ValueError as exc:
        raise SalesValidationError("Fecha de vencimiento invalida.") from exc


# Origen del dinero con que se paga una obligacion. La clave es lo unico que
# acepta la API; el valor dice como se registra el gasto que se genera solo.
#   etiqueta       -> texto que va en el concepto del gasto
#   fuente_dinero  -> enum de gastos_caja.fuente_dinero
#   metodo_pago    -> decide si descuenta de la caja del turno
ORIGENES_PAGO = {
    "transferencia": {"etiqueta": "Transferencia", "fuente_dinero": "Bancos", "metodo_pago": "Bancos"},
    "caja menor": {"etiqueta": "Caja Menor", "fuente_dinero": "Caja Menor", "metodo_pago": "Efectivo"},
    "caja fuerte": {"etiqueta": "Caja Fuerte", "fuente_dinero": "Caja Fuerte", "metodo_pago": "Efectivo"},
}


def _resolver_origen(origen) -> dict:
    """Valida el origen contra la lista estricta. Nada del DOM se acepta tal cual."""
    clave = str(origen or "").strip().lower()
    if clave not in ORIGENES_PAGO:
        raise SalesValidationError(
            "Origen de fondos invalido. Usa Transferencia, Caja Menor o Caja Fuerte."
        )
    return ORIGENES_PAGO[clave]


CATEGORIA_GASTO_CXP = "Cuentas por pagar"


def _descripcion_gasto_cxp(id_cuenta: int, cuenta: dict, proveedor: str, origen: str) -> str:
    partes = [
        f"Abono cuenta por pagar #{id_cuenta} ({cuenta['categoria']})",
        f"Origen: {origen}",
        f"Pagado a: {proveedor or cuenta['concepto']}",
    ]
    if proveedor:
        partes.append(f"Concepto: {cuenta['concepto']}")
    return " - ".join(partes)[:255]


def pagar_cuenta_por_pagar(
    id_tienda: int, id_usuario: int, id_cuenta: int, monto: float, origen: str
) -> dict:
    """Aprueba un pago (total o parcial) y registra su gasto, todo atomico.

    Una sola transaccion cubre el descuento de la deuda y el INSERT en
    gastos_caja: si el gasto falla (por ejemplo, Caja Menor sin turno abierto),
    el pago se revierte y la deuda queda intacta.

    El saldo se relee bajo FOR UPDATE: dos aprobaciones simultaneas no pueden
    pagar mas que el monto de la obligacion.
    """
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        id_cuenta = parse_int(id_cuenta, "Cuenta", min_value=1)
        monto = parse_float(monto, "El monto", min_value=0, allow_zero=False)
    except ValueError as exc:
        _raise_validation(exc)

    config_origen = _resolver_origen(origen)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT concepto, categoria, id_proveedor, monto_total, monto_pagado, estado "
            "FROM cuentas_por_pagar "
            "WHERE id_cuenta = %s AND id_tienda = %s LIMIT 1 FOR UPDATE",
            (id_cuenta, id_tienda),
        )
        cuenta = cur.fetchone()
        if not cuenta:
            raise SalesNotFoundError("Cuenta por pagar no encontrada.")
        if cuenta["estado"] != "Pendiente":
            raise SalesConflictError("Esta obligacion ya no esta pendiente.")

        total = float(cuenta["monto_total"] or 0)
        pagado = float(cuenta["monto_pagado"] or 0)
        saldo = max(0.0, total - pagado)
        if monto > saldo + 0.01:
            raise SalesValidationError("El pago no puede superar el saldo pendiente.")

        nuevo_pagado = min(total, pagado + monto)
        queda_pagada = nuevo_pagado >= total - 0.01

        cur.execute(
            "UPDATE cuentas_por_pagar "
            "SET monto_pagado = %s, estado = %s, id_usuario_aprobador = %s, "
            "    fecha_ultimo_pago = CURRENT_TIMESTAMP "
            "WHERE id_cuenta = %s AND id_tienda = %s",
            (
                nuevo_pagado,
                "Pagada" if queda_pagada else "Pendiente",
                id_usuario,
                id_cuenta,
                id_tienda,
            ),
        )

        proveedor = ""
        if cuenta["id_proveedor"]:
            cur.execute(
                "SELECT nombre_empresa FROM proveedores WHERE id_proveedor = %s AND id_tienda = %s LIMIT 1",
                (cuenta["id_proveedor"], id_tienda),
            )
            fila_prov = cur.fetchone()
            proveedor = (fila_prov or {}).get("nombre_empresa") or ""

        # Gasto automatico, mismo cursor y misma transaccion que el UPDATE.
        # Categoria fija: asi el reporte de gastos agrupa todos los abonos a
        # deudas. A quien se pago y de que cuenta va en la descripcion, con
        # cuenta y origen primero para que el recorte a 255 nunca los pierda.
        id_gasto = insertar_gasto(
            cur,
            id_tienda,
            id_usuario,
            CATEGORIA_GASTO_CXP,
            _descripcion_gasto_cxp(id_cuenta, cuenta, proveedor, config_origen["etiqueta"]),
            config_origen["metodo_pago"],
            config_origen["fuente_dinero"],
            monto,
        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    registrar_auditoria(
        id_tienda, id_usuario, "aprobar_pago_cuenta",
        f"Cuenta id={id_cuenta}: pago de {monto} desde {config_origen['etiqueta']}, "
        f"acumulado {nuevo_pagado}/{total}, gasto id={id_gasto}",
    )
    return {
        "saldo": max(0.0, total - nuevo_pagado),
        "estado": "Pagada" if queda_pagada else "Pendiente",
        "id_gasto": id_gasto,
        "origen": config_origen["etiqueta"],
    }


def anular_cuenta_por_pagar(id_tienda: int, id_usuario: int, id_cuenta: int) -> None:
    """Anula una obligacion sin borrar la fila (traza contable intacta)."""
    try:
        id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
        id_usuario = parse_int(id_usuario, "Usuario", min_value=1)
        id_cuenta = parse_int(id_cuenta, "Cuenta", min_value=1)
    except ValueError as exc:
        _raise_validation(exc)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cuentas_por_pagar SET estado = 'Anulada' "
            "WHERE id_cuenta = %s AND id_tienda = %s AND estado = 'Pendiente'",
            (id_cuenta, id_tienda),
        )
        if cur.rowcount == 0:
            raise SalesNotFoundError("Cuenta por pagar no encontrada o ya procesada.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    registrar_auditoria(id_tienda, id_usuario, "anular_cuenta_por_pagar", f"Cuenta id={id_cuenta}")


def get_resumen_cartera(id_tienda: int) -> dict:
    """Totales de las dos pestanas, en una sola consulta por lado."""
    id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        # INNER JOIN a clientes activos: un cliente dado de baja sale del listado
        # y tambien del total, para que el encabezado cuadre con las filas.
        cur.execute(
            """
            SELECT
              COALESCE(SUM(GREATEST(v.total_final - COALESCE((
                SELECT SUM(ab.monto_abonado) FROM abonos_fiados ab WHERE ab.id_venta = v.id_venta
              ), 0), 0)), 0) AS por_cobrar,
              COUNT(DISTINCT v.id_cliente) AS deudores
            FROM ventas v
            INNER JOIN clientes c
              ON c.id_cliente = v.id_cliente AND c.id_tienda = v.id_tienda
             AND c.estado_activo = 1
            WHERE v.id_tienda = %s AND v.estado_venta = 'Fiada/Pendiente'
            """,
            (id_tienda,),
        )
        cobrar = cur.fetchone() or {}

        cur.execute(
            """
            SELECT COALESCE(SUM(monto_total - monto_pagado), 0) AS por_pagar,
                   COUNT(*) AS obligaciones,
                   COALESCE(SUM(CASE WHEN fecha_vencimiento IS NOT NULL
                                      AND fecha_vencimiento < CURDATE()
                                     THEN monto_total - monto_pagado ELSE 0 END), 0) AS vencido
            FROM cuentas_por_pagar
            WHERE id_tienda = %s AND estado = 'Pendiente'
            """,
            (id_tienda,),
        )
        pagar = cur.fetchone() or {}
    finally:
        conn.close()

    return {
        "por_cobrar": float(cobrar.get("por_cobrar") or 0),
        "deudores": int(cobrar.get("deudores") or 0),
        "por_pagar": float(pagar.get("por_pagar") or 0),
        "obligaciones": int(pagar.get("obligaciones") or 0),
        "vencido": float(pagar.get("vencido") or 0),
    }


# ORDER BY no admite parametros: la columna sale de esta lista blanca, nunca
# del cliente. El desempate por id deja el top estable entre refrescos.
_ORDEN_DEUDORES = {
    "antiguas": "deuda_desde ASC, c.id_cliente",
    "monto": "saldo DESC, c.id_cliente",
}


def get_top_deudores(id_tienda: int, orden: str, limit: int = 5) -> list[dict]:
    """Top de clientes con deuda pendiente, por antiguedad o por monto.

    Misma deuda que get_resumen_cartera (fiados pendientes menos sus abonos,
    solo clientes activos) y misma mora que get_fiados_clientes: dias desde
    la venta pendiente mas antigua.
    """
    id_tienda = parse_int(id_tienda, "Tienda", min_value=1)
    limit = parse_int(limit, "Limite", min_value=1, max_value=50)
    orden_sql = _ORDEN_DEUDORES[orden]
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT c.id_cliente, c.nombre,
              SUM(GREATEST(v.total_final - COALESCE((
                SELECT SUM(ab.monto_abonado) FROM abonos_fiados ab WHERE ab.id_venta = v.id_venta
              ), 0), 0)) AS saldo,
              MIN(v.fecha_creacion) AS deuda_desde
            FROM ventas v
            INNER JOIN clientes c
              ON c.id_cliente = v.id_cliente AND c.id_tienda = v.id_tienda
             AND c.estado_activo = 1
            WHERE v.id_tienda = %s AND v.estado_venta = 'Fiada/Pendiente'
            GROUP BY c.id_cliente, c.nombre
            HAVING saldo > 0
            ORDER BY {orden_sql}
            LIMIT %s
            """,
            (id_tienda, limit),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    return [
        {
            "id": f["id_cliente"],
            "nombre": f["nombre"],
            "saldo": round(float(f["saldo"] or 0), 2),
            "dias": _dias_desde(f["deuda_desde"]) or 0,
        }
        for f in filas
    ]
