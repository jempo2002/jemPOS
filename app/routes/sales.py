from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, jsonify, render_template, request, session

from app.utils.decorators import login_required, roles_required
from app.utils.helpers import (
    avatar_iniciales,
    normalize_payment_method as normalizar_metodo_pago,
    only_digits as solo_digitos,
)
from database import get_db

sales_bp = Blueprint("sales_bp", __name__, url_prefix="/pos")
sales_api_bp = Blueprint("sales_api_bp", __name__, url_prefix="/pos")


def _get_dias_restantes(id_tienda: int) -> int:
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


def _base_context() -> dict:
    nombre = session.get("nombre_completo", "")
    dias = 0
    mostrar_alerta = False
    if session.get("id_tienda"):
        dias = _get_dias_restantes(session["id_tienda"])
        mostrar_alerta = 0 < dias <= 5

    return {
        "rol": session.get("rol", ""),
        "nombre_completo": nombre,
        "foto_perfil": session.get("foto_perfil"),
        "avatar_iniciales": avatar_iniciales(nombre),
        "mostrar_alerta_suscripcion": mostrar_alerta,
        "dias_restantes": dias,
    }


def _render_sales(template: str, **kwargs):
    ctx = _base_context()
    ctx.update(kwargs)
    return render_template(template, **ctx)


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


def _obtener_categorias_gastos(id_tienda: int) -> list:
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


def _obtener_fiados_clientes(id_tienda: int) -> list:
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
            "phone": f["telefono"] or "—",
            "debt": max(0.0, float(f["deuda_total"] or 0)),
        }
        for f in filas
    ]


@sales_bp.get("/turno")
@login_required
def turno():
    return _render_sales("pos/turno.html")


@sales_bp.get("/caja")
@login_required
def caja():
    return _render_sales("pos/caja.html")


@sales_bp.get("/ventas")
@login_required
def ventas():
    id_tienda = session.get("id_tienda")
    rol = (session.get("rol") or "").strip()
    filtro_url = request.args.get("filtro")
    filtro = "24h" if rol == "Cajero" else (filtro_url or "mes")
    lista_ventas = []

    if not id_tienda:
        flash("No se encontro la tienda activa en la sesion.", "error")
        return _render_sales("pos/ventas.html", ventas=[], filtro_activo="mes")

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
            filtro = "24h"
            consulta += "AND v.id_cajero = %s "
            parametros.append(session.get("id_usuario"))
            consulta += "AND v.fecha_creacion >= (NOW() - INTERVAL 1 DAY) "
        elif rol in {"Admin", "Master"}:
            if filtro not in {"hoy", "semana", "mes", "todas"}:
                filtro = "mes"
            if filtro == "hoy":
                consulta += "AND DATE(v.fecha_creacion) = CURDATE() "
            elif filtro == "semana":
                consulta += "AND v.fecha_creacion >= (NOW() - INTERVAL 7 DAY) "
            elif filtro == "mes":
                consulta += "AND YEAR(v.fecha_creacion) = YEAR(CURDATE()) AND MONTH(v.fecha_creacion) = MONTH(CURDATE()) "
        else:
            return _render_sales("pos/ventas.html", ventas=[], filtro_activo="mes")

        consulta += "ORDER BY v.id_venta DESC"
        cur.execute(consulta, tuple(parametros))
        filas = cur.fetchall() or []
    finally:
        conn.close()

    for fila in filas:
        lista_ventas.append({
            "id_venta": fila.get("id_venta"),
            "total_final": float(fila.get("total_final") or 0),
            "estado_venta": (fila.get("estado_venta") or "Pagada").strip() or "Pagada",
            "fecha_creacion": fila.get("fecha_creacion"),
            "nombre_cliente": fila.get("nombre_cliente") or "Mostrador",
            "nombre_cajero": fila.get("nombre_cajero") or "Sin cajero",
        })

    return _render_sales("pos/ventas.html", ventas=lista_ventas, filtro_activo=filtro)


@sales_bp.get("/fiados")
@login_required
def fiados():
    return _render_sales(
        "pos/fiados.html",
        fiados_clientes=_obtener_fiados_clientes(session["id_tienda"]),
    )


@sales_bp.get("/gastos")
@login_required
@roles_required("Admin", "Master", "Cajero")
def gastos():
    return _render_sales(
        "pos/gastos.html",
        categorias_gastos=_obtener_categorias_gastos(session["id_tienda"]),
    )


# ─────────────────────────────────────────────────────────────
# API — Turno de Caja
# ─────────────────────────────────────────────────────────────
@sales_api_bp.get("/api/turno/estado")
@login_required
def api_turno_estado():
    """Devuelve el turno abierto de la tienda, o null si no hay ninguno."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno, fecha_apertura, monto_inicial "
            "FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
            "ORDER BY fecha_apertura DESC LIMIT 1",
            (session["id_tienda"],),
        )
        turno = cur.fetchone()
    finally:
        conn.close()

    if turno:
        return jsonify({
            "ok": True,
            "turno": {
                "id_turno": turno["id_turno"],
                "hora_apertura": turno["fecha_apertura"].strftime("%I:%M %p"),
                "monto_inicial": float(turno["monto_inicial"]),
            },
        })
    return jsonify({"ok": True, "turno": None})


@sales_api_bp.post("/api/turno/abrir")
@login_required
def api_turno_abrir():
    """Abre un nuevo turno. Rechaza si ya hay uno abierto."""
    data = request.get_json(silent=True) or {}
    try:
        monto = float(data.get("monto_inicial", 0))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400

    if monto <= 0:
        return jsonify({"ok": False, "msg": "El monto debe ser mayor a cero."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' LIMIT 1",
            (session["id_tienda"],),
        )
        if cur.fetchone():
            return jsonify({"ok": False, "msg": "Ya hay un turno abierto para esta tienda."}), 409

        cur.execute(
            "INSERT INTO turnos_caja "
            "(id_tienda, id_usuario_apertura, monto_inicial, monto_final_esperado) "
            "VALUES (%s, %s, %s, %s)",
            (session["id_tienda"], session["id_usuario"], monto, monto),
        )
        conn.commit()
        turno_id = cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return jsonify({"ok": True, "id_turno": turno_id})


@sales_api_bp.post("/api/turno/cerrar")
@login_required
def api_turno_cerrar():
    """Cierra el turno abierto de la tienda."""
    data = request.get_json(silent=True) or {}
    try:
        monto_final = float(data.get("monto_final", -1))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400

    if monto_final < 0:
        return jsonify({"ok": False, "msg": "El monto no puede ser negativo."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_turno FROM turnos_caja "
            "WHERE id_tienda = %s AND estado_turno = 'Abierto' "
            "ORDER BY fecha_apertura DESC LIMIT 1",
            (session["id_tienda"],),
        )
        turno = cur.fetchone()
        if not turno:
            return jsonify({"ok": False, "msg": "No hay turno abierto."}), 404

        cur.execute(
            "UPDATE turnos_caja "
            "SET estado_turno = 'Cerrado', fecha_cierre = NOW(), "
            "    monto_final_real = %s, id_usuario_cierre = %s "
            "WHERE id_turno = %s",
            (monto_final, session["id_usuario"], turno["id_turno"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# API — Caja / Ventas
# ─────────────────────────────────────────────────────────────
@sales_api_bp.get("/api/caja/productos")
@login_required
def api_caja_productos():
    q = str(request.args.get("q", "")).strip()
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
                (session["id_tienda"], f"%{q}%", q),
            )
        else:
            cur.execute(
                "SELECT id_producto, nombre, precio_venta, stock_actual "
                "FROM productos "
                "WHERE id_tienda = %s AND estado_activo = 1 "
                "ORDER BY nombre LIMIT 50",
                (session["id_tienda"],),
            )
        rows = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"ok": True, "productos": [
        {"id": r["id_producto"], "name": r["nombre"],
         "price": float(r["precio_venta"]), "stock": r["stock_actual"]}
        for r in rows
    ]})


@sales_api_bp.post("/api/ventas")
@login_required
def api_ventas_crear():
    datos = request.get_json(silent=True) or {}
    items = datos.get("items", [])
    metodo_pago_ui = str(datos.get("method", "efectivo"))
    id_cliente = datos.get("id_cliente")

    try:
        subtotal = float(datos.get("subtotal", 0))
        monto_total = float(datos.get("total", 0))
        descuento = float(datos.get("discount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Totales invalidos."}), 400

    if not items:
        return jsonify({"ok": False, "msg": "No hay productos en la venta."}), 400

    metodo_pago_db = normalizar_metodo_pago(metodo_pago_ui)
    if not metodo_pago_db:
        return jsonify({"ok": False, "msg": "Metodo de pago invalido."}), 400

    conn = get_db()
    alertas_stock = []
    claves_alerta = set()

    try:
        cur = conn.cursor(dictionary=True)
        id_turno = _obtener_turno_abierto(session["id_tienda"], cur)
        if not id_turno:
            return jsonify({"ok": False, "msg": "Abre un turno antes de registrar ventas."}), 409

        lineas_validas = []

        for item in items:
            try:
                id_producto = int(item["id"])
                cantidad = float(item["qty"])
                precio = float(item["price"])
            except (KeyError, TypeError, ValueError):
                return jsonify({"ok": False, "msg": "Detalle de item invalido."}), 400

            if cantidad <= 0:
                return jsonify({"ok": False, "msg": "La cantidad debe ser mayor a cero."}), 400

            cur.execute(
                "SELECT id_producto, nombre, stock_actual, stock_minimo_alerta, COALESCE(es_preparado, 0) AS es_preparado "
                "FROM productos WHERE id_producto = %s AND id_tienda = %s LIMIT 1 FOR UPDATE",
                (id_producto, session["id_tienda"]),
            )
            producto = cur.fetchone()
            if not producto:
                raise ValueError("Producto no encontrado.")

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
                        (id_insumo, session["id_tienda"]),
                    )
                    insumo = cur.fetchone()
                    if not insumo:
                        raise ValueError("Insumo de receta no encontrado.")
                    if float(insumo.get("stock_actual") or 0) < consumo_total:
                        raise ValueError(
                            f"Stock insuficiente de insumo: {insumo.get('nombre') or 'Insumo'}"
                        )
            else:
                stock_actual = float(producto.get("stock_actual") or 0)
                if stock_actual < cantidad:
                    raise ValueError(
                        f"Stock insuficiente para {producto.get('nombre') or 'producto'}"
                    )

            lineas_validas.append({
                "id_producto": id_producto,
                "cantidad": cantidad,
                "precio": precio,
                "producto": producto,
                "recetas": recetas,
            })

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
            (session["id_tienda"],),
        )
        consecutivo = cur.fetchone()["cnt"]
        numero_venta = f"V{session['id_tienda']:04d}-{consecutivo + 1:06d}"

        cur.execute(
            "INSERT INTO ventas "
            "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
            " subtotal, total_final, metodo_pago, estado_venta) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Pagada')",
            (
                session["id_tienda"],
                id_turno,
                session["id_usuario"],
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
                        (consumo_total, id_insumo, session["id_tienda"]),
                    )
            else:
                cur.execute(
                    "UPDATE productos SET stock_actual = stock_actual - %s "
                    "WHERE id_producto = %s AND id_tienda = %s",
                    (cantidad, id_producto, session["id_tienda"]),
                )

                cur.execute(
                    "SELECT nombre, stock_actual, stock_minimo_alerta "
                    "FROM productos WHERE id_producto = %s AND id_tienda = %s LIMIT 1",
                    (id_producto, session["id_tienda"]),
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

        if descuento >= 20000:
            _registrar_auditoria(
                session.get("id_tienda"),
                session.get("id_usuario"),
                "descuento_manual_alto",
                f"Venta {numero_venta}: descuento manual de {descuento}",
            )
        for alerta in alertas_stock:
            flash(alerta, "alerta_stock")

    except ValueError as exc:
        conn.rollback()
        return jsonify({"ok": False, "msg": str(exc)}), 409
    except Exception as exc:
        conn.rollback()
        return jsonify({"ok": False, "msg": f"Error al registrar la venta: {exc}"}), 500
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "id_venta": id_venta,
        "numero_venta": numero_venta,
        "stock_alerts": alertas_stock,
    })


@sales_api_bp.get("/api/ventas/detalle/<int:id_venta>")
@login_required
def api_ventas_detalle(id_venta: int):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_venta, numero_venta, total_final "
            "FROM ventas "
            "WHERE id_venta = %s AND id_tienda = %s "
            "LIMIT 1",
            (id_venta, session["id_tienda"]),
        )
        venta = cur.fetchone()
        if not venta:
            return jsonify({"ok": False, "msg": "Venta no encontrada."}), 404

        cur.execute(
            "SELECT p.nombre AS producto, dv.cantidad, dv.subtotal_linea "
            "FROM detalle_ventas dv "
            "INNER JOIN productos p ON p.id_producto = dv.id_producto "
            "INNER JOIN ventas v ON v.id_venta = dv.id_venta "
            "WHERE dv.id_venta = %s AND v.id_tienda = %s "
            "ORDER BY dv.id_detalle_venta ASC",
            (id_venta, session["id_tienda"]),
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
    return jsonify({
        "ok": True,
        "id_venta": venta["id_venta"],
        "numero_venta": venta.get("numero_venta") or f"V-{venta['id_venta']}",
        "items": detalles,
        "total": float(venta.get("total_final") or 0),
    })


@sales_api_bp.get("/api/fiados")
@login_required
def api_fiados_listar():
    return jsonify({"ok": True, "clientes": _obtener_fiados_clientes(session["id_tienda"])})


@sales_api_bp.post("/api/fiados")
@login_required
def api_fiados_crear_cliente():
    datos = request.get_json(silent=True) or {}
    nombre = str(datos.get("nombre", "")).strip()
    telefono = solo_digitos(datos.get("telefono"))

    try:
        deuda_inicial = float(datos.get("deuda_inicial", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "La deuda inicial es invalida."}), 400

    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre es requerido."}), 400
    if not telefono:
        return jsonify({"ok": False, "msg": "El telefono es requerido."}), 400
    if len(telefono) > 10:
        return jsonify({"ok": False, "msg": "El telefono debe tener maximo 10 digitos."}), 400
    if len(telefono) < 10:
        return jsonify({"ok": False, "msg": "El telefono debe tener 10 digitos."}), 400
    if deuda_inicial < 0:
        return jsonify({"ok": False, "msg": "La deuda inicial no puede ser negativa."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        id_turno = None
        if deuda_inicial > 0:
            id_turno = _obtener_turno_abierto(session["id_tienda"], cur)
            if not id_turno:
                return jsonify({"ok": False, "msg": "Debes abrir un turno para registrar deuda inicial."}), 409

        cur.execute(
            "INSERT INTO clientes (id_tienda, nombre, telefono) VALUES (%s, %s, %s)",
            (session["id_tienda"], nombre, telefono or None),
        )
        nuevo_id = cur.lastrowid

        if deuda_inicial > 0:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
                (session["id_tienda"],),
            )
            cnt = cur.fetchone()["cnt"]
            numero_venta = f"F{session['id_tienda']:04d}-{cnt + 1:06d}"

            cur.execute(
                "INSERT INTO ventas "
                "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
                " subtotal, total_final, metodo_pago, estado_venta, observaciones) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'Efectivo','Fiada/Pendiente',%s)",
                (
                    session["id_tienda"],
                    id_turno,
                    session["id_usuario"],
                    nuevo_id,
                    numero_venta,
                    deuda_inicial,
                    deuda_inicial,
                    "Saldo inicial",
                ),
            )

        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "id": nuevo_id})


@sales_api_bp.post("/api/fiados/<int:id_cliente>/sumar")
@login_required
def api_fiados_sumar(id_cliente: int):
    datos = request.get_json(silent=True) or {}
    try:
        monto = float(datos.get("monto", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400

    if monto <= 0:
        return jsonify({"ok": False, "msg": "El monto debe ser mayor a cero."}), 400

    concepto = str(datos.get("concepto", "Fiado")).strip() or "Fiado"

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_cliente FROM clientes WHERE id_cliente = %s AND id_tienda = %s LIMIT 1",
            (id_cliente, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Cliente no encontrado."}), 404

        id_turno = _obtener_turno_abierto(session["id_tienda"], cur)
        if not id_turno:
            return jsonify({"ok": False, "msg": "No hay turno abierto."}), 409

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM ventas WHERE id_tienda = %s",
            (session["id_tienda"],),
        )
        cnt = cur.fetchone()["cnt"]
        numero_venta = f"F{session['id_tienda']:04d}-{cnt + 1:06d}"

        cur.execute(
            "INSERT INTO ventas "
            "(id_tienda, id_turno, id_cajero, id_cliente, numero_venta, "
            " subtotal, total_final, metodo_pago, estado_venta, observaciones) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'Efectivo','Fiada/Pendiente',%s)",
            (
                session["id_tienda"],
                id_turno,
                session["id_usuario"],
                id_cliente,
                numero_venta,
                monto,
                monto,
                concepto,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


@sales_api_bp.post("/api/fiados/<int:id_cliente>/abonar")
@login_required
def api_fiados_abonar(id_cliente: int):
    datos = request.get_json(silent=True) or {}
    try:
        monto = float(datos.get("monto", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400

    if monto <= 0:
        return jsonify({"ok": False, "msg": "El monto debe ser mayor a cero."}), 400

    metodo = normalizar_metodo_pago(datos.get("metodo", "efectivo"))
    if not metodo:
        return jsonify({"ok": False, "msg": "Metodo invalido."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_cliente FROM clientes WHERE id_cliente = %s AND id_tienda = %s LIMIT 1",
            (id_cliente, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Cliente no encontrado."}), 404

        cur.execute(
            "SELECT v.id_venta, v.total_final, "
            "COALESCE((SELECT SUM(ab.monto_abonado) FROM abonos_fiados ab "
            "WHERE ab.id_venta = v.id_venta), 0) AS abonado "
            "FROM ventas v "
            "WHERE v.id_cliente = %s AND v.id_tienda = %s "
            "AND v.estado_venta = 'Fiada/Pendiente' "
            "ORDER BY v.id_venta ASC LIMIT 1",
            (id_cliente, session["id_tienda"]),
        )
        venta = cur.fetchone()
        if not venta:
            return jsonify({"ok": False, "msg": "Este cliente no tiene deuda pendiente."}), 404

        deuda_actual = max(0.0, float(venta.get("total_final") or 0) - float(venta.get("abonado") or 0))
        if monto <= 0 or monto > deuda_actual:
            return jsonify({
                "ok": False,
                "error": "El monto debe ser mayor a 0 y no puede superar la deuda actual.",
            }), 400

        cur.execute(
            "INSERT INTO abonos_fiados "
            "(id_tienda, id_venta, id_usuario, monto_abonado, metodo_pago) "
            "VALUES (%s,%s,%s,%s,%s)",
            (session["id_tienda"], venta["id_venta"], session["id_usuario"], monto, metodo),
        )

        if float(venta["abonado"]) + monto >= float(venta["total_final"]):
            cur.execute(
                "UPDATE ventas SET estado_venta = 'Pagada' WHERE id_venta = %s",
                (venta["id_venta"],),
            )

        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


@sales_api_bp.get("/api/gastos")
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_gastos_listar():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT gc.id_gasto, gc.concepto, gc.descripcion, gc.monto, gc.fuente_dinero, "
            "UNIX_TIMESTAMP(gc.fecha_creacion) * 1000 AS ts "
            "FROM gastos_caja gc "
            "WHERE gc.id_tienda = %s AND gc.id_usuario = %s "
            "ORDER BY gc.id_gasto DESC LIMIT 100",
            (session["id_tienda"], session["id_usuario"]),
        )
        filas = cur.fetchall()
    finally:
        conn.close()

    return jsonify({"ok": True, "gastos": [
        {
            "id": r["id_gasto"],
            "category": r["concepto"],
            "desc": str(r.get("descripcion") or "").strip(),
            "origen": (r.get("fuente_dinero") or "Bancos"),
            "amount": float(r["monto"]),
            "ts": int(r["ts"] or 0),
        }
        for r in filas
    ]})


@sales_api_bp.post("/api/gastos")
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_gastos_crear():
    datos = request.get_json(silent=True) or {}
    concepto = str(datos.get("category", "")).strip()
    descripcion = str(datos.get("desc", "")).strip()
    metodo_pago = str(datos.get("metodo_pago", "Efectivo")).strip()
    fuente_dinero = str(datos.get("fuente_dinero", "")).strip()

    try:
        monto = float(datos.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400

    if monto <= 0:
        return jsonify({"ok": False, "msg": "El monto debe ser mayor a cero."}), 400
    if not concepto:
        return jsonify({"ok": False, "msg": "La categoria es requerida."}), 400
    if metodo_pago not in {"Efectivo", "Bancos"}:
        return jsonify({"ok": False, "msg": "Metodo de pago invalido."}), 400

    if metodo_pago == "Efectivo":
        if fuente_dinero not in {"Caja Menor", "Caja Fuerte"}:
            return jsonify({"ok": False, "msg": "Fuente de dinero invalida para efectivo."}), 400
    else:
        fuente_dinero = "Bancos"

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        id_turno = _obtener_turno_abierto(session["id_tienda"], cur)

        if metodo_pago == "Efectivo" and fuente_dinero == "Caja Menor" and not id_turno:
            return jsonify({"ok": False, "msg": "No hay turno activo para cargar gastos de Caja Menor."}), 409

        if not id_turno:
            cur.execute(
                "SELECT id_turno FROM turnos_caja "
                "WHERE id_tienda = %s "
                "ORDER BY fecha_apertura DESC LIMIT 1",
                (session["id_tienda"],),
            )
            fila_turno = cur.fetchone()
            if not fila_turno:
                return jsonify({"ok": False, "msg": "No existe ningun turno para registrar el gasto."}), 409
            id_turno = fila_turno["id_turno"]

        cur.execute(
            "INSERT INTO gastos_caja "
            "(id_tienda, id_turno, id_usuario, concepto, descripcion, monto, fuente_dinero) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (session["id_tienda"], id_turno, session["id_usuario"], concepto, descripcion, monto, fuente_dinero),
        )

        if metodo_pago == "Efectivo" and fuente_dinero == "Caja Menor":
            cur.execute(
                "UPDATE turnos_caja "
                "SET monto_final_esperado = COALESCE(monto_final_esperado, monto_inicial, 0) - %s "
                "WHERE id_turno = %s AND id_tienda = %s",
                (monto, id_turno, session["id_tienda"]),
            )

        conn.commit()
        nuevo_id = cur.lastrowid
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "registrar_gasto",
        f"Gasto id={nuevo_id}, categoria={concepto}, monto={monto}, fuente={fuente_dinero}",
    )
    return jsonify({"ok": True, "id": nuevo_id})
