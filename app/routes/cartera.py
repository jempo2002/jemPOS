"""Rutas de Cartera (por cobrar / por pagar) y del modulo B2B.

Reglas de acceso:
  * Ver cuentas por cobrar: cualquier usuario autenticado (ya era asi en fiados).
  * Todo lo de cuentas por pagar y el modulo Mayorista: solo Admin/Master.
    Incluye nomina y el dashboard de compras de cada cliente.
  * El selector de clientes de Venta Mayorista: cualquier usuario (id, nombre
    y NIT; nada de compras ni deuda).
  * Aprobar pagos, anular obligaciones y borrar deudas: solo Admin/Master.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, session

from app import limiter
from app.services.cartera_service import (
    CATEGORIAS_POR_PAGAR,
    ORIGENES_PAGO,
    anular_cuenta_por_pagar,
    crear_cuenta_por_pagar,
    get_cliente_b2b_dashboard,
    get_clientes_b2b,
    get_clientes_mayoristas_min,
    get_cuentas_por_pagar,
    get_proveedores_min,
    get_resumen_cartera,
    pagar_cuenta_por_pagar,
    upsert_cliente_b2b,
)
from app.services.sales_service import (
    SalesConflictError,
    SalesNotFoundError,
    SalesValidationError,
    get_dias_restantes,
)
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import avatar_iniciales

cartera_bp = Blueprint("cartera_bp", __name__, url_prefix="/pos")
cartera_api_bp = Blueprint("cartera_api_bp", __name__, url_prefix="/pos")

# Roles con permiso administrativo sobre la cartera del negocio.
ADMIN_ROLES = ("Admin", "Master")

# Cada carga de la pantalla dispara 3 GET (resumen, cobrar, pagar) y cada accion
# recarga: el default global de 50/hora se agota en ~16 refrescos. Limite propio
# para todo el blueprint de API, igual que hace /api/clientes/buscar.
limiter.limit("90 per minute")(cartera_api_bp)


def _base_context() -> dict:
    nombre = session.get("nombre_completo", "")
    dias = get_dias_restantes(int(session["id_tienda"])) if session.get("id_tienda") else 0
    return {
        "rol": session.get("rol", ""),
        "nombre_completo": nombre,
        "avatar_iniciales": avatar_iniciales(nombre),
        "mostrar_alerta_suscripcion": 0 < dias <= 5,
        "dias_restantes": dias,
    }


def _tienda() -> int:
    return int(session["id_tienda"])


def _usuario() -> int:
    return int(session["id_usuario"])


def _manejar(accion):
    """Ejecuta un servicio y traduce sus excepciones al contrato JSON de la app."""
    try:
        return jsonify({"ok": True, **(accion() or {})})
    except SalesValidationError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except SalesNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except SalesConflictError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 409


# ══════════════════════════════════════════════════════════════
# PAGINAS
# ══════════════════════════════════════════════════════════════

@cartera_bp.get("/clientes-proveer")
@login_required
@roles_required(*ADMIN_ROLES)
def clientes_proveer_page():
    return render_template("pos/clientes_proveer.html", **_base_context())


# ══════════════════════════════════════════════════════════════
# API — RESUMEN
# ══════════════════════════════════════════════════════════════

@cartera_api_bp.get("/api/cartera/resumen")
@login_required
def api_cartera_resumen():
    resumen = get_resumen_cartera(_tienda())
    # El cajero no ve los totales de obligaciones del negocio (nomina, etc).
    if str(session.get("rol") or "").strip() not in ADMIN_ROLES:
        resumen = {"por_cobrar": resumen["por_cobrar"], "deudores": resumen["deudores"]}
    return jsonify({"ok": True, "resumen": resumen})


# ══════════════════════════════════════════════════════════════
# API — CUENTAS POR PAGAR
# ══════════════════════════════════════════════════════════════

@cartera_api_bp.get("/api/cartera/por-pagar")
@login_required
@roles_required(*ADMIN_ROLES)
def api_por_pagar_listar():
    return jsonify(
        {
            "ok": True,
            "cuentas": get_cuentas_por_pagar(_tienda()),
            "categorias": list(CATEGORIAS_POR_PAGAR),
            "proveedores": get_proveedores_min(_tienda()),
            # El <select> de origen se arma con esta lista, la misma que valida el servicio.
            "origenes": [{"valor": k, "etiqueta": v["etiqueta"]} for k, v in ORIGENES_PAGO.items()],
        }
    )


@cartera_api_bp.post("/api/cartera/por-pagar")
@login_required
@roles_required(*ADMIN_ROLES)
def api_por_pagar_crear():
    datos = request.get_json(silent=True) or {}
    return _manejar(
        lambda: {
            "id": crear_cuenta_por_pagar(
                _tienda(),
                _usuario(),
                datos.get("categoria"),
                datos.get("concepto"),
                datos.get("descripcion"),
                datos.get("monto"),
                datos.get("vence"),
                _id_opcional(datos.get("id_proveedor")),
            )
        }
    )


@cartera_api_bp.post("/api/cartera/por-pagar/<int:id_cuenta>/pagar")
@login_required
@roles_required(*ADMIN_ROLES)
def api_por_pagar_pagar(id_cuenta: int):
    datos = request.get_json(silent=True) or {}
    # `origen` lo valida el servicio contra ORIGENES_PAGO: lo que venga del DOM
    # fuera de esa lista es un 400, no un gasto con fuente inventada.
    return _manejar(
        lambda: pagar_cuenta_por_pagar(
            _tienda(), _usuario(), id_cuenta, datos.get("monto"), datos.get("origen")
        )
    )


@cartera_api_bp.delete("/api/cartera/por-pagar/<int:id_cuenta>")
@login_required
@roles_required(*ADMIN_ROLES)
def api_por_pagar_anular(id_cuenta: int):
    return _manejar(lambda: anular_cuenta_por_pagar(_tienda(), _usuario(), id_cuenta))


# ══════════════════════════════════════════════════════════════
# API — CLIENTES B2B
# ══════════════════════════════════════════════════════════════

@cartera_api_bp.get("/api/b2b/clientes")
@login_required
@roles_required(*ADMIN_ROLES)
def api_b2b_clientes_listar():
    return jsonify({"ok": True, "clientes": get_clientes_b2b(_tienda())})


@cartera_api_bp.get("/api/mayorista/clientes")
@login_required
def api_mayorista_clientes():
    return jsonify({"ok": True, "clientes": get_clientes_mayoristas_min(_tienda())})


@cartera_api_bp.get("/api/b2b/clientes/<int:id_cliente>")
@login_required
@roles_required(*ADMIN_ROLES)
def api_b2b_cliente_detalle(id_cliente: int):
    return _manejar(lambda: {"cliente": get_cliente_b2b_dashboard(_tienda(), id_cliente)})


@cartera_api_bp.post("/api/b2b/clientes")
@login_required
@roles_required(*ADMIN_ROLES)
def api_b2b_cliente_crear():
    datos = request.get_json(silent=True) or {}
    return _manejar(
        lambda: {
            "id": upsert_cliente_b2b(
                _tienda(),
                _usuario(),
                datos.get("nombre"),
                datos.get("telefono"),
                datos.get("nit"),
                _id_opcional(datos.get("id_cliente")),
            )
        }
    )


def _id_opcional(valor) -> int | None:
    """None para '', null o 0; deja que el servicio valide el resto."""
    if valor in (None, "", 0, "0"):
        return None
    return valor
