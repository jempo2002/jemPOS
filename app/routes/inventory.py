from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from app.services.inventory_service import (
    InventoryNotFoundError,
    add_stock,
    create_producto,
    create_proveedor,
    delete_producto,
    delete_proveedor,
    get_categorias_inventario,
    get_productos_inventario,
    get_proveedor_productos,
    get_proveedores,
    list_categorias_api,
    list_inventario_api,
    update_producto,
    update_proveedor,
)
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import avatar_iniciales, only_digits

inventory_bp = Blueprint("inventory_bp", __name__, url_prefix="/inventario")
inventory_api_bp = Blueprint("inventory_api_bp", __name__)


def _base_context() -> dict:
    nombre = session.get("nombre_completo", "")
    return {
        "rol": session.get("rol", ""),
        "nombre_completo": nombre,
        "avatar_iniciales": avatar_iniciales(nombre),
        "mostrar_alerta_suscripcion": False,
        "dias_restantes": 0,
    }


def _parse_proveedor_id(raw_value):
    try:
        return int(raw_value) if raw_value not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        raise ValueError("Proveedor invalido.")


@inventory_bp.route("/")
@login_required
@roles_required("Admin", "Master", "Cajero")
def inventario_page():
    id_tienda = int(session["id_tienda"])
    ctx = _base_context()
    ctx.update(
        {
            "productos": get_productos_inventario(id_tienda),
            "categorias": get_categorias_inventario(id_tienda),
            "proveedores": get_proveedores(id_tienda),
        }
    )
    return render_template("pos/inventario.html", **ctx)


@inventory_api_bp.route("/api/inventario", methods=["GET"])
@inventory_api_bp.route("/inventario/api/productos", methods=["GET"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_list():
    productos = list_inventario_api(int(session["id_tienda"]))
    return jsonify({"ok": True, "productos": productos})


@inventory_api_bp.route("/api/inventario/categorias", methods=["GET"])
@inventory_api_bp.route("/api/categorias", methods=["GET"])
@inventory_api_bp.route("/inventario/api/categorias", methods=["GET"])
@login_required
def api_inventario_categorias():
    return jsonify({"ok": True, "categorias": list_categorias_api(int(session["id_tienda"]))})


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

    try:
        proveedor_id = _parse_proveedor_id(fuente.get("id_proveedor"))
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400

    if not nombre or not categoria:
        return jsonify({"ok": False, "msg": "Nombre y categoria son requeridos."}), 400
    if costo < 0 or venta < 0 or stock < 0:
        return jsonify({"ok": False, "msg": "Los valores no pueden ser negativos."}), 400

    try:
        new_id = create_producto(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            nombre,
            categoria,
            costo,
            venta,
            stock,
            proveedor_id,
        )
        return jsonify({"ok": True, "id": new_id})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo crear el producto."}), 500


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

    try:
        proveedor_id = _parse_proveedor_id(fuente.get("id_proveedor"))
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400

    if not nombre or not categoria:
        return jsonify({"ok": False, "msg": "Nombre y categoria son requeridos."}), 400

    try:
        update_producto(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            int(id_producto),
            nombre,
            categoria,
            costo,
            venta,
            stock,
            proveedor_id,
        )
        return jsonify({"ok": True})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo actualizar el producto."}), 500


@inventory_api_bp.route("/api/inventario/<int:id_producto>", methods=["DELETE"])
@inventory_api_bp.route("/inventario/api/productos/<int:id_producto>", methods=["DELETE"])
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_inventario_delete(id_producto: int):
    try:
        delete_producto(int(session["id_tienda"]), int(session["id_usuario"]), int(id_producto))
        return jsonify({"ok": True})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo eliminar el producto."}), 500


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

    try:
        nuevo_stock = add_stock(int(session["id_tienda"]), int(session["id_usuario"]), int(id_producto), int(cantidad))
        return jsonify({"ok": True, "nuevo_stock": nuevo_stock})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo actualizar el stock."}), 500


@inventory_api_bp.route("/api/proveedores", methods=["GET"])
@inventory_api_bp.route("/inventario/api/proveedores", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_list():
    return jsonify({"ok": True, "proveedores": get_proveedores(int(session["id_tienda"]))})


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

    try:
        new_id = create_proveedor(int(session["id_tienda"]), int(session["id_usuario"]), empresa, contacto, celular, correo, detalles)
        return jsonify({"ok": True, "id": new_id})
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo crear el proveedor."}), 500


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

    try:
        update_proveedor(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            int(id_proveedor),
            empresa,
            contacto,
            celular,
            correo,
            detalles,
        )
        return jsonify({"ok": True})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo actualizar el proveedor."}), 500


@inventory_api_bp.route("/api/proveedores/<int:id_proveedor>", methods=["DELETE"])
@inventory_api_bp.route("/inventario/api/proveedores/<int:id_proveedor>", methods=["DELETE"])
@login_required
@roles_required("Admin", "Master")
def api_proveedores_delete(id_proveedor: int):
    try:
        delete_proveedor(int(session["id_tienda"]), int(session["id_usuario"]), int(id_proveedor), soft_products=True)
        return jsonify({"ok": True})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo eliminar el proveedor."}), 500


@inventory_api_bp.route("/api/proveedores/<int:id_proveedor>/productos", methods=["GET"])
@inventory_api_bp.route("/inventario/api/proveedores/<int:id_proveedor>/productos", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_proveedor_productos(id_proveedor: int):
    try:
        data = get_proveedor_productos(int(session["id_tienda"]), int(id_proveedor))
        return jsonify({"ok": True, **data})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
