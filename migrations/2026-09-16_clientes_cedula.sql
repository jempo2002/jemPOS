-- ============================================================
-- Migracion: Cedula de clientes (fiados desde Caja)
-- Fecha: 2026-09-16
-- Motor: MariaDB (soporta IF NOT EXISTS en ALTER)
-- ============================================================

-- No se crea tabla `fiados`: un fiado ya es una fila de `ventas` con
-- estado_venta = 'Fiada/Pendiente' + id_cliente, y los pagos viven en
-- `abonos_fiados`. La deuda del cliente = SUM(total_final - abonos).
-- Solo falta identificar al cliente por cedula.

ALTER TABLE `clientes`
  ADD COLUMN IF NOT EXISTS `cedula` varchar(20) DEFAULT NULL AFTER `nombre`,
  ADD UNIQUE KEY IF NOT EXISTS `uq_clientes_tienda_cedula` (`id_tienda`, `cedula`);
