from __future__ import annotations

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
            "SELECT id_proveedor, nombre_empresa, nombre_contacto, celular, correo, detalles "
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


def create_proveedor(id_tienda: int, id_usuario: int, empresa: str, contacto: str, celular: str, correo: str, detalles: str) -> int:
    empresa = sanitize_text(empresa, "La empresa", max_len=150)
    contacto = sanitize_optional_text(contacto, "El nombre de contacto", max_len=150)
    celular_raw = str(celular or "").strip()
    celular_digits = only_digits(celular_raw)
    if celular_raw and not celular_digits:
        raise ValueError("Celular invalido.")
    if celular_digits and len(celular_digits) > 20:
        raise ValueError("El celular no puede superar 20 digitos.")
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
            "INSERT INTO proveedores (id_tienda, nombre_empresa, nombre_contacto, celular, correo, detalles) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (id_tienda, empresa, contacto or None, celular_digits or None, correo_raw or None, detalles or None),
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


def update_proveedor(id_tienda: int, id_usuario: int, id_proveedor: int, empresa: str, contacto: str, celular: str, correo: str, detalles: str) -> None:
    id_proveedor = parse_int(id_proveedor, "Proveedor", min_value=1)
    empresa = sanitize_text(empresa, "La empresa", max_len=150)
    contacto = sanitize_optional_text(contacto, "El nombre de contacto", max_len=150)
    celular_raw = str(celular or "").strip()
    celular_digits = only_digits(celular_raw)
    if celular_raw and not celular_digits:
        raise ValueError("Celular invalido.")
    if celular_digits and len(celular_digits) > 20:
        raise ValueError("El celular no puede superar 20 digitos.")
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
            "SET nombre_empresa=%s, nombre_contacto=%s, celular=%s, correo=%s, detalles=%s "
            "WHERE id_proveedor=%s AND id_tienda=%s AND estado_activo=1",
            (empresa, contacto or None, celular_digits or None, correo_raw or None, detalles or None, id_proveedor, id_tienda),
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
            "SELECT p.id_producto, p.nombre, c.nombre AS categoria, "
            "p.precio_costo, p.precio_venta, p.stock_actual, p.stock_minimo_alerta, "
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
            "category": r["categoria"] or "",
            "cost": float(r["precio_costo"]),
            "sale": float(r["precio_venta"]),
            "stock": r["stock_actual"],
            "stock_min": r["stock_minimo_alerta"] or 0,
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


def create_producto(
    id_tienda: int,
    id_usuario: int,
    nombre: str,
    categoria: str,
    costo: float,
    venta: float,
    stock: float,
    proveedor_id: int | None,
) -> int:
    nombre = sanitize_text(nombre, "El nombre del producto", max_len=150)
    categoria = sanitize_text(categoria, "La categoria", max_len=120)
    costo = parse_float(costo, "Precio de costo", min_value=0)
    venta = parse_float(venta, "Precio de venta", min_value=0)
    stock = parse_float(stock, "Stock", min_value=0)
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
            "(id_tienda, id_categoria, nombre, precio_costo, precio_venta, stock_actual, id_proveedor) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (id_tienda, id_cat, nombre, costo, venta, stock, proveedor_id),
        )
        new_id = cur.lastrowid

        conn.commit()
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
    venta: float,
    stock: float,
    proveedor_id: int | None,
) -> None:
    id_producto = parse_int(id_producto, "Producto", min_value=1)
    nombre = sanitize_text(nombre, "El nombre del producto", max_len=150)
    categoria = sanitize_text(categoria, "La categoria", max_len=120)
    costo = parse_float(costo, "Precio de costo", min_value=0)
    venta = parse_float(venta, "Precio de venta", min_value=0)
    stock = parse_float(stock, "Stock", min_value=0)
    if proveedor_id is not None:
        proveedor_id = parse_int(proveedor_id, "Proveedor", min_value=1)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_producto FROM productos "
            "WHERE id_producto = %s AND id_tienda = %s LIMIT 1",
            (id_producto, id_tienda),
        )
        if not cur.fetchone():
            raise InventoryNotFoundError("Producto no encontrado.")

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
            "SET nombre=%s, id_categoria=%s, precio_costo=%s, precio_venta=%s, stock_actual=%s, id_proveedor=%s "
            "WHERE id_producto=%s AND id_tienda=%s",
            (nombre, id_cat, costo, venta, stock, proveedor_id, id_producto, id_tienda),
        )

        conn.commit()
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
            "UPDATE productos SET estado_activo = 0 "
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


def add_stock(id_tienda: int, id_usuario: int, id_producto: int, cantidad: int) -> int:
    id_producto = parse_int(id_producto, "Producto", min_value=1)
    cantidad = parse_int(cantidad, "Cantidad", min_value=1, allow_zero=False)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_producto, stock_actual "
            "FROM productos "
            "WHERE id_producto = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
            (id_producto, id_tienda),
        )
        p = cur.fetchone()
        if not p:
            raise InventoryNotFoundError("Producto no encontrado.")

        nuevo_stock = p["stock_actual"] + cantidad
        cur.execute(
            "UPDATE productos SET stock_actual = %s WHERE id_producto = %s AND id_tienda = %s",
            (nuevo_stock, id_producto, id_tienda),
        )
        cur.execute(
            "INSERT INTO movimientos_inventario "
            "(id_tienda, id_producto, id_usuario, tipo_movimiento, cantidad, stock_anterior, stock_posterior) "
            "VALUES (%s, %s, %s, 'Entrada', %s, %s, %s)",
            (id_tienda, id_producto, id_usuario, cantidad, p["stock_actual"], nuevo_stock),
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
            "SELECT id_producto, nombre, precio_venta, stock_actual "
            "FROM productos "
            "WHERE id_tienda=%s AND id_proveedor=%s AND estado_activo=1 "
            "ORDER BY nombre",
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
                "precio_venta": float(r.get("precio_venta") or 0),
                "stock_actual": int(r.get("stock_actual") or 0),
            }
            for r in rows
        ],
    }
