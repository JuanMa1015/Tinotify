-- Reversion de 20261118030000_datos_por_usuario. NO es una migracion de la CLI.
-- Quita las columnas usuario_id y la tabla credenciales_usuario. ATENCION: las filas de usuarios (no del propietario) quedarian
-- mezcladas con las del propietario; revierte SOLO si no hay usuarios con datos (o borra antes sus filas con usuario_id NOT NULL).
BEGIN;
DO $precondiciones$
BEGIN
    IF EXISTS (SELECT 1 FROM tinotify_real.estado_expediente WHERE usuario_id IS NOT NULL)
       OR EXISTS (SELECT 1 FROM tinotify_real.avisos WHERE usuario_id IS NOT NULL)
       OR EXISTS (SELECT 1 FROM tinotify_real.ejecuciones WHERE usuario_id IS NOT NULL)
       OR EXISTS (SELECT 1 FROM tinotify_real.dispositivos WHERE usuario_id IS NOT NULL)
       OR EXISTS (SELECT 1 FROM tinotify_real.credenciales_usuario) THEN
        RAISE EXCEPTION 'Hay datos de usuarios; borrarlos (o borrar las cuentas) antes de revertir.';
    END IF;
END;
$precondiciones$;
DROP TABLE tinotify_real.credenciales_usuario;
ALTER TABLE tinotify_real.dispositivos DROP COLUMN usuario_id;
ALTER TABLE tinotify_real.ejecuciones DROP COLUMN usuario_id;
ALTER TABLE tinotify_real.avisos DROP COLUMN usuario_id;
ALTER TABLE tinotify_real.estado_expediente DROP COLUMN usuario_id;
COMMIT;
