-- Reversion de 20261118050000_novedades. NO es una migracion de la CLI. Borra solo tinotify_real.novedades (las fichas del feed; el
-- monitor no las regenera: solo las futuras). Verifica el estado remoto despues.
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.novedades') IS NULL THEN
        RAISE EXCEPTION 'La tabla novedades no existe; revisar a mano.';
    END IF;
END;
$precondiciones$;
DROP TABLE tinotify_real.novedades;
COMMIT;
