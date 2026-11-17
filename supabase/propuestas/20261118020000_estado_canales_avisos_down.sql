-- Reversion de 20261118020000_estado_canales_avisos. NO es una migracion de la CLI. Quita solo las dos columnas de canal.
-- OJO: el servidor nuevo escribe esas columnas; revierte DESPUES de desplegar un servidor que no las use.
BEGIN;
ALTER TABLE tinotify_real.avisos DROP COLUMN push_estado, DROP COLUMN correo_estado;
COMMIT;
