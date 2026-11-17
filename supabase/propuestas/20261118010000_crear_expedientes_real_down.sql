-- Reversion de 20261118010000_crear_expedientes_real. NO es una migracion de la CLI. Borra solo tinotify_real.expedientes
-- (el listado cifrado; el monitor lo vuelve a llenar en la siguiente revision). Verifica el estado remoto despues.
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.expedientes') IS NULL THEN
        RAISE EXCEPTION 'La tabla expedientes no existe; revisar a mano.';
    END IF;
END;
$precondiciones$;
DROP TABLE tinotify_real.expedientes;
COMMIT;
