from __future__ import annotations

from datetime import date

from app.utils.helpers import normalize_payment_method
from database import get_db


class SalesServiceError(ValueError):
    pass


class SalesValidationError(SalesServiceError):
    pass


class SalesNotFoundError(SalesServiceError):
    pass


class SalesConflictError(SalesServiceError):
    pass


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
        return [r[0] for r in cur.fetchall() if r and r[0]]
    finally:
        conn.close()


def get_fiados_clientes(id_tienda: int) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT c.id_cliente, c.nombre, c.telefono,
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
              ), 0) AS deuda_total
            FROM clientes c
            WHERE c.id_tienda = %s AND c.estado_activo = 1
            ORDER BY c.nombre
            """,
            (id_tienda,),
        )
        filas = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": f["id_cliente"],
            "name": f["nombre"],
            "phone": f["telefono"] or "-",
            "debt": max(0.0, float(f["deuda_total"] or 0)),
        }
        for f in filas
    ]


def get_ventas(id_tienda: int, rol: str, id_usuario: int | None, filtro: str | None) -> tuple[list[dict], str]:
    filtro_final = "24h" if rol == "Cajero" else (filtro or "mes")

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        consulta = (
            "SELECT v.id_venta, v.total_final, v.estado_venta, v.fecha_creacion, "
            "COALESCE(c.nombre, 'Mostrador') AS nombre_cliente, "
            "u.nombre_completo AS nombre_cajero "
            "FROM ventas v "
            "LEFT JOIN clientes c ON v.id_cliente = c.id_cliente "
            "LEFT JOIN usuarios u ON v.id_cajero = u.id_usuario "
            "WHERE v.id_tienda = %s "
        )
        parametros = [id_tienda]

        if rol == "Cajero":
            filtro_final = "24h"
            consulta += "AND v.id_cajero = %s "
            parametros.append(id_usuario)
            consulta += "AND v.fecha_creacion >= (NOW() - INTERVAL 1 DAY) "
        elif rol in {"Admin", "Master"}:
            if filtro_final not in {"hoy", "semana", "mes", "todas"}:
                filtro_final = "mes"
            if filtro_final == "hoy":
                consulta += "AND DATE(v.fecha_creacion) = CURDATE() "
            elif filtro_final == "semana":
                consulta += "AND v.fecha_creacion >= (NOW() - INTERVAL 7 DAY) "
            elif filtro_final == "mes":
                consulta += "AND YEAR(v.fecha_creacion) = YEAR(CURDATE()) AND MONTH(v.fecha_creacion) = MONTH(CURDATE()) "
        else:
            return [], "mes"

        consulta += "ORDER BY v.id_venta DESC"
        cur.execute(consulta, tuple(parametros))
        filas = cur.fetchall() or []
    finally:
        conn.close()

    lista = []
    for fila in filas:
        lista.append(
            {
                "id_venta": fila.get("id_venta"),
                "total_final": float(fila.get("total_final") or 0),
                "estado_venta": (fila.get("estado_venta") or "Pagada").strip() or "Pagada",
                "fecha_creacion": fila.get("fecha_creacion"),
                "nombre_cliente": fila.get("nombre_cliente") or "Mostrador",
                "nombre_cajero": fila.get("nombre_cajero") or "Sin cajero",
            }
        )
    return lista, filtro_final


def get_turno_estado(id_tienda: int) -> dict | None:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno, fecha_apertura, monto_inicial "
            "FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
            "ORDER BY fecha_apertura DESC LIMIT 1",
            (id_tienda,),
        )
        turno = cur.fetchone()
    finally:
        conn.close()

    if not turno:
        return None
    return {
        "id_turno": turno["id_turno"],
        "hora_apertura": turno["fecha_apertura"].strftime("%I:%M %p"),
        "monto_inicial": float(turno["monto_inicial"]),
    }


def abrir_turno(id_tienda: int, id_usuario: int, monto_inicial: float) -> int:
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


def cerrar_turno(id_tienda: int, id_usuario: int, monto_final: float) -> None:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
            "ORDER BY fecha_apertura DESC LIMIT 1",
            (id_tienda,),
        )
        turno = cur.fetchone()
        if not turno:
            raise SalesNotFoundError("No hay turno abierto.")

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


def get_caja_productos(id_tienda: int, q: str) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if q:
            cur.execute(
                "SELECT id_producto, nombre, precio_venta, stock_actual "
                "FROM productos "
                "WHERE id_tienda = %s AND estado_activo = 1 "
                "AND (nombre LIKE %s OR codigo_barras = %s) "
                "ORDER BY nombre LIMIT 20",
                (id_tienda, f"%{q}%", q),
            )
        else:
            cur.execute(
                "SELECT id_producto, nombre, precio_venta, stock_actual "
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
) -> dict:
    metodo_pago_db = normalize_payment_method(metodo_pago_ui)
    if not metodo_pago_db:
        raise SalesValidationError("Metodo de pago invalido.")

    conn = get_db()
    alertas_stock: list[str] = []
    claves_alerta: set[int] = set()

    try:
        cur = conn.cursor(dictionary=True)
        id_turno = _obtener_turno_abierto(id_tienda, cur)
        if not id_turno:
            raise SalesConflictError("Abre un turno antes de registrar ventas.")

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
                        "SELECT id_insumo, cantidad_necesaria "
                        "FROM recetas_productos WHERE id_producto = %s",
                        (id_producto,),
                    )
                except Exception:
                    cur.execute(
                        "SELECT id_insumo, cantidad_requerida AS cantidad_necesaria "
                        "FROM recetas_productos WHERE id_producto = %s",
                        (id_producto,),
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

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
            (id_tienda,),
        )
        consecutivo = cur.fetchone()["cnt"]
        numero_venta = f"V{id_tienda:04d}-{consecutivo + 1:06d}"

        cur.execute(
            "INSERT INTO ventas "
            "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
            " subtotal, total_final, metodo_pago, estado_venta) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Pagada')",
            (
                id_tienda,
                id_turno,
                id_usuario,
                id_cliente,
                numero_venta,
                subtotal,
                monto_total,
                metodo_pago_db,
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

        if metodo_pago_db == "Efectivo":
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
        "stock_alerts": alertas_stock,
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
            "INNER JOIN productos p ON p.id_producto = dv.id_producto "
            "INNER JOIN ventas v ON v.id_venta = dv.id_venta "
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
            (id_tienda, nombre, telefono or None),
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


def sumar_fiado(id_tienda: int, id_usuario: int, id_cliente: int, monto: float, concepto: str) -> None:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_cliente FROM clientes WHERE id_cliente = %s AND id_tienda = %s LIMIT 1",
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
    metodo = normalize_payment_method(metodo_ui)
    if not metodo:
        raise SalesValidationError("Metodo invalido.")

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_cliente FROM clientes WHERE id_cliente = %s AND id_tienda = %s LIMIT 1",
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

        cur.execute(
            "INSERT INTO abonos_fiados "
            "(id_tienda, id_venta, id_usuario, monto_abonado, metodo_pago) "
            "VALUES (%s,%s,%s,%s,%s)",
            (id_tienda, venta["id_venta"], id_usuario, monto, metodo),
        )

        if metodo == "Efectivo":
            id_turno = _obtener_turno_abierto(id_tienda, cur)
            if not id_turno:
                raise SalesConflictError("No hay turno abierto para registrar abonos en efectivo.")
            cur.execute(
                "UPDATE turnos_caja "
                "SET monto_final_esperado = COALESCE(monto_final_esperado, monto_inicial, 0) + %s "
                "WHERE id_turno = %s",
                (monto, id_turno),
            )

        if float(venta["abonado"]) + monto >= float(venta["total_final"]):
            cur.execute(
                "UPDATE ventas SET estado_venta = 'Pagada' WHERE id_venta = %s",
                (venta["id_venta"],),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_gastos(id_tienda: int, id_usuario: int) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT gc.id_gasto, gc.concepto, gc.descripcion, gc.monto, gc.fuente_dinero, "
            "UNIX_TIMESTAMP(gc.fecha_creacion) * 1000 AS ts "
            "FROM gastos_caja gc "
            "WHERE gc.id_tienda = %s AND gc.id_usuario = %s "
            "ORDER BY gc.id_gasto DESC LIMIT 100",
            (id_tienda, id_usuario),
        )
        filas = cur.fetchall() or []
    finally:
        conn.close()

    return [
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


def crear_gasto(
    id_tienda: int,
    id_usuario: int,
    concepto: str,
    descripcion: str,
    metodo_pago: str,
    fuente_dinero: str,
    monto: float,
) -> int:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        id_turno = _obtener_turno_abierto(id_tienda, cur)

        if metodo_pago == "Efectivo" and fuente_dinero == "Caja Menor" and not id_turno:
            raise SalesConflictError("No hay turno activo para cargar gastos de Caja Menor.")

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
        cur.execute("SELECT LAST_INSERT_ID() AS nuevo_id")
        fila_nuevo_id = cur.fetchone() or {}
        nuevo_id = int(fila_nuevo_id.get("nuevo_id") or 0)

        if metodo_pago == "Efectivo" and fuente_dinero == "Caja Menor":
            cur.execute(
                "UPDATE turnos_caja "
                "SET monto_final_esperado = COALESCE(monto_final_esperado, monto_inicial, 0) - %s "
                "WHERE id_turno = %s AND id_tienda = %s",
                (monto, id_turno, id_tienda),
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
