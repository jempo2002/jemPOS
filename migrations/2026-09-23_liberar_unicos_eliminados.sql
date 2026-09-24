-- ============================================================
-- Migracion: liberar correo/cc/NIT de registros eliminados
-- Fecha: 2026-09-23
-- Motor: MariaDB y MySQL 8/9
-- ============================================================
--
-- Eliminar un usuario o una tienda es soft delete (estado_activo=0 /
-- estado='Eliminado'), pero la fila seguia ocupando uq_usuarios_correo,
-- uq_usuarios_cc y uq_tiendas_nit: nadie podia volver a registrarse con ese
-- correo, cedula o NIT.
--
-- Al eliminar, el backend ahora antepone 'deleted_<unix_ts>_' a esos campos
-- (app/routes/core.py, _LIBERAR_USUARIO_SQL). El prefijo son hasta 20
-- caracteres, asi que las columnas crecen para que quepa sin truncar:
--   correo 150 + 20 <= 191 (191 * 4 bytes cabe en cualquier indice InnoDB)
--   cc/nit  30 + 20 <= 50  (el registro publico guarda el NIT como cc)

ALTER TABLE `usuarios`
  MODIFY `correo` varchar(191) NOT NULL,
  MODIFY `cc` varchar(50) DEFAULT NULL;

ALTER TABLE `tiendas`
  MODIFY `nit` varchar(50) DEFAULT NULL;

-- Filas eliminadas antes de esta migracion.
UPDATE `usuarios`
   SET `correo` = CONCAT('deleted_', UNIX_TIMESTAMP(), '_', `correo`),
       `cc` = CONCAT('deleted_', UNIX_TIMESTAMP(), '_', `cc`)
 WHERE `estado_activo` = 0 AND `correo` NOT LIKE 'deleted\_%';

UPDATE `tiendas`
   SET `nit` = CONCAT('deleted_', UNIX_TIMESTAMP(), '_', `nit`)
 WHERE `estado` = 'Eliminado' AND `nit` NOT LIKE 'deleted\_%';
