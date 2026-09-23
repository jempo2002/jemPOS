-- ============================================================
-- Migracion: Cartera (por cobrar / por pagar) + Clientes B2B
-- Fecha: 2026-09-22
-- Motor: MariaDB 10.4 (soporta IF NOT EXISTS en ALTER)
-- ============================================================
--
-- Decisiones:
--  * No se crea tabla de "fiados": la deuda B2C/B2B sigue viviendo en
--    `ventas` (estado 'Fiada/Pendiente') + `abonos_fiados`, igual que hoy.
--  * `listas_precios` guarda el descuento mayorista; un cliente B2B la
--    referencia. Al borrar la lista el cliente queda sin lista (SET NULL),
--    nunca apuntando a una fila inexistente.
--  * `cuentas_por_pagar` lleva el pago parcial en `monto_pagado`: evita una
--    segunda tabla de abonos que quedaria huerfana al anular la obligacion.
--  * Todo id_tienda va con ON DELETE CASCADE, como el resto del esquema.
-- ============================================================

-- ── 1) Listas de precios mayoristas ─────────────────────────
CREATE TABLE IF NOT EXISTS `listas_precios` (
  `id_lista` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `nombre` varchar(100) NOT NULL,
  `descuento_pct` decimal(5,2) NOT NULL DEFAULT 0.00,
  `min_pedidos_recurrentes` int(10) UNSIGNED NOT NULL DEFAULT 0,
  `estado_activo` tinyint(1) NOT NULL DEFAULT 1,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_lista`),
  UNIQUE KEY `uq_listas_tienda_nombre` (`id_tienda`, `nombre`),
  KEY `idx_listas_tienda_activo` (`id_tienda`, `estado_activo`),
  CONSTRAINT `fk_listas_precios_tiendas`
    FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_listas_descuento_pct` CHECK (`descuento_pct` >= 0 AND `descuento_pct` <= 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── 2) Clientes: tipo B2C/B2B + NIT + lista asignada ────────
ALTER TABLE `clientes`
  ADD COLUMN IF NOT EXISTS `tipo` enum('B2C','B2B') NOT NULL DEFAULT 'B2C' AFTER `telefono`,
  ADD COLUMN IF NOT EXISTS `nit` varchar(30) DEFAULT NULL AFTER `tipo`,
  ADD COLUMN IF NOT EXISTS `id_lista_precios` bigint(20) UNSIGNED DEFAULT NULL AFTER `nit`,
  ADD KEY IF NOT EXISTS `idx_clientes_tienda_tipo` (`id_tienda`, `tipo`, `estado_activo`),
  ADD KEY IF NOT EXISTS `idx_clientes_lista` (`id_lista_precios`);

-- FK a la lista: si se borra la lista el cliente queda sin lista, no huerfano.
-- MariaDB 10.4 no acepta IF NOT EXISTS en ADD CONSTRAINT, se ignora el error 1826/121
-- si ya existe (el runner de migraciones lo reporta como no-op).
ALTER TABLE `clientes`
  ADD CONSTRAINT `fk_clientes_listas_precios`
  FOREIGN KEY (`id_lista_precios`) REFERENCES `listas_precios` (`id_lista`)
  ON DELETE SET NULL ON UPDATE CASCADE;

-- ── 3) Cuentas por pagar (obligaciones del negocio) ─────────
CREATE TABLE IF NOT EXISTS `cuentas_por_pagar` (
  `id_cuenta` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_proveedor` bigint(20) UNSIGNED DEFAULT NULL,
  `categoria` enum('Proveedor','Nomina','Servicios','Arriendo','Impuestos','Otro') NOT NULL DEFAULT 'Otro',
  `concepto` varchar(150) NOT NULL,
  `descripcion` varchar(255) DEFAULT NULL,
  `monto_total` decimal(12,2) NOT NULL,
  `monto_pagado` decimal(12,2) NOT NULL DEFAULT 0.00,
  `fecha_vencimiento` date DEFAULT NULL,
  `estado` enum('Pendiente','Pagada','Anulada') NOT NULL DEFAULT 'Pendiente',
  `id_usuario_creador` bigint(20) UNSIGNED DEFAULT NULL,
  `id_usuario_aprobador` bigint(20) UNSIGNED DEFAULT NULL,
  `fecha_ultimo_pago` timestamp NULL DEFAULT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_cuenta`),
  KEY `idx_cxp_tienda_estado` (`id_tienda`, `estado`, `fecha_vencimiento`),
  KEY `idx_cxp_proveedor` (`id_proveedor`),
  KEY `idx_cxp_creador` (`id_usuario_creador`),
  KEY `idx_cxp_aprobador` (`id_usuario_aprobador`),
  CONSTRAINT `fk_cxp_tiendas`
    FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  -- Borrar un proveedor no debe borrar la obligacion contable: queda sin proveedor.
  CONSTRAINT `fk_cxp_proveedores`
    FOREIGN KEY (`id_proveedor`) REFERENCES `proveedores` (`id_proveedor`)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_cxp_usuario_creador`
    FOREIGN KEY (`id_usuario_creador`) REFERENCES `usuarios` (`id_usuario`)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_cxp_usuario_aprobador`
    FOREIGN KEY (`id_usuario_aprobador`) REFERENCES `usuarios` (`id_usuario`)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_cxp_montos` CHECK (`monto_total` > 0 AND `monto_pagado` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
