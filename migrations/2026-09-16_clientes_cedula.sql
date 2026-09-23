-- ============================================================
-- Migracion: Cedula de clientes (fiados desde Caja)
-- Fecha: 2026-09-16
-- Motor: MariaDB y MySQL 8/9
-- ============================================================
--
-- No se crea tabla `fiados`: un fiado ya es una fila de `ventas` con
-- estado_venta = 'Fiada/Pendiente' + id_cliente, y los pagos viven en
-- `abonos_fiados`. La deuda del cliente = SUM(total_final - abonos).
-- Solo falta identificar al cliente por cedula.
--
-- Sin `IF NOT EXISTS` en las clausulas: es sintaxis exclusiva de MariaDB y
-- MySQL la rechaza con error 1064. La idempotencia la da
-- scripts/run_migration.py, que trata "ya existe" (1060 columna duplicada,
-- 1061 clave duplicada) como no-op.
--
-- Y una clausula por sentencia, no un ALTER con varias: un ALTER multiple es
-- atomico, asi que si la columna ya existe pero la clave no, el motor rechaza
-- el bloque entero por 1060, el runner lo salta como "ya aplicado" y la clave
-- nunca se crea. Separadas, cada una se aplica o se salta por su cuenta.

ALTER TABLE `clientes`
  ADD COLUMN `cedula` varchar(20) DEFAULT NULL AFTER `nombre`;

ALTER TABLE `clientes`
  ADD UNIQUE KEY `uq_clientes_tienda_cedula` (`id_tienda`, `cedula`);
