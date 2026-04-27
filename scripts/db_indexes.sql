-- SQL index additions for jemPOS
-- Naming convention: idx_<table>_<column>

-- ventas: estado_venta, fecha_creacion, id_tienda
CREATE INDEX idx_ventas_estado_venta ON ventas(estado_venta);
CREATE INDEX idx_ventas_fecha_creacion ON ventas(fecha_creacion);
CREATE INDEX idx_ventas_id_tienda ON ventas(id_tienda);

-- productos: codigo_barras, estado_activo, id_categoria
CREATE INDEX idx_productos_codigo_barras ON productos(codigo_barras);
CREATE INDEX idx_productos_estado_activo ON productos(estado_activo);
CREATE INDEX idx_productos_id_categoria ON productos(id_categoria);

-- turnos_caja: estado_turno, fecha_apertura
CREATE INDEX idx_turnos_caja_estado_turno ON turnos_caja(estado_turno);
CREATE INDEX idx_turnos_caja_fecha_apertura ON turnos_caja(fecha_apertura);

-- movimientos_inventario: fecha_creacion, id_producto
CREATE INDEX idx_movimientos_inventario_fecha_creacion ON movimientos_inventario(fecha_creacion);
CREATE INDEX idx_movimientos_inventario_id_producto ON movimientos_inventario(id_producto);

-- Notes:
-- 1) Run these statements during low-traffic windows.
-- 2) If tables are very large, consider creating indexes CONCURRENTLY
--    (MySQL does not support CONCURRENTLY; use online DDL with pt-online-schema-change
--    or ALTER TABLE ... ALGORITHM=INPLACE where applicable).
