-- ============================================================================
-- jemPOS MVP Deep Clean - SQL Cleanup Script
-- ============================================================================
-- 
-- Objetivo: Eliminar tablas y columnas de funcionalidad Restaurante/Insumos/Fotos
-- Riesgo: CRÍTICO - DESTRUCCIÓN DE DATOS. RESPALDAR ANTES DE EJECUTAR.
-- 
-- Ejecución:
--   mysql -u user -p jempos < scripts/db_mvp_cleanup.sql
--
-- O en phpMyAdmin: Copiar cada sentencia y ejecutar por separado.
-- ============================================================================

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";

-- ============================================================================
-- PASO 1: Eliminar Tabla de Recetas (depende de insumos)
-- ============================================================================
-- 
-- La tabla recetas_productos vincula productos con insumos.
-- Se elimina PRIMERO porque tiene FK a insumos.
-- 

DROP TABLE IF EXISTS `recetas_productos`;

-- ============================================================================
-- PASO 2: Eliminar Tabla de Insumos
-- ============================================================================
-- 
-- Tabla de inventario de despensa (ingredientes, materias primas).
-- Ya no se usará en POS retail.
-- 

DROP TABLE IF EXISTS `insumos`;

-- ============================================================================
-- PASO 3: Eliminar Tabla de Movimientos de Inventario (si existe)
-- ============================================================================
-- 
-- Tabla de auditoría de movimientos de insumos.
-- Se elimina para mantener limpieza total.
-- 

DROP TABLE IF EXISTS `movimientos_inventario`;

-- ============================================================================
-- PASO 4: Remover Columna foto_perfil de usuarios
-- ============================================================================
-- 
-- Ya no se permitirán uploads de fotos de perfil.
-- Los avatares se generarán a partir de iniciales del usuario.
-- 

ALTER TABLE `usuarios` DROP COLUMN IF EXISTS `foto_perfil`;

-- ============================================================================
-- PASO 5: Remover Columna foto_perfil de tiendas (si existe)
-- ============================================================================
-- 
-- Eliminar logo/foto de tienda si estaba almacenada en BD.
-- 

ALTER TABLE `tiendas` DROP COLUMN IF EXISTS `foto_perfil`;

-- ============================================================================
-- [OPCIONAL] PASO 6: Remover Flag es_preparado de productos
-- ============================================================================
-- 
-- Esta columna indicaba si un producto era un "plato preparado" con receta.
-- Sin recetas, es innecesaria. COMENTADA PORQUE ES REVERSIBLE DESPUÉS.
-- 
-- Para ejecutar: descomenta la siguiente línea.
-- 

-- ALTER TABLE `productos` DROP COLUMN IF EXISTS `es_preparado`;

-- ============================================================================
-- Verificación (ejecutar DESPUÉS de todo para confirmar)
-- ============================================================================
-- 
-- SHOW TABLES;  -- No deben aparecer: insumos, recetas_productos, movimientos_inventario
-- DESC usuarios;  -- foto_perfil NO debe existir
-- DESC tiendas;   -- foto_perfil NO debe existir (opcional)
-- 

COMMIT;

-- ============================================================================
-- FIN DEL SCRIPT DE LIMPIEZA MVP
-- ============================================================================
