from __future__ import annotations

from flask import Blueprint, flash, jsonify, render_template, request, session

from app.services.sales_service import (
    SalesConflictError,
    SalesNotFoundError,
    SalesValidationError,
    abonar_fiado,
    abrir_turno,
    cerrar_turno,
    crear_cliente_fiado,
    crear_gasto,
    get_caja_productos,
    get_categorias_gastos,
    get_detalle_venta,
    get_dias_restantes,
    get_fiados_clientes,
    get_gastos,
    get_turno_estado,
    get_ventas,
    registrar_venta,
    sumar_fiado,
)
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import avatar_iniciales, only_digits as solo_digitos

sales_bp = Blueprint("sales_bp", __name__, url_prefix="/pos")
sales_api_bp = Blueprint("sales_api_bp", __name__, url_prefix="/pos")


def _base_context() -> dict:
    nombre = session.get("nombre_completo", "")
    dias = 0
    mostrar_alerta = False
    if session.get("id_tienda"):
        dias = get_dias_restantes(int(session["id_tienda"]))
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

    if not id_tienda:
        flash("No se encontro la tienda activa en la sesion.", "error")
        return _render_sales("pos/ventas.html", ventas=[], filtro_activo="mes")

    lista_ventas, filtro = get_ventas(int(id_tienda), rol, session.get("id_usuario"), filtro_url)
    return _render_sales("pos/ventas.html", ventas=lista_ventas, filtro_activo=filtro)


@sales_bp.get("/fiados")
@login_required
def fiados():
    return _render_sales(
        "pos/fiados.html",
        fiados_clientes=get_fiados_clientes(int(session["id_tienda"])),
    )


@sales_bp.get("/gastos")
@login_required
@roles_required("Admin", "Master", "Cajero")
def gastos():
    return _render_sales(
        "pos/gastos.html",
        categorias_gastos=get_categorias_gastos(int(session["id_tienda"])),
    )


@sales_api_bp.get("/api/turno/estado")
@login_required
def api_turno_estado():
    turno_abierto = get_turno_estado(int(session["id_tienda"]))
    return jsonify({"ok": True, "turno": turno_abierto})


@sales_api_bp.post("/api/turno/abrir")
@login_required
def api_turno_abrir():
    data = request.get_json(silent=True) or {}
    try:
        monto = float(data.get("monto_inicial", 0))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400

    if monto <= 0:
        return jsonify({"ok": False, "msg": "El monto debe ser mayor a cero."}), 400

    try:
        turno_id = abrir_turno(int(session["id_tienda"]), int(session["id_usuario"]), monto)
        return jsonify({"ok": True, "id_turno": turno_id})
    except SalesConflictError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 409


@sales_api_bp.post("/api/turno/cerrar")
@login_required
def api_turno_cerrar():
    data = request.get_json(silent=True) or {}
    try:
        monto_final = float(data.get("monto_final", -1))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Monto invalido."}), 400

    if monto_final < 0:
        return jsonify({"ok": False, "msg": "El monto no puede ser negativo."}), 400

    try:
        cerrar_turno(int(session["id_tienda"]), int(session["id_usuario"]), monto_final)
        return jsonify({"ok": True})
    except SalesNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404


@sales_api_bp.get("/api/caja/productos")
@login_required
def api_caja_productos():
    q = str(request.args.get("q", "")).strip()
    return jsonify({"ok": True, "productos": get_caja_productos(int(session["id_tienda"]), q)})


@sales_api_bp.post("/api/ventas")
@login_required
def api_ventas_crear():
    datos = request.get_json(silent=True) or {}
    items = datos.get("items", [])

    try:
        subtotal = float(datos.get("subtotal", 0))
        monto_total = float(datos.get("total", 0))
        descuento = float(datos.get("discount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Totales invalidos."}), 400

    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "msg": "No hay productos en la venta."}), 400

    try:
        resultado = registrar_venta(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            items,
            str(datos.get("method", "efectivo")),
            datos.get("id_cliente"),
            subtotal,
            monto_total,
            descuento,
        )
        for alerta in resultado.get("stock_alerts", []):
            flash(alerta, "alerta_stock")
        return jsonify({"ok": True, **resultado})
    except SalesValidationError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except SalesNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except SalesConflictError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 409
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"Error al registrar la venta: {exc}"}), 500


@sales_api_bp.get("/api/ventas/detalle/<int:id_venta>")
@login_required
def api_ventas_detalle(id_venta: int):
    try:
        data = get_detalle_venta(int(session["id_tienda"]), int(id_venta))
        return jsonify({"ok": True, **data})
    except SalesNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404


@sales_api_bp.get("/api/fiados")
@login_required
def api_fiados_listar():
    return jsonify({"ok": True, "clientes": get_fiados_clientes(int(session["id_tienda"]))})


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

    try:
        nuevo_id = crear_cliente_fiado(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            nombre,
            telefono,
            deuda_inicial,
        )
        return jsonify({"ok": True, "id": nuevo_id})
    except SalesConflictError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 409


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

    try:
        sumar_fiado(int(session["id_tienda"]), int(session["id_usuario"]), int(id_cliente), monto, concepto)
        return jsonify({"ok": True})
    except SalesNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except SalesConflictError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 409


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

    try:
        abonar_fiado(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            int(id_cliente),
            monto,
            str(datos.get("metodo", "efectivo")),
        )
        return jsonify({"ok": True})
    except SalesValidationError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except SalesNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404


@sales_api_bp.get("/api/gastos")
@login_required
@roles_required("Admin", "Master", "Cajero")
def api_gastos_listar():
    gastos = get_gastos(int(session["id_tienda"]), int(session["id_usuario"]))
    return jsonify({"ok": True, "gastos": gastos})


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

    try:
        nuevo_id = crear_gasto(
            int(session["id_tienda"]),
            int(session["id_usuario"]),
            concepto,
            descripcion,
            metodo_pago,
            fuente_dinero,
            monto,
        )
        return jsonify({"ok": True, "id": nuevo_id})
    except SalesConflictError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 409
