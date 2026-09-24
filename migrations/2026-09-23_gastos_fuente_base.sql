-- ============================================================
-- Migracion: nueva fuente de dinero "Base" para los gastos
-- Fecha: 2026-09-23
-- Motor: MariaDB y MySQL 8/9
-- ============================================================
--
-- Hasta ahora un gasto en efectivo salia de 'Caja Menor' o 'Caja Fuerte'.
-- Falta el caso real mas comun del dia a dia: el cajero paga algo con los
-- billetes de la base con la que abrio el turno.
--
-- Importa distinguirlo porque afecta al cuadre: un gasto pagado con la base
-- reduce el efectivo fisico que debe quedar en el cajon al cerrar, y hasta
-- ahora no habia forma de registrarlo sin mentirle al arqueo.
--
-- `MODIFY COLUMN` reescribe la definicion entera de la columna, asi que hay
-- que repetir los tres valores que ya existian: omitir uno lo borraria y
-- dejaria en blanco los gastos que lo usaban. Se puede repetir sin riesgo,
-- el resultado es el mismo.

ALTER TABLE `gastos_caja`
  MODIFY COLUMN `fuente_dinero`
  enum('Caja Menor','Caja Fuerte','Bancos','Base') DEFAULT 'Bancos';
