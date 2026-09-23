-- ============================================================
-- Migracion: Proveedores telefono_2 + verificacion FK productos
-- Fecha: 2026-09-16
-- Motor: MariaDB y MySQL 8/9
-- ============================================================
--
-- Sin `IF NOT EXISTS`: es sintaxis exclusiva de MariaDB (MySQL responde 1064).
-- La idempotencia la da scripts/run_migration.py, que trata el error 1060
-- (columna duplicada) como no-op.

-- 1) Telefono secundario (opcional). telefono_1 ya es la columna `celular`.
ALTER TABLE `proveedores`
  ADD COLUMN `telefono_2` varchar(20) DEFAULT NULL AFTER `celular`;

-- 2) FK productos.id_proveedor -> proveedores.id_proveedor
--    Ya existe en el esquema como `fk_productos_proveedores`
--    (ON DELETE SET NULL ON UPDATE CASCADE). Se deja documentada.
--    Ejecutar SOLO si la restriccion no existe:
--
-- ALTER TABLE `productos`
--   ADD CONSTRAINT `fk_productos_proveedores`
--   FOREIGN KEY (`id_proveedor`) REFERENCES `proveedores` (`id_proveedor`)
--   ON DELETE SET NULL ON UPDATE CASCADE;
