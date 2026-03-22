from __future__ import annotations

from dataclasses import dataclass

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


def get_proveedores_page(id_tienda: int) -> list:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM proveedores WHERE id_tienda = %s ORDER BY nombre_empresa",
            (id_tienda,),
        )
        return cur.fetchall() or []
    finally:
        conn.close()


def get_insumos(id_tienda: int) -> list:
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


def get_productos_inventario(id_tienda: int) -> list:
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


def create_insumo(id_tienda: int, id_usuario: int, nombre: str, unidad: str, stock: float, costo: float, proveedor_id: int | None) -> int:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, id_tienda),
            )
            if not cur.fetchone():
                raise InventoryNotFoundError("Proveedor no encontrado para esta tienda.")

        cur.execute(
            "INSERT INTO insumos "
            "(id_tienda, nombre, stock_actual, unidad_medida, costo_unitario, id_proveedor) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (id_tienda, nombre, stock, unidad, costo, proveedor_id),
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _registrar_auditoria(id_tienda, id_usuario, "crear_insumo", f"Insumo creado id={new_id}, nombre={nombre}")
    return new_id


def update_insumo(id_tienda: int, id_usuario: int, id_insumo: int, nombre: str, unidad: str, stock: float, costo: float, proveedor_id: int | None) -> None:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, id_tienda),
            )
            if not cur.fetchone():
                raise InventoryNotFoundError("Proveedor no encontrado para esta tienda.")

        cur.execute(
            "UPDATE insumos "
            "SET nombre=%s, stock_actual=%s, unidad_medida=%s, costo_unitario=%s, id_proveedor=%s "
            "WHERE id_insumo=%s AND id_tienda=%s",
            (nombre, stock, unidad, costo, proveedor_id, id_insumo, id_tienda),
        )
        conn.commit()
        updated = cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not updated:
        raise InventoryNotFoundError("Insumo no encontrado para esta tienda.")

    _registrar_auditoria(id_tienda, id_usuario, "editar_insumo", f"Insumo editado id={id_insumo}, nombre={nombre}")


def delete_insumo(id_tienda: int, id_usuario: int, id_insumo: int) -> None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM insumos WHERE id_insumo=%s AND id_tienda=%s",
            (id_insumo, id_tienda),
        )
        conn.commit()
        deleted = cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not deleted:
        raise InventoryNotFoundError("Insumo no encontrado para esta tienda.")

    _registrar_auditoria(id_tienda, id_usuario, "eliminar_insumo", f"Insumo eliminado id={id_insumo}")


def create_proveedor(id_tienda: int, id_usuario: int, empresa: str, contacto: str, celular: str, correo: str, detalles: str) -> int:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO proveedores (id_tienda, nombre_empresa, nombre_contacto, celular, correo, detalles) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (id_tienda, empresa, contacto or None, celular or None, correo or None, detalles or None),
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
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE proveedores "
            "SET nombre_empresa=%s, nombre_contacto=%s, celular=%s, correo=%s, detalles=%s "
            "WHERE id_proveedor=%s AND id_tienda=%s",
            (empresa, contacto or None, celular or None, correo or None, detalles or None, id_proveedor, id_tienda),
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
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        if soft_products:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (id_proveedor, id_tienda),
            )
            if not cur.fetchone():
                raise InventoryNotFoundError("Proveedor no encontrado.")

            cur.execute(
                "UPDATE productos SET id_proveedor = NULL WHERE id_proveedor=%s AND id_tienda=%s",
                (id_proveedor, id_tienda),
            )
            cur.execute(
                "DELETE FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s",
                (id_proveedor, id_tienda),
            )
            conn.commit()
        else:
            cur2 = conn.cursor()
            cur2.execute(
                "DELETE FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s",
                (id_proveedor, id_tienda),
            )
            conn.commit()
            if cur2.rowcount == 0:
                raise InventoryNotFoundError("Proveedor no encontrado para esta tienda.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _registrar_auditoria(id_tienda, id_usuario, "eliminar_proveedor", f"Proveedor eliminado id={id_proveedor}")


def list_inventario_api(id_tienda: int) -> list:
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
            "es_preparado": bool(r.get("es_preparado") or 0),
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
    es_preparado: bool,
    ingredientes_raw: list,
    proveedor_id: int | None,
) -> int:
    ingredientes = _parse_ingredientes(ingredientes_raw)
    if es_preparado and not ingredientes:
        raise ValueError("Agrega al menos un ingrediente para la receta.")

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)

        if proveedor_id is not None:
            cur.execute(
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, id_tienda),
            )
            if not cur.fetchone():
                raise InventoryNotFoundError("Proveedor no encontrado.")

        id_cat = _obtener_o_crear_categoria(cur, id_tienda, categoria)

        cur.execute(
            "INSERT INTO productos "
            "(id_tienda, id_categoria, nombre, precio_costo, precio_venta, stock_actual, id_proveedor, es_preparado) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (id_tienda, id_cat, nombre, costo, venta, stock, proveedor_id, 1 if es_preparado else 0),
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
    es_preparado: bool,
    ingredientes_raw: list,
    proveedor_id: int | None,
) -> None:
    ingredientes = _parse_ingredientes(ingredientes_raw)
    if es_preparado and not ingredientes:
        raise ValueError("Agrega al menos un ingrediente para la receta.")

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
                "SELECT id_proveedor FROM proveedores WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
                (proveedor_id, id_tienda),
            )
            if not cur.fetchone():
                raise InventoryNotFoundError("Proveedor no encontrado.")

        id_cat = _obtener_o_crear_categoria(cur, id_tienda, categoria)

        cur.execute(
            "UPDATE productos "
            "SET nombre=%s, id_categoria=%s, precio_costo=%s, precio_venta=%s, stock_actual=%s, id_proveedor=%s, es_preparado=%s "
            "WHERE id_producto=%s AND id_tienda=%s",
            (nombre, id_cat, costo, venta, stock, proveedor_id, 1 if es_preparado else 0, id_producto, id_tienda),
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
        raise
    finally:
        conn.close()

    _registrar_auditoria(id_tienda, id_usuario, "editar_producto", f"Producto editado id={id_producto}, nombre={nombre}")


def delete_producto(id_tienda: int, id_usuario: int, id_producto: int) -> None:
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
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_producto, stock_actual, COALESCE(es_preparado, 0) AS es_preparado "
            "FROM productos "
            "WHERE id_producto = %s AND id_tienda = %s AND estado_activo = 1 LIMIT 1",
            (id_producto, id_tienda),
        )
        p = cur.fetchone()
        if not p:
            raise InventoryNotFoundError("Producto no encontrado.")
        if bool(p.get("es_preparado") or 0):
            raise ValueError("El stock de platos preparados se calcula desde sus insumos.")

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
            "WHERE id_proveedor=%s AND id_tienda=%s LIMIT 1",
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
