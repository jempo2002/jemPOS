from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, session

from app.utils.decorators import login_required, roles_required
from app.utils.helpers import avatar_iniciales
from database import get_db

inventory_bp = Blueprint("inventory_bp", __name__, url_prefix="/inventario")
inventory_api_bp = Blueprint("inventory_api_bp", __name__)


def _get_categorias_inventario(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT nombre FROM categorias WHERE id_tienda = %s ORDER BY nombre",
            (id_tienda,),
        )
        return [r[0] for r in cur.fetchall() if r and r[0]]
    finally:
        conn.close()


def _get_proveedores(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor, nombre_empresa, nombre_contacto, celular, correo, detalles "
            "FROM proveedores "
            "WHERE id_tienda = %s "
            "ORDER BY nombre_empresa",
            (id_tienda,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": r["id_proveedor"],
            "empresa": r.get("nombre_empresa") or "",
            "contacto": r.get("nombre_contacto") or "",
            "celular": r.get("celular") or "",
            "correo": r.get("correo") or "",
            "detalles": r.get("detalles") or "",
        }
        for r in rows
    ]


def _get_insumos(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT i.id_insumo, i.nombre, i.stock_actual, i.unidad_medida, i.costo_unitario, "
            "i.id_proveedor, p.nombre_empresa AS proveedor_nombre "
            "FROM insumos i "
            "LEFT JOIN proveedores p ON p.id_proveedor = i.id_proveedor "
            "WHERE i.id_tienda = %s "
            "ORDER BY i.nombre",
            (id_tienda,),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        {
            "id_insumo": r.get("id_insumo"),
            "nombre": r.get("nombre") or "",
            "stock_actual": float(r.get("stock_actual") or 0),
            "unidad_medida": (r.get("unidad_medida") or "Un").strip() or "Un",
            "costo_unitario": float(r.get("costo_unitario") or 0),
            "id_proveedor": r.get("id_proveedor"),
            "proveedor_nombre": r.get("proveedor_nombre") or "Sin proveedor",
        }
        for r in rows
    ]


def _get_productos_inventario(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT p.id_producto, p.nombre, c.nombre AS categoria, p.precio_costo, p.precio_venta, "
            "p.stock_actual, p.id_proveedor, COALESCE(p.es_preparado, 0) AS es_preparado "
            "FROM productos p "
            "LEFT JOIN categorias c ON c.id_categoria = p.id_categoria "
            "WHERE p.id_tienda=%s AND p.estado_activo=1 "
            "ORDER BY p.nombre",
            (id_tienda,),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        {
            "id": r.get("id_producto"),
            "nombre": r.get("nombre") or "",
            "categoria": r.get("categoria") or "",
            "precio_costo": float(r.get("precio_costo") or 0),
            "precio_venta": float(r.get("precio_venta") or 0),
            "stock_actual": float(r.get("stock_actual") or 0),
            "id_proveedor": r.get("id_proveedor"),
            "es_preparado": bool(r.get("es_preparado") or 0),
        }
        for r in rows
    ]


def _base_context() -> dict:
    nombre = session.get("nombre_completo", "")
    return {
        "rol": session.get("rol", ""),
        "nombre_completo": nombre,
        "foto_perfil": session.get("foto_perfil"),
        "avatar_iniciales": avatar_iniciales(nombre),
        "mostrar_alerta_suscripcion": False,
        "dias_restantes": 0,
    }


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


def _obtener_o_crear_categoria(cur, id_tienda: int, categoria: str) -> int:
    cur.execute(
        "SELECT id_categoria FROM categorias "
        "WHERE nombre = %s AND id_tienda = %s LIMIT 1",
        (categoria, id_tienda),
    )
    row = cur.fetchone()
    if row:
        return row["id_categoria"]

    cur.execute(
        "INSERT INTO categorias (id_tienda, nombre) VALUES (%s, %s)",
        (id_tienda, categoria),
    )
    return cur.lastrowid


def _parse_ingredientes(ingredientes_raw: list) -> list[dict]:
    ingredientes = []
    for item in ingredientes_raw:
        try:
            id_insumo = int(item.get("id_insumo"))
            cantidad = float(item.get("cantidad"))
            if id_insumo <= 0 or cantidad <= 0:
                continue
            ingredientes.append({"id_insumo": id_insumo, "cantidad": cantidad})
        except (TypeError, ValueError, AttributeError):
            continue
    return ingredientes


@inventory_bp.route("/")
@login_required
@roles_required("Admin", "Master", "Cajero")
def inventario_page():
    id_tienda = session["id_tienda"]
    ctx = _base_context()
    ctx.update(
        {
            "productos": _get_productos_inventario(id_tienda),
            "insumos": _get_insumos(id_tienda),
            "categorias": _get_categorias_inventario(id_tienda),
            "proveedores": _get_proveedores(id_tienda),
        }
    )
    return render_template("pos/inventario.html", **ctx)


@inventory_bp.route("/insumos")
@login_required
@roles_required("Admin", "Master")
def insumos_page():
    id_tienda = session["id_tienda"]
    ctx = _base_context()
    ctx.update(
        {
            "insumos": _get_insumos(id_tienda),
            "proveedores": _get_proveedores(id_tienda),
        }
    )
    return render_template("pos/insumos.html", **ctx)


@inventory_bp.route("/proveedores")
@login_required
@roles_required("Admin", "Master")
def proveedores_page():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM proveedores WHERE id_tienda = %s ORDER BY nombre_empresa",
            (session["id_tienda"],),
        )
        proveedores = cur.fetchall()
    finally:
        conn.close()

    ctx = _base_context()
    ctx.update({"proveedores": proveedores})
    return render_template("pos/proveedores.html", **ctx)


@inventory_api_bp.route("/api/inventario", methods=["GET"])
@inventory_api_bp.route("/inventario/api/productos", methods=["GET"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_list():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT p.id_producto, p.nombre, c.nombre AS categoria, "
            "p.precio_costo, p.precio_venta, p.stock_actual, p.stock_minimo_alerta, "
            "p.id_proveedor, pr.nombre_empresa AS proveedor_nombre, COALESCE(p.es_preparado, 0) AS es_preparado "
            "FROM productos p "
            "LEFT JOIN categorias c ON c.id_categoria = p.id_categoria "
            "LEFT JOIN proveedores pr ON pr.id_proveedor = p.id_proveedor "
            "WHERE p.id_tienda = %s AND p.estado_activo = 1 "
            "ORDER BY p.nombre",
            (session["id_tienda"],),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return jsonify(
        {
            "ok": True,
            "productos": [
                {
                    "id": r["id_producto"],
                    "name": r["nombre"],
                    "category": r["categoria"] or "",
                    "cost": float(r["precio_costo"]),
                    "sale": float(r["precio_venta"]),
                    "stock": r["stock_actual"],
                    "stock_min": r["stock_minimo_alerta"] or 0,
                    "proveedor_id": r.get("id_proveedor"),
                    "proveedor_nombre": r.get("proveedor_nombre") or "",
                    "es_preparado": bool(r.get("es_preparado") or 0),
                }
                for r in rows
            ],
        }
    )


@inventory_api_bp.route("/api/inventario/categorias", methods=["GET"])
@inventory_api_bp.route("/api/categorias", methods=["GET"])
@inventory_api_bp.route("/inventario/api/categorias", methods=["GET"])
@login_required
def api_inventario_categorias():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT nombre FROM categorias "
            "WHERE id_tienda = %s AND estado_activo = 1 ORDER BY nombre",
            (session["id_tienda"],),
        )
        cats = cur.fetchall()
    finally:
        conn.close()

    return jsonify({"ok": True, "categorias": [r["nombre"] for r in cats]})


@inventory_api_bp.route("/api/inventario", methods=["POST"])
@inventory_api_bp.route("/inventario/api/productos", methods=["POST"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_create():
    data = request.get_json(silent=True)
    is_json = data is not None
    data = data or {}

    fuente = data if is_json else request.form
    nombre = str(fuente.get("nombre", "")).strip()
    categoria = str(fuente.get("categoria", "")).strip()

    try:
        costo = float(fuente.get("costo", 0) or 0)
        venta = float(fuente.get("venta", 0) or 0)
        stock = float(fuente.get("stock", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Valores numericos invalidos."}), 400

    es_preparado = bool(data.get("es_preparado")) if is_json else (request.form.get("es_preparado") == "on")
    if es_preparado:
        stock = 0

    if is_json:
        ingredientes_raw = data.get("ingredientes") or []
    else:
        ids = request.form.getlist("id_insumo[]")
        cants = request.form.getlist("cantidad_insumo[]")
        ingredientes_raw = [{"id_insumo": i, "cantidad": c} for i, c in zip(ids, cants)]

    ingredientes = _parse_ingredientes(ingredientes_raw)

    if es_preparado and not ingredientes:
        return jsonify({"ok": False, "msg": "Agrega al menos un ingrediente para la receta."}), 400

    proveedor_id = fuente.get("id_proveedor")
    try:
        proveedor_id = int(proveedor_id) if proveedor_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Proveedor invalido."}), 400

    if not nombre or not categoria:
        return jsonify({"ok": False, "msg": "Nombre y categoria son requeridos."}), 400
    if costo < 0 or venta < 0 or stock < 0:
        return jsonify({"ok": False, "msg": "Los valores no pueden ser negativos."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, session["id_tienda"]),
            )
            if not cur.fetchone():
                return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        id_cat = _obtener_o_crear_categoria(cur, int(session["id_tienda"]), categoria)

        cur.execute(
            "INSERT INTO productos "
            "(id_tienda, id_categoria, nombre, precio_costo, precio_venta, stock_actual, id_proveedor, es_preparado) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (session["id_tienda"], id_cat, nombre, costo, venta, stock, proveedor_id, 1 if es_preparado else 0),
        )
        new_id = cur.lastrowid

        if es_preparado:
            for ing in ingredientes:
                cur.execute(
                    "INSERT INTO recetas_productos (id_producto, id_insumo, cantidad_requerida) "
                    "VALUES (%s, %s, %s)",
                    (new_id, ing["id_insumo"], ing["cantidad"]),
                )

        conn.commit()
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo crear el producto."}), 500
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "crear_producto",
        f"Producto creado id={new_id}, nombre={nombre}",
    )
    return jsonify({"ok": True, "id": new_id})


@inventory_api_bp.route("/api/inventario/<int:id_producto>", methods=["PUT"])
@inventory_api_bp.route("/inventario/api/productos/<int:id_producto>", methods=["PUT"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_update(id_producto: int):
    data = request.get_json(silent=True)
    is_json = data is not None
    data = data or {}

    fuente = data if is_json else request.form
    nombre = str(fuente.get("nombre", "")).strip()
    categoria = str(fuente.get("categoria", "")).strip()

    try:
        costo = float(fuente.get("costo", 0) or 0)
        venta = float(fuente.get("venta", 0) or 0)
        stock = float(fuente.get("stock", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Valores numericos invalidos."}), 400

    es_preparado = bool(data.get("es_preparado")) if is_json else (request.form.get("es_preparado") == "on")
    if es_preparado:
        stock = 0

    if is_json:
        ingredientes_raw = data.get("ingredientes") or []
    else:
        ids = request.form.getlist("id_insumo[]")
        cants = request.form.getlist("cantidad_insumo[]")
        ingredientes_raw = [{"id_insumo": i, "cantidad": c} for i, c in zip(ids, cants)]
    ingredientes = _parse_ingredientes(ingredientes_raw)

    if es_preparado and not ingredientes:
        return jsonify({"ok": False, "msg": "Agrega al menos un ingrediente para la receta."}), 400

    proveedor_id = fuente.get("id_proveedor")
    try:
        proveedor_id = int(proveedor_id) if proveedor_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Proveedor invalido."}), 400

    if not nombre or not categoria:
        return jsonify({"ok": False, "msg": "Nombre y categoria son requeridos."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_producto FROM productos "
            "WHERE id_producto = %s AND id_tienda = %s LIMIT 1",
            (id_producto, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Producto no encontrado."}), 404

        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, session["id_tienda"]),
            )
            if not cur.fetchone():
                return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        id_cat = _obtener_o_crear_categoria(cur, int(session["id_tienda"]), categoria)

        cur.execute(
            "UPDATE productos "
            "SET nombre=%s, id_categoria=%s, precio_costo=%s, precio_venta=%s, stock_actual=%s, id_proveedor=%s, es_preparado=%s "
            "WHERE id_producto=%s AND id_tienda=%s",
            (
                nombre,
                id_cat,
                costo,
                venta,
                stock,
                proveedor_id,
                1 if es_preparado else 0,
                id_producto,
                session["id_tienda"],
            ),
        )

        cur.execute("DELETE FROM recetas_productos WHERE id_producto=%s", (id_producto,))
        if es_preparado:
            for ing in ingredientes:
                cur.execute(
                    "INSERT INTO recetas_productos (id_producto, id_insumo, cantidad_requerida) "
                    "VALUES (%s, %s, %s)",
                    (id_producto, ing["id_insumo"], ing["cantidad"]),
                )

        conn.commit()
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo actualizar el producto."}), 500
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "editar_producto",
        f"Producto editado id={id_producto}, nombre={nombre}",
    )
    return jsonify({"ok": True})


@inventory_api_bp.route("/api/inventario/<int:id_producto>", methods=["DELETE"])
@inventory_api_bp.route("/inventario/api/productos/<int:id_producto>", methods=["DELETE"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_delete(id_producto: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE productos SET estado_activo = 0 "
            "WHERE id_producto = %s AND id_tienda = %s",
            (id_producto, session["id_tienda"]),
        )
        if cur.rowcount == 0:
            return jsonify({"ok": False, "msg": "Producto no encontrado."}), 404
        conn.commit()
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo eliminar el producto."}), 500
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "eliminar_producto",
        f"Producto desactivado id={id_producto}",
    )
    return jsonify({"ok": True})


@inventory_api_bp.route("/api/inventario/stock", methods=["POST"])
@inventory_api_bp.route("/api/inventario/<int:id_producto>/stock", methods=["POST"])
@inventory_api_bp.route("/inventario/api/productos/stock", methods=["POST"])
@inventory_api_bp.route("/inventario/api/productos/<int:id_producto>/stock", methods=["POST"])
@login_required
def api_inventario_stock(id_producto: int | None = None):
    data = request.get_json(silent=True) or {}
    if id_producto is None:
        try:
            id_producto = int(data.get("id_producto", 0))
        except (TypeError, ValueError):
            id_producto = 0

    try:
        cantidad = int(data.get("cantidad", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Cantidad invalida."}), 400

    if id_producto <= 0:
        return jsonify({"ok": False, "msg": "Producto invalido."}), 400
    if cantidad <= 0:
        return jsonify({"ok": False, "msg": "La cantidad debe ser mayor a cero."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_producto, stock_actual, COALESCE(es_preparado, 0) AS es_preparado "
            "FROM productos "
            "WHERE id_producto = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
            (id_producto, session["id_tienda"]),
        )
        p = cur.fetchone()
        if not p:
            return jsonify({"ok": False, "msg": "Producto no encontrado."}), 404
        if bool(p.get("es_preparado") or 0):
            return jsonify({"ok": False, "msg": "El stock de platos preparados se calcula desde sus insumos."}), 400

        nuevo_stock = p["stock_actual"] + cantidad
        cur.execute(
            "UPDATE productos SET stock_actual = %s WHERE id_producto = %s AND id_tienda = %s",
            (nuevo_stock, id_producto, session["id_tienda"]),
        )
        cur.execute(
            "INSERT INTO movimientos_inventario "
            "(id_tienda, id_producto, id_usuario, tipo_movimiento, cantidad, stock_anterior, stock_posterior) "
            "VALUES (%s, %s, %s, 'Entrada', %s, %s, %s)",
            (
                session["id_tienda"],
                id_producto,
                session["id_usuario"],
                cantidad,
                p["stock_actual"],
                nuevo_stock,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo actualizar el stock."}), 500
    finally:
        conn.close()

    return jsonify({"ok": True, "nuevo_stock": nuevo_stock})


@inventory_api_bp.route("/api/proveedores", methods=["GET"])
@inventory_api_bp.route("/inventario/api/proveedores", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_list():
    return jsonify({"ok": True, "proveedores": _get_proveedores(session["id_tienda"])})


@inventory_api_bp.route("/api/proveedores", methods=["POST"])
@inventory_api_bp.route("/inventario/api/proveedores", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_create():
    data = request.get_json(silent=True) or {}
    empresa = str(data.get("empresa", "")).strip()
    contacto = str(data.get("contacto", "")).strip()
    celular = str(data.get("celular", "")).strip()
    correo = str(data.get("correo", "")).strip()
    detalles = str(data.get("detalles", "")).strip()

    if not empresa:
        return jsonify({"ok": False, "msg": "La empresa es requerida."}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO proveedores "
            "(id_tienda, nombre_empresa, nombre_contacto, celular, correo, detalles) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                session["id_tienda"],
                empresa,
                contacto or None,
                celular or None,
                correo or None,
                detalles or None,
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo crear el proveedor."}), 500
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "crear_proveedor",
        f"Proveedor creado id={new_id}, empresa={empresa}",
    )
    return jsonify({"ok": True, "id": new_id})


@inventory_api_bp.route("/api/proveedores/<int:id_proveedor>", methods=["PUT"])
@inventory_api_bp.route("/inventario/api/proveedores/<int:id_proveedor>", methods=["PUT"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_update(id_proveedor: int):
    data = request.get_json(silent=True) or {}
    empresa = str(data.get("empresa", "")).strip()
    contacto = str(data.get("contacto", "")).strip()
    celular = str(data.get("celular", "")).strip()
    correo = str(data.get("correo", "")).strip()
    detalles = str(data.get("detalles", "")).strip()

    if not empresa:
        return jsonify({"ok": False, "msg": "La empresa es requerida."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
            (id_proveedor, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        cur.execute(
            "UPDATE proveedores "
            "SET nombre_empresa=%s, nombre_contacto=%s, celular=%s, correo=%s, detalles=%s "
            "WHERE id_proveedor=%s AND id_tienda=%s",
            (
                empresa,
                contacto or None,
                celular or None,
                correo or None,
                detalles or None,
                id_proveedor,
                session["id_tienda"],
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo actualizar el proveedor."}), 500
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "editar_proveedor",
        f"Proveedor editado id={id_proveedor}, empresa={empresa}",
    )
    return jsonify({"ok": True})


@inventory_api_bp.route("/api/proveedores/<int:id_proveedor>", methods=["DELETE"])
@inventory_api_bp.route("/inventario/api/proveedores/<int:id_proveedor>", methods=["DELETE"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_delete(id_proveedor: int):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
            (id_proveedor, session["id_tienda"]),
        )
        if not cur.fetchone():
            return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        cur.execute(
            "UPDATE productos SET id_proveedor = NULL WHERE id_proveedor=%s AND id_tienda=%s",
            (id_proveedor, session["id_tienda"]),
        )
        cur.execute(
            "DELETE FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s",
            (id_proveedor, session["id_tienda"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo eliminar el proveedor."}), 500
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "eliminar_proveedor",
        f"Proveedor eliminado id={id_proveedor}",
    )
    return jsonify({"ok": True})


@inventory_api_bp.route("/api/proveedores/<int:id_proveedor>/productos", methods=["GET"])
@inventory_api_bp.route("/inventario/api/proveedores/<int:id_proveedor>/productos", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_proveedor_productos(id_proveedor: int):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor, nombre_empresa "
            "FROM proveedores "
            "WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
            (id_proveedor, session["id_tienda"]),
        )
        prov = cur.fetchone()
        if not prov:
            return jsonify({"ok": False, "msg": "Proveedor no encontrado."}), 404

        cur.execute(
            "SELECT id_producto, nombre, precio_venta, stock_actual "
            "FROM productos "
            "WHERE id_tienda=%s AND id_proveedor=%s AND estado_activo=1 "
            "ORDER BY nombre",
            (session["id_tienda"], id_proveedor),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return jsonify(
        {
            "ok": True,
            "proveedor": {
                "id": prov["id_proveedor"],
                "empresa": prov.get("nombre_empresa") or "",
            },
            "productos": [
                {
                    "id": r["id_producto"],
                    "nombre": r["nombre"],
                    "precio_venta": float(r.get("precio_venta") or 0),
                    "stock_actual": int(r.get("stock_actual") or 0),
                }
                for r in rows
            ],
        }
    )


@inventory_api_bp.route("/api/insumos", methods=["GET"])
@inventory_api_bp.route("/inventario/api/insumos", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_insumos_list():
    return jsonify({"ok": True, "insumos": _get_insumos(session["id_tienda"])})


@inventory_api_bp.route("/api/insumos", methods=["POST"])
@inventory_api_bp.route("/inventario/api/insumos", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_insumos_create():
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    unidad = str(data.get("unidad_medida", "Un")).strip() or "Un"
    proveedor_raw = data.get("id_proveedor")

    try:
        stock = float(data.get("stock_actual", 0) or 0)
        costo = float(data.get("costo_unitario", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Stock y costo deben ser numericos."}), 400

    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre del insumo es requerido."}), 400

    if unidad not in {"Gr", "Ml", "Un"}:
        return jsonify({"ok": False, "msg": "Unidad invalida. Usa Gr, Ml o Un."}), 400

    if stock < 0 or costo < 0:
        return jsonify({"ok": False, "msg": "Stock y costo no pueden ser negativos."}), 400

    try:
        proveedor_id = int(proveedor_raw) if proveedor_raw not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Proveedor invalido."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, session["id_tienda"]),
            )
            if not cur.fetchone():
                return jsonify({"ok": False, "msg": "Proveedor no encontrado para esta tienda."}), 404

        cur.execute(
            "INSERT INTO insumos "
            "(id_tienda, nombre, stock_actual, unidad_medida, costo_unitario, id_proveedor) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (session["id_tienda"], nombre, stock, unidad, costo, proveedor_id),
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo crear el insumo."}), 500
    finally:
        conn.close()

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "crear_insumo",
        f"Insumo creado id={new_id}, nombre={nombre}",
    )
    return jsonify({"ok": True, "id": new_id})


@inventory_api_bp.route("/api/insumos/<int:id_insumo>", methods=["PUT"])
@inventory_api_bp.route("/inventario/api/insumos/<int:id_insumo>", methods=["PUT"])
@login_required
@roles_required("Admin", "Master")
def api_insumos_update(id_insumo: int):
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    unidad = str(data.get("unidad_medida", "Un")).strip() or "Un"
    proveedor_raw = data.get("id_proveedor")

    try:
        stock = float(data.get("stock_actual", 0) or 0)
        costo = float(data.get("costo_unitario", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Stock y costo deben ser numericos."}), 400

    if not nombre:
        return jsonify({"ok": False, "msg": "El nombre del insumo es requerido."}), 400

    if unidad not in {"Gr", "Ml", "Un"}:
        return jsonify({"ok": False, "msg": "Unidad invalida. Usa Gr, Ml o Un."}), 400

    if stock < 0 or costo < 0:
        return jsonify({"ok": False, "msg": "Stock y costo no pueden ser negativos."}), 400

    try:
        proveedor_id = int(proveedor_raw) if proveedor_raw not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Proveedor invalido."}), 400

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, session["id_tienda"]),
            )
            if not cur.fetchone():
                return jsonify({"ok": False, "msg": "Proveedor no encontrado para esta tienda."}), 404

        cur.execute(
            "UPDATE insumos "
            "SET nombre=%s, stock_actual=%s, unidad_medida=%s, costo_unitario=%s, id_proveedor=%s "
            "WHERE id_insumo=%s AND id_tienda=%s",
            (nombre, stock, unidad, costo, proveedor_id, id_insumo, session["id_tienda"]),
        )
        conn.commit()
        updated = cur.rowcount > 0
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo actualizar el insumo."}), 500
    finally:
        conn.close()

    if not updated:
        return jsonify({"ok": False, "msg": "Insumo no encontrado para esta tienda."}), 404

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "editar_insumo",
        f"Insumo editado id={id_insumo}, nombre={nombre}",
    )
    return jsonify({"ok": True})


@inventory_api_bp.route("/api/insumos/<int:id_insumo>", methods=["DELETE"])
@inventory_api_bp.route("/inventario/api/insumos/<int:id_insumo>", methods=["DELETE"])
@login_required
@roles_required("Admin", "Master")
def api_insumos_delete(id_insumo: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM insumos WHERE id_insumo=%s AND id_tienda=%s",
            (id_insumo, session["id_tienda"]),
        )
        conn.commit()
        deleted = cur.rowcount > 0
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "msg": "No se pudo eliminar el insumo."}), 500
    finally:
        conn.close()

    if not deleted:
        return jsonify({"ok": False, "msg": "Insumo no encontrado para esta tienda."}), 404

    _registrar_auditoria(
        session.get("id_tienda"),
        session.get("id_usuario"),
        "eliminar_insumo",
        f"Insumo eliminado id={id_insumo}",
    )
    return jsonify({"ok": True})
