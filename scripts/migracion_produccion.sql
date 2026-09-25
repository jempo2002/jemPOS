-- ============================================================
-- Migracion de produccion: iguala Railway (MySQL 9) con el codigo actual
-- Fecha: 2026-09-25
-- Motor: MySQL 8/9 y MariaDB
-- ============================================================
--
-- Junta lo que el codigo ya usa y que DEPLOY.md no registra como aplicado en
-- Railway (alli constan hasta 2026-09-22 + db_indexes.sql):
--
--   2026-09-23_abonos_id_turno          abonos_fiados.id_turno (+ clave, FK)
--   2026-09-23_gastos_fuente_base       gastos_caja.fuente_dinero + 'Base'
--   2026-09-23_liberar_unicos_eliminados usuarios.correo/cc, tiendas.nit mas anchos
--   2026-09-23_tiendas_estado_eliminado tiendas.estado + 'Eliminado'
--   2026-09-25_mayorista_servicios_unidades productos.tipo/unidad_medida/
--                                       precio_mayorista/empaque_*,
--                                       detalle_ventas.unidad_venta, stock decimal
--   2026-09-25_master_movimientos       tabla master_movimientos
--
-- El Panel de Control cae sin `detalle_ventas.unidad_venta` y
-- `productos.empaque_nombre/empaque_cantidad` (utilidad bruta y tarjetas del
-- personal) y sin `abonos_fiados.id_turno` (cuadre de cada turno).
--
-- Nada se borra: solo CREATE TABLE, ADD COLUMN/KEY/CONSTRAINT, MODIFY que
-- ensancha tipos o agrega valores a un enum, y un UPDATE que rellena NULLs.
--
-- Se puede ejecutar varias veces y en cualquier cliente (consola de Railway,
-- DBeaver, `mysql`, scripts/run_migration.py): MySQL no tiene
-- `ADD COLUMN IF NOT EXISTS`, asi que cada ADD consulta information_schema y
-- ejecuta `DO 0` si ya existe. Los MODIFY se repiten sin efecto.
--
-- ponytail: el guardia es texto repetido a proposito; un procedimiento
-- almacenado necesitaria DELIMITER, que la consola web de Railway no entiende.

-- ---------- abonos_fiados.id_turno ----------

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'abonos_fiados' AND COLUMN_NAME = 'id_turno'), 'DO 0', 'ALTER TABLE `abonos_fiados` ADD COLUMN `id_turno` bigint(20) UNSIGNED DEFAULT NULL AFTER `id_venta`');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'abonos_fiados' AND INDEX_NAME = 'idx_abonos_turno'), 'DO 0', 'ALTER TABLE `abonos_fiados` ADD KEY `idx_abonos_turno` (`id_turno`)');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'abonos_fiados' AND CONSTRAINT_NAME = 'fk_abonos_turnos'), 'DO 0', 'ALTER TABLE `abonos_fiados` ADD CONSTRAINT `fk_abonos_turnos` FOREIGN KEY (`id_turno`) REFERENCES `turnos_caja` (`id_turno`) ON DELETE SET NULL ON UPDATE CASCADE');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

-- Asigna a cada abono viejo el turno que estaba abierto cuando se hizo. Solo
-- toca filas con id_turno NULL: repetirlo no cambia lo ya asignado.
UPDATE `abonos_fiados` a
SET a.id_turno = (
  SELECT t.id_turno
  FROM turnos_caja t
  WHERE t.id_tienda = a.id_tienda
    AND a.fecha_creacion >= t.fecha_apertura
    AND (t.fecha_cierre IS NULL OR a.fecha_creacion <= t.fecha_cierre)
  ORDER BY t.fecha_apertura DESC
  LIMIT 1
)
WHERE a.id_turno IS NULL;

-- ---------- gastos_caja / tiendas / usuarios: enums y anchos ----------

ALTER TABLE `gastos_caja`
  MODIFY COLUMN `fuente_dinero` enum('Caja Menor','Caja Fuerte','Bancos','Base') DEFAULT 'Bancos';

ALTER TABLE `tiendas`
  MODIFY `estado` enum('Activo','Suspendido','Eliminado') NOT NULL DEFAULT 'Activo';

-- El prefijo 'deleted_<timestamp>_' al eliminar necesita espacio extra.
ALTER TABLE `usuarios`
  MODIFY `correo` varchar(191) NOT NULL;

ALTER TABLE `usuarios`
  MODIFY `cc` varchar(50) DEFAULT NULL;

ALTER TABLE `tiendas`
  MODIFY `nit` varchar(50) DEFAULT NULL;

-- ---------- productos: tipo, unidad, mayorista y empaque ----------

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos' AND COLUMN_NAME = 'tipo'), 'DO 0', 'ALTER TABLE `productos` ADD COLUMN `tipo` enum(''Producto'',''Servicio'') NOT NULL DEFAULT ''Producto'' AFTER `nombre`');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos' AND COLUMN_NAME = 'unidad_medida'), 'DO 0', 'ALTER TABLE `productos` ADD COLUMN `unidad_medida` varchar(20) NOT NULL DEFAULT ''Unidad'' AFTER `tipo`');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos' AND COLUMN_NAME = 'precio_mayorista'), 'DO 0', 'ALTER TABLE `productos` ADD COLUMN `precio_mayorista` decimal(12,2) DEFAULT NULL AFTER `precio_venta`');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos' AND COLUMN_NAME = 'empaque_nombre'), 'DO 0', 'ALTER TABLE `productos` ADD COLUMN `empaque_nombre` varchar(30) DEFAULT NULL AFTER `precio_mayorista`');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos' AND COLUMN_NAME = 'empaque_cantidad'), 'DO 0', 'ALTER TABLE `productos` ADD COLUMN `empaque_cantidad` decimal(12,3) DEFAULT NULL AFTER `empaque_nombre`');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos' AND COLUMN_NAME = 'precio_empaque'), 'DO 0', 'ALTER TABLE `productos` ADD COLUMN `precio_empaque` decimal(12,2) DEFAULT NULL AFTER `empaque_cantidad`');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

-- int -> decimal(12,3) para vender fracciones; 9 queda 9.000, no se pierde nada.
ALTER TABLE `productos`
  MODIFY `stock_actual` decimal(12,3) DEFAULT NULL;

ALTER TABLE `productos`
  MODIFY `stock_minimo_alerta` decimal(12,3) DEFAULT NULL;

ALTER TABLE `movimientos_inventario`
  MODIFY `stock_anterior` decimal(12,3) DEFAULT NULL;

ALTER TABLE `movimientos_inventario`
  MODIFY `stock_posterior` decimal(12,3) DEFAULT NULL;

-- ---------- detalle_ventas.unidad_venta ----------

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'detalle_ventas' AND COLUMN_NAME = 'unidad_venta'), 'DO 0', 'ALTER TABLE `detalle_ventas` ADD COLUMN `unidad_venta` varchar(30) DEFAULT NULL AFTER `cantidad`');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

-- ---------- master_movimientos (finanzas del Panel Master) ----------

CREATE TABLE IF NOT EXISTS `master_movimientos` (
  `id_movimiento` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `tipo` enum('Ingreso','Gasto') NOT NULL,
  `concepto` varchar(150) NOT NULL,
  `monto` decimal(12,2) NOT NULL,
  `fecha` date NOT NULL,
  `id_usuario` bigint(20) UNSIGNED NOT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_movimiento`),
  KEY `idx_master_mov_fecha` (`fecha`),
  CONSTRAINT `fk_master_mov_usuario` FOREIGN KEY (`id_usuario`) REFERENCES `usuarios` (`id_usuario`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
