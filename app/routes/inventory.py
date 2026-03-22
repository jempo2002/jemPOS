from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from app.services.inventory_service import (
    InventoryNotFoundError,
    add_stock,
    create_insumo,
    create_producto,
    create_proveedor,
    delete_insumo,
    delete_producto,
    delete_proveedor,
    get_categorias_inventario,
    get_insumos,
    get_productos_inventario,
    get_proveedor_productos,
    get_proveedores,
    get_proveedores_page,
    list_categorias_api,
    list_inventario_api,
    update_insumo,
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
        "foto_perfil": session.get("foto_perfil"),
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
            "insumos": get_insumos(id_tienda),
            "categorias": get_categorias_inventario(id_tienda),
            "proveedores": get_proveedores(id_tienda),
        }
    )
    return render_template("pos/inventario.html", **ctx)


@inventory_bp.route("/insumos")
@login_required
@roles_required("Admin", "Master")
def insumos_page():
    id_tienda = int(session["id_tienda"])
    ctx = _base_context()
    ctx.update(
        {
            "insumos": get_insumos(id_tienda),
            "proveedores": get_proveedores(id_tienda),
        }
    )
    return render_template("pos/insumos.html", **ctx)


@inventory_bp.route("/proveedores")
@login_required
@roles_required("Admin", "Master")
def proveedores_page():
    ctx = _base_context()
    ctx.update({"proveedores": get_proveedores_page(int(session["id_tienda"]))})
    return render_template("pos/proveedores.html", **ctx)


@inventory_api_bp.route("/insumos/crear", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def insumos_crear_page():
    nombre = str(request.form.get("nombre", "")).strip()
    unidad = str(request.form.get("unidad_medida", "Un")).strip() or "Un"

    try:
        stock = float(request.form.get("stock_actual", 0) or 0)
        costo = float(request.form.get("costo_unitario", 0) or 0)
    except (TypeError, ValueError):
        flash("Stock y costo deben ser numericos.", "error")
        return redirect(url_for("inventory_bp.insumos_page"))

    if not nombre:
        flash("El nombre del insumo es requerido.", "error")
        return redirect(url_for("inventory_bp.insumos_page"))

    if unidad not in {"Gr", "Ml", "Un"}:
        flash("Unidad invalida. Usa Gr, Ml o Un.", "error")
        return redirect(url_for("inventory_bp.insumos_page"))

    if stock < 0 or costo < 0:
        flash("Stock y costo no pueden ser negativos.", "error")
        return redirect(url_for("inventory_bp.insumos_page"))

    try:
        proveedor_id = _parse_proveedor_id(request.form.get("id_proveedor"))
        create_insumo(int(session["id_tienda"]), int(session["id_usuario"]), nombre, unidad, stock, costo, proveedor_id)
    except InventoryNotFoundError as exc:
        flash(str(exc), "error")
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("No fue posible crear el insumo. Verifica migraciones de base de datos.", "error")
        return redirect(url_for("inventory_bp.insumos_page"))

    if '_flashes' not in session or not any(cat == 'error' for cat, _ in session.get('_flashes', [])):
        flash("Insumo creado correctamente.", "success")
    return redirect(url_for("inventory_bp.insumos_page"))


@inventory_api_bp.route("/insumos/editar/<int:id_insumo>", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def insumos_editar_page(id_insumo):
    nombre = str(request.form.get("nombre", "")).strip()
    unidad = str(request.form.get("unidad_medida", "Un")).strip() or "Un"

    try:
        stock = float(request.form.get("stock_actual", 0) or 0)
        costo = float(request.form.get("costo_unitario", 0) or 0)
    except (TypeError, ValueError):
        flash("Stock y costo deben ser numericos.", "error")
        return redirect(url_for("inventory_bp.insumos_page"))

    if not nombre:
        flash("El nombre del insumo es requerido.", "error")
        return redirect(url_for("inventory_bp.insumos_page"))

    if unidad not in {"Gr", "Ml", "Un"}:
        flash("Unidad invalida. Usa Gr, Ml o Un.", "error")
        return redirect(url_for("inventory_bp.insumos_page"))

    if stock < 0 or costo < 0:
        flash("Stock y costo no pueden ser negativos.", "error")
        return redirect(url_for("inventory_bp.insumos_page"))

    try:
        proveedor_id = _parse_proveedor_id(request.form.get("id_proveedor"))
        update_insumo(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            int(id_insumo),
            nombre,
            unidad,
            stock,
            costo,
            proveedor_id,
        )
        flash("Insumo actualizado correctamente.", "success")
    except InventoryNotFoundError as exc:
        flash(str(exc), "error")
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("No fue posible actualizar el insumo.", "error")

    return redirect(url_for("inventory_bp.insumos_page"))


@inventory_api_bp.route("/insumos/eliminar/<int:id_insumo>", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def insumos_eliminar_page(id_insumo):
    try:
        delete_insumo(int(session["id_tienda"]), int(session["id_usuario"]), int(id_insumo))
        flash("Insumo eliminado correctamente.", "success")
    except InventoryNotFoundError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("No fue posible eliminar el insumo.", "error")
    return redirect(url_for("inventory_bp.insumos_page"))


@inventory_api_bp.route("/proveedores/crear", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def proveedores_crear_page():
    empresa = str(request.form.get("empresa", "")).strip()
    nombre_contacto = str(request.form.get("nombre_contacto", "")).strip()
    celular = only_digits(request.form.get("celular"))
    correo = str(request.form.get("correo", "")).strip()
    detalles = str(request.form.get("detalles", "")).strip()

    if not empresa:
        flash("La empresa es requerida.", "error")
        return redirect(url_for("inventory_bp.proveedores_page"))

    if celular and len(celular) > 10:
        flash("El celular debe tener maximo 10 digitos.", "error")
        return redirect(url_for("inventory_bp.proveedores_page"))

    try:
        create_proveedor(int(session["id_tienda"]), int(session["id_usuario"]), empresa, nombre_contacto, celular, correo, detalles)
        flash("Proveedor creado correctamente.", "success")
    except Exception:
        flash("No fue posible crear el proveedor.", "error")

    return redirect(url_for("inventory_bp.proveedores_page"))


@inventory_api_bp.route("/proveedores/editar/<int:id_proveedor>", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def proveedores_editar_page(id_proveedor):
    empresa = str(request.form.get("empresa", "")).strip()
    nombre_contacto = str(request.form.get("nombre_contacto", "")).strip()
    celular = only_digits(request.form.get("celular"))
    correo = str(request.form.get("correo", "")).strip()
    detalles = str(request.form.get("detalles", "")).strip()

    if not empresa:
        flash("La empresa es requerida.", "error")
        return redirect(url_for("inventory_bp.proveedores_page"))

    if celular and len(celular) > 10:
        flash("El celular debe tener maximo 10 digitos.", "error")
        return redirect(url_for("inventory_bp.proveedores_page"))

    try:
        update_proveedor(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            int(id_proveedor),
            empresa,
            nombre_contacto,
            celular,
            correo,
            detalles,
        )
        flash("Proveedor actualizado correctamente.", "success")
    except InventoryNotFoundError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("No fue posible actualizar el proveedor.", "error")

    return redirect(url_for("inventory_bp.proveedores_page"))


@inventory_api_bp.route("/proveedores/eliminar/<int:id_proveedor>", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def proveedores_eliminar_page(id_proveedor):
    try:
        delete_proveedor(int(session["id_tienda"]), int(session["id_usuario"]), int(id_proveedor))
        flash("Proveedor eliminado correctamente.", "success")
    except InventoryNotFoundError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("No fue posible eliminar el proveedor.", "error")
    return redirect(url_for("inventory_bp.proveedores_page"))


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

    es_preparado = bool(data.get("es_preparado")) if is_json else (request.form.get("es_preparado") == "on")
    if es_preparado:
        stock = 0

    if is_json:
        ingredientes_raw = data.get("ingredientes") or []
    else:
        ids = request.form.getlist("id_insumo[]")
        cants = request.form.getlist("cantidad_insumo[]")
        ingredientes_raw = [{"id_insumo": i, "cantidad": c} for i, c in zip(ids, cants)]

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
            es_preparado,
            ingredientes_raw,
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

    es_preparado = bool(data.get("es_preparado")) if is_json else (request.form.get("es_preparado") == "on")
    if es_preparado:
        stock = 0

    if is_json:
        ingredientes_raw = data.get("ingredientes") or []
    else:
        ids = request.form.getlist("id_insumo[]")
        cants = request.form.getlist("cantidad_insumo[]")
        ingredientes_raw = [{"id_insumo": i, "cantidad": c} for i, c in zip(ids, cants)]

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
            es_preparado,
            ingredientes_raw,
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


@inventory_api_bp.route("/api/insumos", methods=["GET"])
@inventory_api_bp.route("/inventario/api/insumos", methods=["GET"])
@login_required
@roles_required("Admin", "Master")
def api_insumos_list():
    return jsonify({"ok": True, "insumos": get_insumos(int(session["id_tienda"]))})


@inventory_api_bp.route("/api/insumos", methods=["POST"])
@inventory_api_bp.route("/inventario/api/insumos", methods=["POST"])
@login_required
@roles_required("Admin", "Master")
def api_insumos_create():
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    unidad = str(data.get("unidad_medida", "Un")).strip() or "Un"

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
        proveedor_id = _parse_proveedor_id(data.get("id_proveedor"))
        new_id = create_insumo(int(session["id_tienda"]), int(session["id_usuario"]), nombre, unidad, stock, costo, proveedor_id)
        return jsonify({"ok": True, "id": new_id})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo crear el insumo."}), 500


@inventory_api_bp.route("/api/insumos/<int:id_insumo>", methods=["PUT"])
@inventory_api_bp.route("/inventario/api/insumos/<int:id_insumo>", methods=["PUT"])
@login_required
@roles_required("Admin", "Master")
def api_insumos_update(id_insumo: int):
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    unidad = str(data.get("unidad_medida", "Un")).strip() or "Un"

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
        proveedor_id = _parse_proveedor_id(data.get("id_proveedor"))
        update_insumo(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            int(id_insumo),
            nombre,
            unidad,
            stock,
            costo,
            proveedor_id,
        )
        return jsonify({"ok": True})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo actualizar el insumo."}), 500


@inventory_api_bp.route("/api/insumos/<int:id_insumo>", methods=["DELETE"])
@inventory_api_bp.route("/inventario/api/insumos/<int:id_insumo>", methods=["DELETE"])
@login_required
@roles_required("Admin", "Master")
def api_insumos_delete(id_insumo: int):
    try:
        delete_insumo(int(session["id_tienda"]), int(session["id_usuario"]), int(id_insumo))
        return jsonify({"ok": True})
    except InventoryNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except Exception:
        return jsonify({"ok": False, "msg": "No se pudo eliminar el insumo."}), 500
