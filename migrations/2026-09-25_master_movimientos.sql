-- ============================================================
-- Migracion: finanzas propias del SaaS (Panel Master)
-- Fecha: 2026-09-25
-- Motor: MariaDB y MySQL 8/9
-- ============================================================
--
-- Ingresos (mensualidades, implementaciones) y gastos operativos de jemPOS
-- como negocio. No tiene id_tienda: son las cuentas del proyecto, no las de
-- ninguna tienda cliente.

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
