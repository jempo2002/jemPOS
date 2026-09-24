-- ============================================================
-- Migracion: tiendas.estado admite 'Eliminado' (soft delete)
-- Fecha: 2026-09-23
-- Motor: MariaDB y MySQL 8/9
-- ============================================================
--
-- Eliminar una tienda desde el Panel Master hacia `DELETE FROM tiendas`, que
-- falla con 1451 en cualquier tienda con ventas: detalle_ventas -> productos,
-- ventas -> turnos_caja y ventas/gastos/movimientos -> usuarios son RESTRICT.
-- Borrar en cascada ademas destruiria el historial contable.
--
-- Ahora la tienda se marca 'Eliminado', sus usuarios quedan inactivos y los
-- listados del panel la ocultan. Los datos siguen en la base.

ALTER TABLE `tiendas`
  MODIFY `estado` enum('Activo','Suspendido','Eliminado') NOT NULL DEFAULT 'Activo';
