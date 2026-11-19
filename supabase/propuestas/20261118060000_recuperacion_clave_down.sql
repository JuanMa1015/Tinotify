-- Reversion de 20261118060000_recuperacion_clave. NO es una migracion de la CLI. Borra solo tinotify_real.recuperaciones.
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.recuperaciones') IS NULL THEN
        RAISE EXCEPTION 'La tabla recuperaciones no existe; revisar a mano.';
    END IF;
END;
$precondiciones$;
DROP TABLE tinotify_real.recuperaciones;
COMMIT;
