-- Reversion de 20261118000000_crear_cuentas_real. NO es una migracion de la CLI.
-- Borra SOLO las tablas sesiones, invitaciones y usuarios (y con ellas las cuentas creadas). No toca el resto del esquema real.
-- Verifica el estado remoto despues: un codigo de salida distinto de cero no prueba por si solo que se revirtio.
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.usuarios') IS NULL OR to_regclass('tinotify_real.sesiones') IS NULL
       OR to_regclass('tinotify_real.invitaciones') IS NULL THEN
        RAISE EXCEPTION 'Las tablas de cuentas no estan completas; revisar a mano.';
    END IF;
END;
$precondiciones$;
DROP TABLE tinotify_real.sesiones;
DROP TABLE tinotify_real.invitaciones;
DROP TABLE tinotify_real.usuarios;
COMMIT;
