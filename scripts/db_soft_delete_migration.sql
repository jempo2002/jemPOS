-- Soft Delete migration for jemPOS (multi-tenant safe)
-- Strategy: use estado_activo TINYINT(1) DEFAULT 1
-- This script is idempotent: it only adds columns/indexes if missing.

SET @db_name := DATABASE();

-- 1) productos.estado_activo
SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'productos'
    AND COLUMN_NAME = 'estado_activo'
);
SET @sql := IF(
  @exists = 0,
  'ALTER TABLE productos ADD COLUMN estado_activo TINYINT(1) NOT NULL DEFAULT 1 AFTER stock_minimo_alerta',
  'SELECT ''productos.estado_activo already exists'''
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) insumos.estado_activo
SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'insumos'
    AND COLUMN_NAME = 'estado_activo'
);
SET @sql := IF(
  @exists = 0,
  'ALTER TABLE insumos ADD COLUMN estado_activo TINYINT(1) NOT NULL DEFAULT 1 AFTER id_proveedor',
  'SELECT ''insumos.estado_activo already exists'''
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 3) clientes.estado_activo
SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'clientes'
    AND COLUMN_NAME = 'estado_activo'
);
SET @sql := IF(
  @exists = 0,
  'ALTER TABLE clientes ADD COLUMN estado_activo TINYINT(1) NOT NULL DEFAULT 1 AFTER direccion',
  'SELECT ''clientes.estado_activo already exists'''
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4) proveedores.estado_activo
SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'proveedores'
    AND COLUMN_NAME = 'estado_activo'
);
SET @sql := IF(
  @exists = 0,
  'ALTER TABLE proveedores ADD COLUMN estado_activo TINYINT(1) NOT NULL DEFAULT 1 AFTER detalles',
  'SELECT ''proveedores.estado_activo already exists'''
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Recommended indexes for active filters by tenant
SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'productos'
    AND INDEX_NAME = 'idx_productos_tienda_activo'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_productos_tienda_activo ON productos(id_tienda, estado_activo)',
  'SELECT ''idx_productos_tienda_activo already exists'''
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'insumos'
    AND INDEX_NAME = 'idx_insumos_tienda_activo'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_insumos_tienda_activo ON insumos(id_tienda, estado_activo)',
  'SELECT ''idx_insumos_tienda_activo already exists'''
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'clientes'
    AND INDEX_NAME = 'idx_clientes_tienda_activo'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_clientes_tienda_activo ON clientes(id_tienda, estado_activo)',
  'SELECT ''idx_clientes_tienda_activo already exists'''
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db_name
    AND TABLE_NAME = 'proveedores'
    AND INDEX_NAME = 'idx_proveedores_tienda_activo'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_proveedores_tienda_activo ON proveedores(id_tienda, estado_activo)',
  'SELECT ''idx_proveedores_tienda_activo already exists'''
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
