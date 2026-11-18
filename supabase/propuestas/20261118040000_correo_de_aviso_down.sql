-- Reversion de 20261118040000_correo_de_aviso. NO es una migracion de la CLI. Quita las dos columnas; revierte DESPUES de desplegar un
-- servidor que no las use (el registro las escribe).
BEGIN;
ALTER TABLE tinotify_real.usuarios DROP CONSTRAINT correo_completo, DROP COLUMN correo_nonce, DROP COLUMN correo_cifrado;
COMMIT;
