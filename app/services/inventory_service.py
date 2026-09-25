from __future__ import annotations

from mysql.connector import IntegrityError

from app.services.auth_service import is_valid_email
from app.utils.helpers import only_digits
from app.utils.validation import (
    parse_float,
    parse_int,
    sanitize_optional_text,
    sanitize_text,
)
from database import get_db


class InventoryNotFoundError(ValueError):
    pass


TIPOS_ITEM = ("Producto", "Servicio")

# Unidad base del stock y de precio_venta. La lista vive aqui (no en un ENUM de
# la tabla) para sumar unidades sin migracion; el servidor rechaza cualquier otra.
UNIDADES_MEDIDA = (
    "Unidad", "Paquete", "Caja", "Docena", "Rollo", "Bulto",
    "Libra", "Kilogramo", "Gramo", "Metro", "Centimetro", "Litro", "Mililitro", "Galon",
)
# Las que se venden por fraccion (2.5 libras, 0.75 metros). El resto, enteras.
UNIDADES_FRACCIONABLES = frozenset(
    {"Libra", "Kilogramo", "Gramo", "Metro", "Centimetro", "Litro", "Mililitro", "Galon"}
)


def _precio_opcional(value, label: str) -> float | None:
    """'' / None / 0 = sin precio; si no, un numero positivo."""
    if value in (None, ""):
        return None
    precio = parse_float(value, label, min_value=0)
    return precio or None


def _datos_venta(tipo, unidad, mayorista, empaque_nombre, empaque_cantidad, precio_empaque) -> dict:
    """Valida los campos de presentacion comunes a crear y editar.

    El empaque va completo o no va: un "Rollo" sin cantidad no dice cuanto
    stock descuenta, y sin precio no se puede cobrar. Un servicio no tiene
    empaque (no hay stock que partir).
    """
    tipo = str(tipo or "Producto").strip().capitalize()
    if tipo not in TIPOS_ITEM:
        raise ValueError("Tipo invalido.")
    unidad = str(unidad or "Unidad").strip().capitalize()
    if unidad not in UNIDADES_MEDIDA:
        raise ValueError("Unidad de medida invalida.")

    empaque = sanitize_optional_text(empaque_nombre, "El empaque", max_len=30)
    cantidad = _precio_opcional(empaque_cantidad, "Unidades por empaque")
    precio = _precio_opcional(precio_empaque, "Precio del empaque")
    if tipo == "Servicio" or not (empaque or cantidad or precio):
        empaque = cantidad = precio = None
    elif not (empaque and cantidad and precio):
        raise ValueError("Para vender por empaque indica nombre, unidades y precio del empaque.")

    return {
        "tipo": tipo,
        "unidad": unidad,
        "mayorista": _precio_opcional(mayorista, "Precio mayorista"),
        "empaque_nombre": empaque,
        "empaque_cantidad": round(cantidad, 3) if cantidad else None,
        "precio_empaque": precio,
    }


def _num(value) -> float | None:
    return float(value) if value is not None else None


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


def get_categorias_inventario(id_tienda: int) -> list:
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


def get_proveedores(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor, nombre_empresa, nombre_contacto, celular, telefono_2, correo, detalles "
            "FROM proveedores "
            "WHERE id_tienda = %s AND estado_activo = 1 "
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
            "telefono_1": r.get("celular") or "",
            "telefono_2": r.get("telefono_2") or "",
            "correo": r.get("correo") or "",
            "detalles": r.get("detalles") or "",
        }
        for r in rows
    ]


def get_productos_inventario(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT p.id_producto, p.nombre, c.nombre AS categoria, p.precio_costo, p.precio_venta, "
            "p.stock_actual, p.id_proveedor "
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
        }
        for r in rows
    ]


def _telefono_digits(value: str, label: str) -> str | None:
    """Valida un telefono opcional; devuelve solo digitos o None si vacio."""
    raw = str(value or "").strip()
    if not raw:
        return None
    digits = only_digits(raw)
    if not digits:
        raise ValueError(f"{label} invalido.")
    if len(digits) > 20:
        raise ValueError(f"{label} no puede superar 20 digitos.")
    return digits


def create_proveedor(id_tienda: int, id_usuario: int, empresa: str, contacto: str, celular: str, correo: str, detalles: str, telefono_2: str = "") -> int:
    empresa = sanitize_text(empresa, "La empresa", max_len=150)
    contacto = sanitize_optional_text(contacto, "El nombre de contacto", max_len=150)
    celular_digits = _telefono_digits(celular, "El telefono 1")
    telefono_2_digits = _telefono_digits(telefono_2, "El telefono 2")
    correo_raw = str(correo or "").strip().lower()
    if correo_raw:
        if len(correo_raw) > 100:
            raise ValueError("El correo no puede superar 100 caracteres.")
        if not is_valid_email(correo_raw):
            raise ValueError("El correo no es valido.")
    detalles = sanitize_optional_text(detalles, "Los detalles", max_len=1000)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO proveedores (id_tienda, nombre_empresa, nombre_contacto, celular, telefono_2, correo, detalles) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (id_tienda, empresa, contacto or None, celular_digits or None, telefono_2_digits or None, correo_raw or None, detalles or None),
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _registrar_auditoria(id_tienda, id_usuario, "crear_proveedor", f"Proveedor creado id={new_id}, empresa={empresa}")
    return new_id


def update_proveedor(id_tienda: int, id_usuario: int, id_proveedor: int, empresa: str, contacto: str, celular: str, correo: str, detalles: str, telefono_2: str = "") -> None:
    id_proveedor = parse_int(id_proveedor, "Proveedor", min_value=1)
    empresa = sanitize_text(empresa, "La empresa", max_len=150)
    contacto = sanitize_optional_text(contacto, "El nombre de contacto", max_len=150)
    celular_digits = _telefono_digits(celular, "El telefono 1")
    telefono_2_digits = _telefono_digits(telefono_2, "El telefono 2")
    correo_raw = str(correo or "").strip().lower()
    if correo_raw:
        if len(correo_raw) > 100:
            raise ValueError("El correo no puede superar 100 caracteres.")
        if not is_valid_email(correo_raw):
            raise ValueError("El correo no es valido.")
    detalles = sanitize_optional_text(detalles, "Los detalles", max_len=1000)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE proveedores "
            "SET nombre_empresa=%s, nombre_contacto=%s, celular=%s, telefono_2=%s, correo=%s, detalles=%s "
            "WHERE id_proveedor=%s AND id_tienda=%s AND estado_activo=1",
            (empresa, contacto or None, celular_digits or None, telefono_2_digits or None, correo_raw or None, detalles or None, id_proveedor, id_tienda),
        )
        conn.commit()
        updated = cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not updated:
        raise InventoryNotFoundError("Proveedor no encontrado para esta tienda.")

    _registrar_auditoria(id_tienda, id_usuario, "editar_proveedor", f"Proveedor editado id={id_proveedor}, empresa={empresa}")


def delete_proveedor(id_tienda: int, id_usuario: int, id_proveedor: int, soft_products: bool = False) -> None:
    id_proveedor = parse_int(id_proveedor, "Proveedor", min_value=1)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor FROM proveedores "
            "WHERE id_proveedor=%s AND id_tienda=%s AND estado_activo=1 LIMIT 1",
            (id_proveedor, id_tienda),
        )
        if not cur.fetchone():
            raise InventoryNotFoundError("Proveedor no encontrado para esta tienda.")

        if soft_products:
            cur.execute(
                "UPDATE productos SET id_proveedor = NULL "
                "WHERE id_proveedor=%s AND id_tienda=%s AND estado_activo=1",
                (id_proveedor, id_tienda),
            )

        cur.execute(
            "UPDATE proveedores SET estado_activo = 0 "
            "WHERE id_proveedor=%s AND id_tienda=%s AND estado_activo=1",
            (id_proveedor, id_tienda),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _registrar_auditoria(id_tienda, id_usuario, "eliminar_proveedor", f"Proveedor desactivado id={id_proveedor}")


def list_inventario_api(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT p.id_producto, p.nombre, p.tipo, p.unidad_medida, c.nombre AS categoria, "
            "p.codigo_barras, p.precio_costo, p.precio_venta, p.precio_mayorista, "
            "p.empaque_nombre, p.empaque_cantidad, p.precio_empaque, "
            "p.stock_actual, p.stock_minimo_alerta, "
            "p.id_proveedor, pr.nombre_empresa AS proveedor_nombre "
            "FROM productos p "
            "LEFT JOIN categorias c ON c.id_categoria = p.id_categoria "
            "LEFT JOIN proveedores pr ON pr.id_proveedor = p.id_proveedor "
            "WHERE p.id_tienda = %s AND p.estado_activo = 1 "
            "ORDER BY p.nombre",
            (id_tienda,),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        {
            "id": r["id_producto"],
            "name": r["nombre"],
            "tipo": r["tipo"],
            "unidad": r["unidad_medida"],
            "category": r["categoria"] or "",
            "barcode": r.get("codigo_barras") or "",
            "cost": float(r["precio_costo"]),
            "sale": float(r["precio_venta"]),
            "mayorista": _num(r["precio_mayorista"]),
            "empaque_nombre": r["empaque_nombre"] or "",
            "empaque_cantidad": _num(r["empaque_cantidad"]),
            "precio_empaque": _num(r["precio_empaque"]),
            # decimal(12,3): Decimal viajaria como texto ("9.000") al JSON.
            "stock": float(r["stock_actual"] or 0),
            "stock_min": float(r["stock_minimo_alerta"] or 0),
            "proveedor_id": r.get("id_proveedor"),
            "proveedor_nombre": r.get("proveedor_nombre") or "",
        }
        for r in rows
    ]


def list_categorias_api(id_tienda: int) -> list[str]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT nombre FROM categorias "
            "WHERE id_tienda = %s AND estado_activo = 1 ORDER BY nombre",
            (id_tienda,),
        )
        cats = cur.fetchall() or []
    finally:
        conn.close()

    return [r["nombre"] for r in cats]


_MSG_CODIGO_DUPLICADO = "Ya existe un producto con ese codigo de barras."


def _codigo_barras(value) -> str | None:
    """Codigo de barras opcional: sin espacios, max 80 (columna varchar(80))."""
    codigo = "".join(str(value or "").split())
    if len(codigo) > 80:
        raise ValueError("El codigo de barras no puede superar 80 caracteres.")
    return codigo or None


def _stock(stock, stock_min, datos: dict) -> tuple[float | None, float | None]:
    """Stock en la unidad base. Un servicio no lleva stock (NULL: nunca alerta)."""
    if datos["tipo"] == "Servicio":
        return None, None
    stock = round(parse_float(stock, "Stock", min_value=0), 3)
    stock_min = round(parse_float(stock_min, "Alerta de stock", min_value=0), 3)
    if datos["unidad"] not in UNIDADES_FRACCIONABLES and stock != int(stock):
        raise ValueError(f"El stock en {datos['unidad']} debe ser un numero entero.")
    return stock, stock_min


def create_producto(
    id_tienda: int,
    id_usuario: int,
    nombre: str,
    categoria: str,
    costo: float,
    venta: float,
    stock: float,
    proveedor_id: int | None,
    stock_min: float = 0,
    codigo_barras: str | None = None,
    *,
    tipo: str = "Producto",
    unidad: str = "Unidad",
    mayorista: float | None = None,
    empaque_nombre: str | None = None,
    empaque_cantidad: float | None = None,
    precio_empaque: float | None = None,
) -> int:
    nombre = sanitize_text(nombre, "El nombre del producto", max_len=150)
    categoria = sanitize_text(categoria, "La categoria", max_len=120)
    costo = parse_float(costo, "Precio de costo", min_value=0)
    venta = parse_float(venta, "Precio de venta", min_value=0)
    datos = _datos_venta(tipo, unidad, mayorista, empaque_nombre, empaque_cantidad, precio_empaque)
    stock, stock_min = _stock(stock, stock_min, datos)
    codigo_barras = _codigo_barras(codigo_barras)
    if proveedor_id is not None:
        proveedor_id = parse_int(proveedor_id, "Proveedor", min_value=1)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores "
                "WHERE id_proveedor=%s AND id_tienda=%s AND estado_activo=1 LIMIT 1",
                (proveedor_id, id_tienda),
            )
            if not cur.fetchone():
                raise InventoryNotFoundError("Proveedor no encontrado.")

        id_cat = _obtener_o_crear_categoria(cur, id_tienda, categoria)

        cur.execute(
            "INSERT INTO productos "
            "(id_tienda, id_categoria, nombre, tipo, unidad_medida, codigo_barras, precio_costo, precio_venta, "
            " precio_mayorista, empaque_nombre, empaque_cantidad, precio_empaque, "
            " stock_actual, stock_minimo_alerta, id_proveedor) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                id_tienda, id_cat, nombre, datos["tipo"], datos["unidad"], codigo_barras, costo, venta,
                datos["mayorista"], datos["empaque_nombre"], datos["empaque_cantidad"], datos["precio_empaque"],
                stock, stock_min, proveedor_id,
            ),
        )
        new_id = cur.lastrowid

        conn.commit()
    except IntegrityError as exc:
        conn.rollback()
        if "codigo_barras" in str(exc):
            raise ValueError(_MSG_CODIGO_DUPLICADO) from exc
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _registrar_auditoria(id_tienda, id_usuario, "crear_producto", f"Producto creado id={new_id}, nombre={nombre}")
    return new_id


def update_producto(
    id_tienda: int,
    id_usuario: int,
    id_producto: int,
    nombre: str,
    categoria: str,
    costo: float,
    venta: float | None,
    stock: float,
    proveedor_id: int | None,
    stock_min: float = 0,
    codigo_barras: str | None = None,
    precio_bloqueado: bool = False,
    *,
    tipo: str = "Producto",
    unidad: str = "Unidad",
    mayorista: float | None = None,
    empaque_nombre: str | None = None,
    empaque_cantidad: float | None = None,
    precio_empaque: float | None = None,
) -> None:
    """venta=None conserva el precio actual. Con precio_bloqueado (Cajero)
    cualquier precio (venta, mayorista, empaque) distinto al guardado se
    rechaza con PermissionError: su formulario los manda sin tocar."""
    id_producto = parse_int(id_producto, "Producto", min_value=1)
    nombre = sanitize_text(nombre, "El nombre del producto", max_len=150)
    categoria = sanitize_text(categoria, "La categoria", max_len=120)
    costo = parse_float(costo, "Precio de costo", min_value=0)
    if venta is not None:
        venta = parse_float(venta, "Precio de venta", min_value=0)
    datos = _datos_venta(tipo, unidad, mayorista, empaque_nombre, empaque_cantidad, precio_empaque)
    stock, stock_min = _stock(stock, stock_min, datos)
    codigo_barras = _codigo_barras(codigo_barras)
    if proveedor_id is not None:
        proveedor_id = parse_int(proveedor_id, "Proveedor", min_value=1)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT precio_venta, precio_mayorista, precio_empaque FROM productos "
            "WHERE id_producto = %s AND id_tienda = %s LIMIT 1",
            (id_producto, id_tienda),
        )
        actual = cur.fetchone()
        if not actual:
            raise InventoryNotFoundError("Producto no encontrado.")
        precio_actual = float(actual["precio_venta"] or 0)
        if venta is None:
            venta = precio_actual
        if precio_bloqueado and any(
            abs((nuevo or 0) - float(guardado or 0)) >= 0.005
            for nuevo, guardado in (
                (venta, precio_actual),
                (datos["mayorista"], actual["precio_mayorista"]),
                (datos["precio_empaque"], actual["precio_empaque"]),
            )
        ):
            raise PermissionError("Solo un administrador puede cambiar el precio de venta.")

        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores "
                "WHERE id_proveedor=%s AND id_tienda=%s AND estado_activo=1 LIMIT 1",
                (proveedor_id, id_tienda),
            )
            if not cur.fetchone():
                raise InventoryNotFoundError("Proveedor no encontrado.")

        id_cat = _obtener_o_crear_categoria(cur, id_tienda, categoria)

        cur.execute(
            "UPDATE productos "
            "SET nombre=%s, tipo=%s, unidad_medida=%s, id_categoria=%s, codigo_barras=%s, precio_costo=%s, "
            "    precio_venta=%s, precio_mayorista=%s, empaque_nombre=%s, empaque_cantidad=%s, precio_empaque=%s, "
            "    stock_actual=%s, stock_minimo_alerta=%s, id_proveedor=%s "
            "WHERE id_producto=%s AND id_tienda=%s",
            (
                nombre, datos["tipo"], datos["unidad"], id_cat, codigo_barras, costo,
                venta, datos["mayorista"], datos["empaque_nombre"], datos["empaque_cantidad"], datos["precio_empaque"],
                stock, stock_min, proveedor_id, id_producto, id_tienda,
            ),
        )

        conn.commit()
    except IntegrityError as exc:
        conn.rollback()
        if "codigo_barras" in str(exc):
            raise ValueError(_MSG_CODIGO_DUPLICADO) from exc
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _registrar_auditoria(id_tienda, id_usuario, "editar_producto", f"Producto editado id={id_producto}, nombre={nombre}")


def delete_producto(id_tienda: int, id_usuario: int, id_producto: int) -> None:
    id_producto = parse_int(id_producto, "Producto", min_value=1)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE productos SET estado_activo = 0, codigo_barras = NULL "
            "WHERE id_producto = %s AND id_tienda = %s",
            (id_producto, id_tienda),
        )
        if cur.rowcount == 0:
            raise InventoryNotFoundError("Producto no encontrado.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _registrar_auditoria(id_tienda, id_usuario, "eliminar_producto", f"Producto desactivado id={id_producto}")


def add_stock(id_tienda: int, id_usuario: int, id_producto: int, cantidad: float) -> float:
    id_producto = parse_int(id_producto, "Producto", min_value=1)
    cantidad = round(parse_float(cantidad, "Cantidad", min_value=0, allow_zero=False), 3)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_producto, tipo, unidad_medida, stock_actual "
            "FROM productos "
            "WHERE id_producto = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1 FOR UPDATE",
            (id_producto, id_tienda),
        )
        p = cur.fetchone()
        if not p:
            raise InventoryNotFoundError("Producto no encontrado.")
        if p["tipo"] == "Servicio":
            raise ValueError("Un servicio no lleva stock.")
        if p["unidad_medida"] not in UNIDADES_FRACCIONABLES and cantidad != int(cantidad):
            raise ValueError(f"La cantidad en {p['unidad_medida']} debe ser un numero entero.")

        anterior = float(p["stock_actual"] or 0)
        nuevo_stock = round(anterior + cantidad, 3)
        cur.execute(
            "UPDATE productos SET stock_actual = %s WHERE id_producto = %s AND id_tienda = %s",
            (nuevo_stock, id_producto, id_tienda),
        )
        # `motivo` es NOT NULL sin default: omitirlo solo pasaba con sql_mode no estricto.
        cur.execute(
            "INSERT INTO movimientos_inventario "
            "(id_tienda, id_producto, id_usuario, tipo_movimiento, motivo, cantidad, stock_anterior, stock_posterior) "
            "VALUES (%s, %s, %s, 'Entrada', 'Entrada manual de stock', %s, %s, %s)",
            (id_tienda, id_producto, id_usuario, cantidad, anterior, nuevo_stock),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return nuevo_stock


def get_proveedor_productos(id_tienda: int, id_proveedor: int) -> dict:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_proveedor, nombre_empresa "
            "FROM proveedores "
            "WHERE id_proveedor=%s AND id_tienda=%s AND estado_activo=1 LIMIT 1",
            (id_proveedor, id_tienda),
        )
        prov = cur.fetchone()
        if not prov:
            raise InventoryNotFoundError("Proveedor no encontrado.")

        cur.execute(
            "SELECT p.id_producto, p.nombre, c.nombre AS categoria, p.precio_venta, p.stock_actual "
            "FROM productos p "
            "LEFT JOIN categorias c ON c.id_categoria = p.id_categoria "
            "WHERE p.id_tienda=%s AND p.id_proveedor=%s AND p.estado_activo=1 "
            "ORDER BY p.nombre",
            (id_tienda, id_proveedor),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    return {
        "proveedor": {
            "id": prov["id_proveedor"],
            "empresa": prov.get("nombre_empresa") or "",
        },
        "productos": [
            {
                "id": r["id_producto"],
                "nombre": r["nombre"],
                "categoria": r.get("categoria") or "Sin categoria",
                "precio_venta": float(r.get("precio_venta") or 0),
                "stock_actual": float(r.get("stock_actual") or 0),
            }
            for r in rows
        ],
    }
