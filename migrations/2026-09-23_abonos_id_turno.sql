-- ============================================================
-- Migracion: abonos_fiados.id_turno (arqueo de caja sin ambiguedad)
-- Fecha: 2026-09-23
-- Motor: MariaDB y MySQL 8/9
-- ============================================================
--
-- El arqueo necesita saber que abonos en efectivo entraron al cajon durante
-- un turno. Hasta ahora se deducia por fecha: los abonos posteriores a la
-- apertura del turno abierto.
--
-- Eso falla en el borde. `fecha_creacion` es un timestamp con precision de
-- segundos, asi que un abono registrado en el mismo segundo en que se abre un
-- turno cae dentro de la ventana de ese turno y de la del anterior: el mismo
-- dinero cuenta dos veces. Improbable, pero es un arqueo de caja, y un
-- descuadre fantasma le cuesta al cajero explicar un dinero que nunca falto.
--
-- Con la columna la pertenencia es un hecho registrado, no una inferencia.
--
-- Las filas antiguas se rellenan buscando el turno de la misma tienda cuya
-- ventana de apertura/cierre contiene el abono. Si ninguna encaja (datos
-- cargados a mano, volcados) el valor se queda en NULL y ese abono no entra
-- en ningun arqueo, que es preferible a asignarlo al turno equivocado.

ALTER TABLE `abonos_fiados`
  ADD COLUMN `id_turno` bigint(20) UNSIGNED DEFAULT NULL AFTER `id_venta`;

ALTER TABLE `abonos_fiados`
  ADD KEY `idx_abonos_turno` (`id_turno`);

-- Borrar un turno no debe borrar el abono: el pago del cliente ocurrio.
ALTER TABLE `abonos_fiados`
  ADD CONSTRAINT `fk_abonos_turnos`
  FOREIGN KEY (`id_turno`) REFERENCES `turnos_caja` (`id_turno`)
  ON DELETE SET NULL ON UPDATE CASCADE;

-- Subconsulta correlacionada y no un JOIN: si dos ventanas se solaparan por
-- datos sucios, un JOIN multiplicaria las filas; aqui se toma un solo turno,
-- el de apertura mas reciente que contenga al abono.
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
