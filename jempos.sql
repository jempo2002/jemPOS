-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Servidor: 127.0.0.1
-- Tiempo de generación: 16-03-2026 a las 07:48:01
-- Versión del servidor: 10.4.32-MariaDB
-- Versión de PHP: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Base de datos: `jempos`
--

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `abonos_fiados`
--

CREATE TABLE `abonos_fiados` (
  `id_abono` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_venta` bigint(20) UNSIGNED NOT NULL,
  `id_usuario` bigint(20) UNSIGNED NOT NULL,
  `monto_abonado` decimal(12,2) NOT NULL,
  `metodo_pago` enum('Efectivo','Nequi/Daviplata','Tarjeta') NOT NULL,
  `observaciones` varchar(255) DEFAULT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `abonos_fiados`
--

INSERT INTO `abonos_fiados` (`id_abono`, `id_tienda`, `id_venta`, `id_usuario`, `monto_abonado`, `metodo_pago`, `observaciones`, `fecha_creacion`) VALUES
(1, 1, 6, 2, 35000.00, 'Efectivo', NULL, '2026-03-13 02:30:24'),
(2, 2, 13, 3, 5000.00, 'Efectivo', NULL, '2026-03-13 03:54:09'),
(3, 2, 13, 3, 15000.00, 'Efectivo', NULL, '2026-03-13 03:54:20'),
(4, 2, 14, 3, 5000.00, 'Efectivo', NULL, '2026-03-13 03:54:26');

--
-- Disparadores `abonos_fiados`
--
DELIMITER $$
CREATE TRIGGER `bi_abonos_fiados_fecha_creacion` BEFORE INSERT ON `abonos_fiados` FOR EACH ROW BEGIN
    SET NEW.fecha_creacion = CURRENT_TIMESTAMP;
END
$$
DELIMITER ;
DELIMITER $$
CREATE TRIGGER `bi_abonos_fiados_validar_venta_fiada` BEFORE INSERT ON `abonos_fiados` FOR EACH ROW BEGIN
    DECLARE v_estado_venta VARCHAR(20);

    SELECT estado_venta INTO v_estado_venta
      FROM ventas
     WHERE id_venta = NEW.id_venta
     LIMIT 1;

    IF v_estado_venta IS NULL THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'La venta asociada no existe.';
    END IF;

    IF v_estado_venta <> 'Fiada/Pendiente' THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Solo se permiten abonos sobre ventas en estado Fiada/Pendiente.';
    END IF;
END
$$
DELIMITER ;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `auditoria`
--

CREATE TABLE `auditoria` (
  `id_auditoria` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_usuario` bigint(20) UNSIGNED NOT NULL,
  `accion` varchar(100) NOT NULL,
  `detalles` text DEFAULT NULL,
  `fecha_hora` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Volcado de datos para la tabla `auditoria`
--

INSERT INTO `auditoria` (`id_auditoria`, `id_tienda`, `id_usuario`, `accion`, `detalles`, `fecha_hora`) VALUES
(1, 1, 2, 'eliminar_producto', 'Producto desactivado id=2', '2026-03-14 00:18:13'),
(2, 1, 2, 'crear_proveedor', 'Proveedor creado id=1, empresa=palmatronics', '2026-03-14 21:01:32'),
(3, 1, 2, 'crear_proveedor', 'Proveedor creado id=2, empresa=jajaaj', '2026-03-14 21:23:11'),
(4, 1, 2, 'crear_proveedor', 'Proveedor creado id=3, empresa=jajaja|', '2026-03-14 21:30:17'),
(5, 1, 2, 'registrar_gasto', 'Gasto id=0, categoria=compras, monto=5000.0, fuente=Caja Menor', '2026-03-16 05:40:40');

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `categorias`
--

CREATE TABLE `categorias` (
  `id_categoria` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `nombre` varchar(120) NOT NULL,
  `descripcion` varchar(255) DEFAULT NULL,
  `estado_activo` tinyint(1) NOT NULL DEFAULT 1,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  `fecha_actualizacion` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `categorias`
--

INSERT INTO `categorias` (`id_categoria`, `id_tienda`, `nombre`, `descripcion`, `estado_activo`, `fecha_creacion`, `fecha_actualizacion`) VALUES
(1, 1, 'liquidos', NULL, 1, '2026-03-12 07:36:57', '2026-03-12 07:36:57'),
(2, 1, 'arquero', NULL, 1, '2026-03-12 19:41:54', '2026-03-12 19:41:54'),
(3, 2, 'liquidos', NULL, 1, '2026-03-13 03:49:39', '2026-03-13 03:49:39'),
(4, 1, 'Inflamables', NULL, 1, '2026-03-14 00:15:27', '2026-03-14 00:15:27');

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `clientes`
--

CREATE TABLE `clientes` (
  `id_cliente` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `nombre` varchar(150) NOT NULL,
  `telefono` varchar(25) NOT NULL,
  `direccion` varchar(200) DEFAULT NULL,
  `estado_activo` tinyint(1) NOT NULL DEFAULT 1,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  `fecha_actualizacion` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `clientes`
--

INSERT INTO `clientes` (`id_cliente`, `id_tienda`, `nombre`, `telefono`, `direccion`, `estado_activo`, `fecha_creacion`, `fecha_actualizacion`) VALUES
(1, 1, 'juanes', '3145678900', NULL, 1, '2026-03-13 00:07:47', '2026-03-13 00:07:47'),
(2, 1, 'camila', '31545655433', NULL, 1, '2026-03-13 00:10:10', '2026-03-13 00:10:10'),
(3, 2, 'lulo', '3112545698', NULL, 1, '2026-03-13 03:54:05', '2026-03-13 03:54:05');

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `detalle_ventas`
--

CREATE TABLE `detalle_ventas` (
  `id_detalle_venta` bigint(20) UNSIGNED NOT NULL,
  `id_venta` bigint(20) UNSIGNED NOT NULL,
  `id_producto` bigint(20) UNSIGNED NOT NULL,
  `cantidad` decimal(12,3) NOT NULL,
  `precio_unitario_historico` decimal(12,2) NOT NULL,
  `descuento_linea` decimal(12,2) NOT NULL DEFAULT 0.00,
  `subtotal_linea` decimal(12,2) NOT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `detalle_ventas`
--

INSERT INTO `detalle_ventas` (`id_detalle_venta`, `id_venta`, `id_producto`, `cantidad`, `precio_unitario_historico`, `descuento_linea`, `subtotal_linea`, `fecha_creacion`) VALUES
(1, 1, 1, 3.000, 8700.00, 0.00, 26100.00, '2026-03-12 19:21:01'),
(2, 2, 1, 1.000, 8700.00, 0.00, 8700.00, '2026-03-12 19:21:10'),
(3, 3, 2, 6.000, 5000.00, 0.00, 30000.00, '2026-03-13 00:11:23'),
(4, 4, 2, 2.000, 5000.00, 0.00, 10000.00, '2026-03-13 00:12:25'),
(5, 5, 2, 3.000, 7800.00, 0.00, 23400.00, '2026-03-13 00:16:30'),
(6, 8, 2, 3.000, 7800.00, 0.00, 23400.00, '2026-03-13 02:23:21'),
(7, 9, 2, 2.000, 7800.00, 0.00, 15600.00, '2026-03-13 02:23:31'),
(8, 11, 2, 2.000, 7800.00, 0.00, 15600.00, '2026-03-13 02:39:50'),
(9, 12, 2, 1.000, 7800.00, 0.00, 7800.00, '2026-03-13 02:40:03'),
(10, 15, 4, 10.000, 20000.00, 0.00, 200000.00, '2026-03-14 00:17:56'),
(11, 16, 4, 1.000, 20000.00, 0.00, 20000.00, '2026-03-15 00:29:11'),
(12, 17, 4, 4.000, 20000.00, 0.00, 80000.00, '2026-03-15 22:18:00');

--
-- Disparadores `detalle_ventas`
--
DELIMITER $$
CREATE TRIGGER `bi_detalle_ventas_fecha_creacion` BEFORE INSERT ON `detalle_ventas` FOR EACH ROW BEGIN
    SET NEW.fecha_creacion = CURRENT_TIMESTAMP;
END
$$
DELIMITER ;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `gastos_caja`
--

CREATE TABLE `gastos_caja` (
  `id_gasto` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_turno` bigint(20) UNSIGNED NOT NULL,
  `id_usuario` bigint(20) UNSIGNED NOT NULL,
  `concepto` varchar(150) NOT NULL,
  `descripcion` varchar(255) DEFAULT NULL,
  `monto` decimal(12,2) NOT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  `fuente_dinero` enum('Caja Menor','Caja Fuerte','Bancos') DEFAULT 'Bancos'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `gastos_caja`
--

INSERT INTO `gastos_caja` (`id_gasto`, `id_tienda`, `id_turno`, `id_usuario`, `concepto`, `descripcion`, `monto`, `fecha_creacion`, `fuente_dinero`) VALUES
(1, 1, 1, 2, 'Otros', 'compra bolsas de basura', 500.00, '2026-03-12 19:17:48', 'Bancos'),
(2, 1, 1, 2, 'Otros', 'compra bolsas de basura', 500.00, '2026-03-12 19:17:52', 'Bancos'),
(3, 1, 1, 2, 'Otros', 'compra bolsas de basura', 500.00, '2026-03-12 19:17:59', 'Bancos'),
(4, 1, 1, 2, 'Otros', 'compra bolsas de basura', 500.00, '2026-03-12 19:17:59', 'Bancos'),
(5, 1, 1, 2, 'Otros', 'compra bolsas de basura', 500.00, '2026-03-12 19:18:00', 'Bancos'),
(6, 1, 2, 2, 'compras', 'basura', 5000.00, '2026-03-13 02:31:27', 'Bancos'),
(7, 1, 2, 2, 'compras', 'basura', 5000.00, '2026-03-13 02:31:29', 'Bancos'),
(8, 1, 2, 2, 'general', 'basura', 5000.00, '2026-03-13 02:34:02', 'Bancos'),
(9, 1, 2, 2, 'general', 'bolsa de basura', 500.00, '2026-03-13 02:35:31', 'Bancos'),
(10, 1, 2, 2, 'general', 'bolsa de basura', 500.00, '2026-03-13 02:35:38', 'Bancos'),
(11, 1, 2, 2, 'general', 'bolsa de basura', 500.00, '2026-03-13 02:35:39', 'Bancos'),
(12, 1, 2, 2, 'general', '[ORIGEN]Efectivo de la Caja[/ORIGEN] compra de servilletas', 3000.00, '2026-03-13 02:39:06', 'Bancos'),
(13, 1, 4, 2, 'compras', '[ORIGEN]Cuenta Nequi / Banco[/ORIGEN] insumos comprados', 180000.00, '2026-03-14 00:25:34', 'Bancos'),
(14, 1, 4, 2, 'compras', 'compra de limpido', 5000.00, '2026-03-16 05:40:40', 'Caja Menor');

--
-- Disparadores `gastos_caja`
--
DELIMITER $$
CREATE TRIGGER `bi_gastos_caja_fecha_creacion` BEFORE INSERT ON `gastos_caja` FOR EACH ROW BEGIN
    SET NEW.fecha_creacion = CURRENT_TIMESTAMP;
END
$$
DELIMITER ;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `insumos`
--

CREATE TABLE `insumos` (
  `id_insumo` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `nombre` varchar(150) NOT NULL,
  `stock_actual` decimal(12,3) NOT NULL DEFAULT 0.000,
  `unidad_medida` enum('Gr','Ml','Un') NOT NULL DEFAULT 'Un',
  `costo_unitario` decimal(12,2) NOT NULL DEFAULT 0.00,
  `id_proveedor` bigint(20) UNSIGNED DEFAULT NULL,
  `estado_activo` tinyint(1) NOT NULL DEFAULT 1,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  `fecha_actualizacion` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `movimientos_inventario`
--

CREATE TABLE `movimientos_inventario` (
  `id_movimiento` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_producto` bigint(20) UNSIGNED NOT NULL,
  `id_usuario` bigint(20) UNSIGNED NOT NULL,
  `tipo_movimiento` enum('Entrada','Salida','Ajuste') NOT NULL,
  `motivo` varchar(255) NOT NULL,
  `cantidad` decimal(12,3) NOT NULL,
  `stock_anterior` int(11) DEFAULT NULL,
  `stock_posterior` int(11) DEFAULT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `movimientos_inventario`
--

INSERT INTO `movimientos_inventario` (`id_movimiento`, `id_tienda`, `id_producto`, `id_usuario`, `tipo_movimiento`, `motivo`, `cantidad`, `stock_anterior`, `stock_posterior`, `fecha_creacion`) VALUES
(1, 1, 1, 2, 'Entrada', '', 9.000, 1, 91, '2026-03-12 08:13:57'),
(2, 1, 1, 2, 'Entrada', '', 2.000, 91, 93, '2026-03-12 16:36:19'),
(3, 1, 1, 2, 'Entrada', '', 2.000, 93, 95, '2026-03-12 18:39:52'),
(4, 1, 1, 2, 'Entrada', '', 2.000, 3, 5, '2026-03-12 19:20:35'),
(5, 1, 1, 2, 'Entrada', '', 6.000, 5, 11, '2026-03-12 19:20:40'),
(6, 1, 4, 2, 'Entrada', '', 15.000, 0, 15, '2026-03-16 02:27:38');

--
-- Disparadores `movimientos_inventario`
--
DELIMITER $$
CREATE TRIGGER `bi_movimientos_inventario_fecha_creacion` BEFORE INSERT ON `movimientos_inventario` FOR EACH ROW BEGIN
    SET NEW.fecha_creacion = CURRENT_TIMESTAMP;
END
$$
DELIMITER ;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `productos`
--

CREATE TABLE `productos` (
  `id_producto` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_categoria` bigint(20) UNSIGNED DEFAULT NULL,
  `nombre` varchar(150) NOT NULL,
  `descripcion` varchar(255) DEFAULT NULL,
  `codigo_barras` varchar(80) DEFAULT NULL,
  `precio_costo` decimal(12,2) NOT NULL DEFAULT 0.00,
  `precio_venta` decimal(12,2) NOT NULL,
  `stock_actual` int(11) DEFAULT NULL,
  `stock_minimo_alerta` int(11) DEFAULT NULL,
  `estado_activo` tinyint(1) NOT NULL DEFAULT 1,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  `fecha_actualizacion` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `id_proveedor` bigint(20) UNSIGNED DEFAULT NULL,
  `es_preparado` tinyint(1) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `productos`
--

INSERT INTO `productos` (`id_producto`, `id_tienda`, `id_categoria`, `nombre`, `descripcion`, `codigo_barras`, `precio_costo`, `precio_venta`, `stock_actual`, `stock_minimo_alerta`, `estado_activo`, `fecha_creacion`, `fecha_actualizacion`, `id_proveedor`, `es_preparado`) VALUES
(1, 1, 1, 'coca 1', NULL, NULL, 3200.00, 8700.00, 7, 0, 0, '2026-03-12 07:36:57', '2026-03-12 19:40:12', NULL, 0),
(2, 1, 2, 'dibu', NULL, NULL, 3400.00, 7800.00, 0, NULL, 0, '2026-03-12 19:41:54', '2026-03-14 00:18:13', NULL, 0),
(3, 2, 3, 'chery mix', NULL, NULL, 5300.00, 15000.00, 1, NULL, 1, '2026-03-13 03:49:39', '2026-03-13 03:49:39', NULL, 0),
(4, 1, 4, 'Alcohol Isopropilico', NULL, NULL, 6000.00, 20000.00, 15, NULL, 1, '2026-03-14 00:15:27', '2026-03-16 02:27:38', NULL, 0);

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `proveedores`
--

CREATE TABLE `proveedores` (
  `id_proveedor` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `nombre_empresa` varchar(150) NOT NULL,
  `nombre_contacto` varchar(150) DEFAULT NULL,
  `celular` varchar(20) DEFAULT NULL,
  `correo` varchar(100) DEFAULT NULL,
  `detalles` text DEFAULT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Volcado de datos para la tabla `proveedores`
--

INSERT INTO `proveedores` (`id_proveedor`, `id_tienda`, `nombre_empresa`, `nombre_contacto`, `celular`, `correo`, `detalles`, `fecha_creacion`) VALUES
(1, 1, 'palmatronics', 'juan diego', NULL, NULL, 'celulares', '2026-03-14 21:01:32'),
(2, 1, 'jajaaj', 'ajajaajja', '1818181181', NULL, NULL, '2026-03-14 21:23:11'),
(3, 1, 'jajaja|', 'jijijj', '2145698752', NULL, NULL, '2026-03-14 21:30:17');

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `recetas_productos`
--

CREATE TABLE `recetas_productos` (
  `id_receta_producto` bigint(20) UNSIGNED NOT NULL,
  `id_producto` bigint(20) UNSIGNED NOT NULL,
  `id_insumo` bigint(20) UNSIGNED NOT NULL,
  `cantidad_requerida` decimal(12,3) NOT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `tiendas`
--

CREATE TABLE `tiendas` (
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `nombre_negocio` varchar(150) NOT NULL,
  `razon_social` varchar(180) DEFAULT NULL,
  `nit` varchar(30) DEFAULT NULL,
  `telefono` varchar(25) DEFAULT NULL,
  `direccion` varchar(200) DEFAULT NULL,
  `estado` enum('Activo','Suspendido') NOT NULL DEFAULT 'Activo',
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  `fecha_actualizacion` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `fecha_inicio_suscripcion` date DEFAULT NULL,
  `fecha_fin_suscripcion` date DEFAULT NULL,
  `estado_suscripcion` enum('activa','suspendida') DEFAULT 'activa',
  `es_restaurante` tinyint(1) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `tiendas`
--

INSERT INTO `tiendas` (`id_tienda`, `nombre_negocio`, `razon_social`, `nit`, `telefono`, `direccion`, `estado`, `fecha_creacion`, `fecha_actualizacion`, `fecha_inicio_suscripcion`, `fecha_fin_suscripcion`, `estado_suscripcion`, `es_restaurante`) VALUES
(1, 'jemPOS Central', NULL, NULL, NULL, NULL, 'Activo', '2026-03-12 07:29:50', '2026-03-12 07:29:50', NULL, NULL, 'activa', 0),
(2, 'puppifresh', NULL, NULL, '3043729115', NULL, 'Activo', '2026-03-13 03:43:54', '2026-03-13 03:43:54', NULL, NULL, 'activa', 0);

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `turnos_caja`
--

CREATE TABLE `turnos_caja` (
  `id_turno` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_usuario_apertura` bigint(20) UNSIGNED NOT NULL,
  `id_usuario_cierre` bigint(20) UNSIGNED DEFAULT NULL,
  `fecha_apertura` datetime NOT NULL DEFAULT current_timestamp(),
  `monto_inicial` decimal(12,2) NOT NULL,
  `fecha_cierre` datetime DEFAULT NULL,
  `monto_final_esperado` decimal(12,2) DEFAULT NULL,
  `monto_final_real` decimal(12,2) DEFAULT NULL,
  `estado_turno` enum('Abierto','Cerrado') NOT NULL DEFAULT 'Abierto',
  `observaciones` varchar(255) DEFAULT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `turnos_caja`
--

INSERT INTO `turnos_caja` (`id_turno`, `id_tienda`, `id_usuario_apertura`, `id_usuario_cierre`, `fecha_apertura`, `monto_inicial`, `fecha_cierre`, `monto_final_esperado`, `monto_final_real`, `estado_turno`, `observaciones`, `fecha_creacion`) VALUES
(1, 1, 2, 2, '2026-03-12 13:44:40', 20000.00, '2026-03-12 14:21:41', NULL, 50000.00, 'Cerrado', NULL, '2026-03-12 18:44:40'),
(2, 1, 2, 2, '2026-03-12 19:11:08', 20000.00, '2026-03-13 19:16:51', 51200.00, 20000.00, 'Cerrado', NULL, '2026-03-13 00:11:08'),
(3, 2, 3, NULL, '2026-03-12 22:51:26', 20000.00, NULL, 20000.00, NULL, 'Abierto', NULL, '2026-03-13 03:51:26'),
(4, 1, 2, NULL, '2026-03-13 19:17:45', 20000.00, NULL, 215000.00, NULL, 'Abierto', NULL, '2026-03-14 00:17:45');

--
-- Disparadores `turnos_caja`
--
DELIMITER $$
CREATE TRIGGER `bi_turnos_caja_fecha_creacion` BEFORE INSERT ON `turnos_caja` FOR EACH ROW BEGIN
    SET NEW.fecha_creacion = CURRENT_TIMESTAMP;
END
$$
DELIMITER ;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `usuarios`
--

CREATE TABLE `usuarios` (
  `id_usuario` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED DEFAULT NULL,
  `nombre_completo` varchar(150) NOT NULL,
  `correo` varchar(150) NOT NULL,
  `clave_hash` varchar(255) NOT NULL,
  `rol` enum('Master','Admin','Cajero') NOT NULL,
  `estado_activo` tinyint(1) NOT NULL DEFAULT 1,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  `fecha_actualizacion` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `foto_perfil` varchar(255) DEFAULT NULL,
  `cc` varchar(20) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `usuarios`
--

INSERT INTO `usuarios` (`id_usuario`, `id_tienda`, `nombre_completo`, `correo`, `clave_hash`, `rol`, `estado_activo`, `fecha_creacion`, `fecha_actualizacion`, `foto_perfil`, `cc`) VALUES
(1, 1, 'Juanes Montenegro', 'jempo1103@gmail.com', 'scrypt:32768:8:1$d286MO9Gbr6wz1zr$52e59e94f1d42428c852ce6a5f7191da65436ae1448ae85bbb16e13ee301fc7c28eb3da7ec89407e090081dd90c83a27ae7d76fa32cae69309f0c2c7132e0518', 'Master', 1, '2026-03-12 07:29:50', '2026-03-12 07:29:50', NULL, NULL),
(2, 1, 'derly ximena', 'ximenuchis@gmail.com', 'scrypt:32768:8:1$seRW3eO5ZPRfrWCB$25c830a80c274ffefbad238e682a94d1de6981079089a1f04c53e7d419fc101a70a836b95cba4e4a6636ecc7d565c30ce093e06a78f571523a0cf99e5b6dc36d', 'Admin', 1, '2026-03-12 07:34:47', '2026-03-14 21:25:13', NULL, NULL),
(3, 2, 'Brayan Soto', 'bs5349764@gmail.com', 'scrypt:32768:8:1$I2Vuozvcw3IDMVvh$e841d479036756f33bac6439f328054529c97b44cd44f233d125003563ffe235e12dbcb7cf834fb8cf7c323d6e58387aabb591805b666f3ab8864aa342d329fb', 'Admin', 1, '2026-03-13 03:42:38', '2026-03-13 03:43:54', NULL, NULL);

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `ventas`
--

CREATE TABLE `ventas` (
  `id_venta` bigint(20) UNSIGNED NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_turno` bigint(20) UNSIGNED NOT NULL,
  `id_cajero` bigint(20) UNSIGNED NOT NULL,
  `id_cliente` bigint(20) UNSIGNED DEFAULT NULL,
  `numero_venta` varchar(30) DEFAULT NULL,
  `subtotal` decimal(12,2) NOT NULL,
  `tipo_descuento` enum('NINGUNO','MONTO','PORCENTAJE') NOT NULL DEFAULT 'NINGUNO',
  `valor_descuento` decimal(12,2) NOT NULL DEFAULT 0.00,
  `descuento_aplicado` decimal(12,2) NOT NULL DEFAULT 0.00,
  `total_final` decimal(12,2) NOT NULL,
  `metodo_pago` enum('Efectivo','Nequi/Daviplata','Tarjeta') NOT NULL,
  `estado_venta` enum('Pagada','Fiada/Pendiente','Anulada') NOT NULL DEFAULT 'Pagada',
  `observaciones` varchar(255) DEFAULT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `ventas`
--

INSERT INTO `ventas` (`id_venta`, `id_tienda`, `id_turno`, `id_cajero`, `id_cliente`, `numero_venta`, `subtotal`, `tipo_descuento`, `valor_descuento`, `descuento_aplicado`, `total_final`, `metodo_pago`, `estado_venta`, `observaciones`, `fecha_creacion`) VALUES
(1, 1, 1, 2, NULL, 'V0001-000001', 26100.00, 'NINGUNO', 0.00, 0.00, 26100.00, 'Efectivo', '', NULL, '2026-03-12 19:21:01'),
(2, 1, 1, 2, NULL, 'V0001-000002', 8700.00, 'NINGUNO', 0.00, 0.00, 8700.00, '', '', NULL, '2026-03-12 19:21:10'),
(3, 1, 2, 2, NULL, 'V0001-000003', 30000.00, 'NINGUNO', 0.00, 0.00, 30000.00, 'Efectivo', '', NULL, '2026-03-13 00:11:23'),
(4, 1, 2, 2, NULL, 'V0001-000004', 10000.00, 'NINGUNO', 0.00, 0.00, 10000.00, 'Efectivo', '', NULL, '2026-03-13 00:12:25'),
(5, 1, 2, 2, NULL, 'V0001-000005', 23400.00, 'NINGUNO', 0.00, 0.00, 23400.00, 'Efectivo', '', NULL, '2026-03-13 00:16:30'),
(6, 1, 2, 2, 1, 'F0001-000006', 50000.00, 'NINGUNO', 0.00, 0.00, 50000.00, '', 'Fiada/Pendiente', 'Fiado', '2026-03-13 02:20:55'),
(7, 1, 2, 2, 1, 'F0001-000007', 20000.00, 'NINGUNO', 0.00, 0.00, 20000.00, '', 'Fiada/Pendiente', 'Fiado', '2026-03-13 02:21:11'),
(8, 1, 2, 2, NULL, 'V0001-000008', 23400.00, 'NINGUNO', 0.00, 0.00, 23400.00, 'Efectivo', 'Pagada', NULL, '2026-03-13 02:23:21'),
(9, 1, 2, 2, NULL, 'V0001-000009', 15600.00, 'NINGUNO', 0.00, 0.00, 15600.00, 'Nequi/Daviplata', 'Pagada', NULL, '2026-03-13 02:23:31'),
(10, 1, 2, 2, 1, 'F0001-000010', 5000.00, 'NINGUNO', 0.00, 0.00, 5000.00, 'Efectivo', 'Fiada/Pendiente', 'Fiado', '2026-03-13 02:30:59'),
(11, 1, 2, 2, NULL, 'V0001-000011', 15600.00, 'NINGUNO', 0.00, 0.00, 15600.00, 'Nequi/Daviplata', 'Pagada', NULL, '2026-03-13 02:39:50'),
(12, 1, 2, 2, NULL, 'V0001-000012', 7800.00, 'NINGUNO', 0.00, 0.00, 7800.00, 'Efectivo', 'Pagada', NULL, '2026-03-13 02:40:03'),
(13, 2, 3, 3, 3, 'F0002-000001', 15000.00, 'NINGUNO', 0.00, 0.00, 15000.00, 'Efectivo', 'Pagada', 'Saldo inicial', '2026-03-13 03:54:05'),
(14, 2, 3, 3, 3, 'F0002-000002', 5000.00, 'NINGUNO', 0.00, 0.00, 5000.00, 'Efectivo', 'Pagada', 'Fiado', '2026-03-13 03:54:14'),
(15, 1, 4, 2, NULL, 'V0001-000013', 200000.00, 'NINGUNO', 0.00, 0.00, 200000.00, 'Efectivo', 'Pagada', NULL, '2026-03-14 00:17:56'),
(16, 1, 4, 2, NULL, 'V0001-000014', 20000.00, 'NINGUNO', 0.00, 0.00, 20000.00, 'Nequi/Daviplata', 'Pagada', NULL, '2026-03-15 00:29:11'),
(17, 1, 4, 2, NULL, 'V0001-000015', 80000.00, 'NINGUNO', 0.00, 0.00, 80000.00, 'Tarjeta', 'Pagada', NULL, '2026-03-15 22:18:00');

--
-- Disparadores `ventas`
--
DELIMITER $$
CREATE TRIGGER `bi_ventas_fecha_creacion` BEFORE INSERT ON `ventas` FOR EACH ROW BEGIN
    SET NEW.fecha_creacion = CURRENT_TIMESTAMP;
END
$$
DELIMITER ;

--
-- Índices para tablas volcadas
--

--
-- Indices de la tabla `abonos_fiados`
--
ALTER TABLE `abonos_fiados`
  ADD PRIMARY KEY (`id_abono`),
  ADD KEY `idx_abonos_tienda` (`id_tienda`),
  ADD KEY `idx_abonos_venta` (`id_venta`),
  ADD KEY `idx_abonos_usuario` (`id_usuario`),
  ADD KEY `idx_abonos_fecha` (`fecha_creacion`);

--
-- Indices de la tabla `auditoria`
--
ALTER TABLE `auditoria`
  ADD PRIMARY KEY (`id_auditoria`),
  ADD KEY `id_tienda` (`id_tienda`),
  ADD KEY `id_usuario` (`id_usuario`);

--
-- Indices de la tabla `categorias`
--
ALTER TABLE `categorias`
  ADD PRIMARY KEY (`id_categoria`),
  ADD UNIQUE KEY `uq_categorias_tienda_nombre` (`id_tienda`,`nombre`),
  ADD KEY `idx_categorias_tienda` (`id_tienda`);

--
-- Indices de la tabla `clientes`
--
ALTER TABLE `clientes`
  ADD PRIMARY KEY (`id_cliente`),
  ADD UNIQUE KEY `uq_clientes_tienda_telefono` (`id_tienda`,`telefono`),
  ADD KEY `idx_clientes_tienda` (`id_tienda`);

--
-- Indices de la tabla `detalle_ventas`
--
ALTER TABLE `detalle_ventas`
  ADD PRIMARY KEY (`id_detalle_venta`),
  ADD KEY `idx_detalle_venta` (`id_venta`),
  ADD KEY `idx_detalle_producto` (`id_producto`);

--
-- Indices de la tabla `gastos_caja`
--
ALTER TABLE `gastos_caja`
  ADD PRIMARY KEY (`id_gasto`),
  ADD KEY `idx_gastos_tienda` (`id_tienda`),
  ADD KEY `idx_gastos_turno` (`id_turno`),
  ADD KEY `idx_gastos_usuario` (`id_usuario`),
  ADD KEY `idx_gastos_fecha` (`fecha_creacion`);

--
-- Indices de la tabla `insumos`
--
ALTER TABLE `insumos`
  ADD PRIMARY KEY (`id_insumo`),
  ADD UNIQUE KEY `uq_insumos_tienda_nombre` (`id_tienda`,`nombre`),
  ADD KEY `idx_insumos_tienda` (`id_tienda`),
  ADD KEY `idx_insumos_proveedor` (`id_proveedor`);

--
-- Indices de la tabla `movimientos_inventario`
--
ALTER TABLE `movimientos_inventario`
  ADD PRIMARY KEY (`id_movimiento`),
  ADD KEY `idx_movimientos_tienda` (`id_tienda`),
  ADD KEY `idx_movimientos_producto` (`id_producto`),
  ADD KEY `idx_movimientos_usuario` (`id_usuario`),
  ADD KEY `idx_movimientos_fecha` (`fecha_creacion`);

--
-- Indices de la tabla `productos`
--
ALTER TABLE `productos`
  ADD PRIMARY KEY (`id_producto`),
  ADD UNIQUE KEY `uq_productos_tienda_codigo_barras` (`id_tienda`,`codigo_barras`),
  ADD KEY `idx_productos_tienda` (`id_tienda`),
  ADD KEY `idx_productos_categoria` (`id_categoria`),
  ADD KEY `fk_productos_proveedores` (`id_proveedor`);

--
-- Indices de la tabla `proveedores`
--
ALTER TABLE `proveedores`
  ADD PRIMARY KEY (`id_proveedor`),
  ADD KEY `id_tienda` (`id_tienda`);

--
-- Indices de la tabla `recetas_productos`
--
ALTER TABLE `recetas_productos`
  ADD PRIMARY KEY (`id_receta_producto`),
  ADD UNIQUE KEY `uq_receta_producto_insumo` (`id_producto`,`id_insumo`),
  ADD KEY `idx_receta_producto` (`id_producto`),
  ADD KEY `idx_receta_insumo` (`id_insumo`);

--
-- Indices de la tabla `tiendas`
--
ALTER TABLE `tiendas`
  ADD PRIMARY KEY (`id_tienda`),
  ADD UNIQUE KEY `uq_tiendas_nit` (`nit`);

--
-- Indices de la tabla `turnos_caja`
--
ALTER TABLE `turnos_caja`
  ADD PRIMARY KEY (`id_turno`),
  ADD KEY `idx_turnos_tienda` (`id_tienda`),
  ADD KEY `idx_turnos_usuario_apertura` (`id_usuario_apertura`),
  ADD KEY `idx_turnos_usuario_cierre` (`id_usuario_cierre`),
  ADD KEY `idx_turnos_estado` (`estado_turno`);

--
-- Indices de la tabla `usuarios`
--
ALTER TABLE `usuarios`
  ADD PRIMARY KEY (`id_usuario`),
  ADD UNIQUE KEY `uq_usuarios_correo` (`correo`),
  ADD UNIQUE KEY `uq_usuarios_cc` (`cc`),
  ADD KEY `idx_usuarios_tienda` (`id_tienda`);

--
-- Indices de la tabla `ventas`
--
ALTER TABLE `ventas`
  ADD PRIMARY KEY (`id_venta`),
  ADD UNIQUE KEY `uq_ventas_tienda_numero_venta` (`id_tienda`,`numero_venta`),
  ADD KEY `idx_ventas_tienda` (`id_tienda`),
  ADD KEY `idx_ventas_turno` (`id_turno`),
  ADD KEY `idx_ventas_cajero` (`id_cajero`),
  ADD KEY `idx_ventas_cliente` (`id_cliente`),
  ADD KEY `idx_ventas_estado` (`estado_venta`),
  ADD KEY `idx_ventas_fecha` (`fecha_creacion`);

--
-- AUTO_INCREMENT de las tablas volcadas
--

--
-- AUTO_INCREMENT de la tabla `abonos_fiados`
--
ALTER TABLE `abonos_fiados`
  MODIFY `id_abono` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT de la tabla `auditoria`
--
ALTER TABLE `auditoria`
  MODIFY `id_auditoria` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6;

--
-- AUTO_INCREMENT de la tabla `categorias`
--
ALTER TABLE `categorias`
  MODIFY `id_categoria` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT de la tabla `clientes`
--
ALTER TABLE `clientes`
  MODIFY `id_cliente` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT de la tabla `detalle_ventas`
--
ALTER TABLE `detalle_ventas`
  MODIFY `id_detalle_venta` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=13;

--
-- AUTO_INCREMENT de la tabla `gastos_caja`
--
ALTER TABLE `gastos_caja`
  MODIFY `id_gasto` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=15;

--
-- AUTO_INCREMENT de la tabla `insumos`
--
ALTER TABLE `insumos`
  MODIFY `id_insumo` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `movimientos_inventario`
--
ALTER TABLE `movimientos_inventario`
  MODIFY `id_movimiento` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=7;

--
-- AUTO_INCREMENT de la tabla `productos`
--
ALTER TABLE `productos`
  MODIFY `id_producto` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT de la tabla `proveedores`
--
ALTER TABLE `proveedores`
  MODIFY `id_proveedor` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT de la tabla `recetas_productos`
--
ALTER TABLE `recetas_productos`
  MODIFY `id_receta_producto` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `tiendas`
--
ALTER TABLE `tiendas`
  MODIFY `id_tienda` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT de la tabla `turnos_caja`
--
ALTER TABLE `turnos_caja`
  MODIFY `id_turno` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT de la tabla `usuarios`
--
ALTER TABLE `usuarios`
  MODIFY `id_usuario` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT de la tabla `ventas`
--
ALTER TABLE `ventas`
  MODIFY `id_venta` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=18;

--
-- Restricciones para tablas volcadas
--

--
-- Filtros para la tabla `abonos_fiados`
--
ALTER TABLE `abonos_fiados`
  ADD CONSTRAINT `fk_abonos_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_abonos_usuarios` FOREIGN KEY (`id_usuario`) REFERENCES `usuarios` (`id_usuario`) ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_abonos_ventas` FOREIGN KEY (`id_venta`) REFERENCES `ventas` (`id_venta`) ON DELETE CASCADE ON UPDATE CASCADE;

--
-- Filtros para la tabla `auditoria`
--
ALTER TABLE `auditoria`
  ADD CONSTRAINT `auditoria_ibfk_1` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE,
  ADD CONSTRAINT `auditoria_ibfk_2` FOREIGN KEY (`id_usuario`) REFERENCES `usuarios` (`id_usuario`) ON DELETE CASCADE;

--
-- Filtros para la tabla `categorias`
--
ALTER TABLE `categorias`
  ADD CONSTRAINT `fk_categorias_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE;

--
-- Filtros para la tabla `clientes`
--
ALTER TABLE `clientes`
  ADD CONSTRAINT `fk_clientes_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE;

--
-- Filtros para la tabla `detalle_ventas`
--
ALTER TABLE `detalle_ventas`
  ADD CONSTRAINT `fk_detalle_productos` FOREIGN KEY (`id_producto`) REFERENCES `productos` (`id_producto`) ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_detalle_ventas` FOREIGN KEY (`id_venta`) REFERENCES `ventas` (`id_venta`) ON DELETE CASCADE ON UPDATE CASCADE;

--
-- Filtros para la tabla `gastos_caja`
--
ALTER TABLE `gastos_caja`
  ADD CONSTRAINT `fk_gastos_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_gastos_turnos` FOREIGN KEY (`id_turno`) REFERENCES `turnos_caja` (`id_turno`) ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_gastos_usuarios` FOREIGN KEY (`id_usuario`) REFERENCES `usuarios` (`id_usuario`) ON UPDATE CASCADE;

--
-- Filtros para la tabla `insumos`
--
ALTER TABLE `insumos`
  ADD CONSTRAINT `fk_insumos_proveedores` FOREIGN KEY (`id_proveedor`) REFERENCES `proveedores` (`id_proveedor`) ON DELETE SET NULL ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_insumos_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE;

--
-- Filtros para la tabla `movimientos_inventario`
--
ALTER TABLE `movimientos_inventario`
  ADD CONSTRAINT `fk_movimientos_productos` FOREIGN KEY (`id_producto`) REFERENCES `productos` (`id_producto`) ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_movimientos_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_movimientos_usuarios` FOREIGN KEY (`id_usuario`) REFERENCES `usuarios` (`id_usuario`) ON UPDATE CASCADE;

--
-- Filtros para la tabla `productos`
--
ALTER TABLE `productos`
  ADD CONSTRAINT `fk_productos_categorias` FOREIGN KEY (`id_categoria`) REFERENCES `categorias` (`id_categoria`) ON DELETE SET NULL ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_productos_proveedores` FOREIGN KEY (`id_proveedor`) REFERENCES `proveedores` (`id_proveedor`) ON DELETE SET NULL ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_productos_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE;

--
-- Filtros para la tabla `proveedores`
--
ALTER TABLE `proveedores`
  ADD CONSTRAINT `proveedores_ibfk_1` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE;

--
-- Filtros para la tabla `recetas_productos`
--
ALTER TABLE `recetas_productos`
  ADD CONSTRAINT `fk_recetas_productos_insumo` FOREIGN KEY (`id_insumo`) REFERENCES `insumos` (`id_insumo`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_recetas_productos_producto` FOREIGN KEY (`id_producto`) REFERENCES `productos` (`id_producto`) ON DELETE CASCADE ON UPDATE CASCADE;

--
-- Filtros para la tabla `turnos_caja`
--
ALTER TABLE `turnos_caja`
  ADD CONSTRAINT `fk_turnos_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_turnos_usuario_apertura` FOREIGN KEY (`id_usuario_apertura`) REFERENCES `usuarios` (`id_usuario`) ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_turnos_usuario_cierre` FOREIGN KEY (`id_usuario_cierre`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE;

--
-- Filtros para la tabla `usuarios`
--
ALTER TABLE `usuarios`
  ADD CONSTRAINT `fk_usuarios_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE;

--
-- Filtros para la tabla `ventas`
--
ALTER TABLE `ventas`
  ADD CONSTRAINT `fk_ventas_cajeros` FOREIGN KEY (`id_cajero`) REFERENCES `usuarios` (`id_usuario`) ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_ventas_clientes` FOREIGN KEY (`id_cliente`) REFERENCES `clientes` (`id_cliente`) ON DELETE SET NULL ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_ventas_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_ventas_turnos` FOREIGN KEY (`id_turno`) REFERENCES `turnos_caja` (`id_turno`) ON UPDATE CASCADE;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
