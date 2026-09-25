-- ============================================================
-- Migracion: precio mayorista fijo, servicios y unidades de medida
-- Fecha: 2026-09-25
-- Motor: MariaDB y MySQL 8/9
-- ============================================================
--
-- Solo agrega columnas y ensancha tipos: ninguna sentencia borra datos.
--
--  * productos.tipo: 'Servicio' es un item vendible sin stock (instalacion,
--    domicilio). Todo lo existente queda como 'Producto'.
--  * productos.precio_mayorista: precio fijo que se cobra en Venta Mayorista.
--    Reemplaza el descuento porcentual de listas_precios, que deja de usarse
--    (la tabla y clientes.id_lista_precios se conservan intactos).
--  * productos.unidad_medida + empaque_*: el stock y precio_venta van en la
--    unidad base (Metro, Libra, Unidad...). El empaque es una presentacion
--    opcional con su propio precio: "Rollo" de 100 Metro a $90.000 mientras el
--    metro suelto vale $1.000. Vender 1 rollo descuenta 100 del stock.
--  * stock_actual / stock_minimo_alerta pasan de int a decimal(12,3) para
--    vender fracciones (2.5 libras). int -> decimal no pierde valores: 9 queda
--    9.000. movimientos_inventario se ensancha igual para no truncar.
--  * detalle_ventas.unidad_venta: la presentacion vendida ("Metro", "Rollo"),
--    para que la factura diga que se vendio y no solo cuanto.
--
-- Una clausula por sentencia y sin `IF NOT EXISTS` (ver 2026-09-22): la
-- idempotencia la pone scripts/run_migration.py (1060 = columna ya existe).
-- Los MODIFY se pueden repetir sin efecto.

ALTER TABLE `productos`
  ADD COLUMN `tipo` enum('Producto','Servicio') NOT NULL DEFAULT 'Producto' AFTER `nombre`;

ALTER TABLE `productos`
  ADD COLUMN `unidad_medida` varchar(20) NOT NULL DEFAULT 'Unidad' AFTER `tipo`;

ALTER TABLE `productos`
  ADD COLUMN `precio_mayorista` decimal(12,2) DEFAULT NULL AFTER `precio_venta`;

ALTER TABLE `productos`
  ADD COLUMN `empaque_nombre` varchar(30) DEFAULT NULL AFTER `precio_mayorista`;

ALTER TABLE `productos`
  ADD COLUMN `empaque_cantidad` decimal(12,3) DEFAULT NULL AFTER `empaque_nombre`;

ALTER TABLE `productos`
  ADD COLUMN `precio_empaque` decimal(12,2) DEFAULT NULL AFTER `empaque_cantidad`;

ALTER TABLE `productos`
  MODIFY `stock_actual` decimal(12,3) DEFAULT NULL;

ALTER TABLE `productos`
  MODIFY `stock_minimo_alerta` decimal(12,3) DEFAULT NULL;

ALTER TABLE `movimientos_inventario`
  MODIFY `stock_anterior` decimal(12,3) DEFAULT NULL;

ALTER TABLE `movimientos_inventario`
  MODIFY `stock_posterior` decimal(12,3) DEFAULT NULL;

ALTER TABLE `detalle_ventas`
  ADD COLUMN `unidad_venta` varchar(30) DEFAULT NULL AFTER `cantidad`;
