-- Estado de los CANALES de cada aviso (push y correo). PROPUESTA: NO aplicada a Supabase. SOLO ADITIVA (dos columnas nuevas, anulables).
-- Permite mostrar en la app por donde se aviso y si fallo. Las filas existentes quedan en NULL (sin dato).
-- Requiere el almacen real (20261117000000). Un solo bloque transaccional.
-- Reversion: 20261118020000_estado_canales_avisos_down.sql
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.avisos') IS NULL THEN
        RAISE EXCEPTION 'Falta el almacen real (20261117000000_crear_almacen_real).';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'tinotify_real' AND table_name = 'avisos'
               AND column_name IN ('push_estado', 'correo_estado')) THEN
        RAISE EXCEPTION 'Las columnas de canal ya existen; revisar en lugar de reutilizar.';
    END IF;
END;
$precondiciones$;

ALTER TABLE tinotify_real.avisos
    ADD COLUMN push_estado text COLLATE "C"
        CHECK (push_estado IS NULL OR push_estado IN ('enviado', 'fallido', 'sin_dispositivos', 'no_configurado')),
    ADD COLUMN correo_estado text COLLATE "C"
        CHECK (correo_estado IS NULL OR correo_estado IN ('enviado', 'fallido', 'desactivado'));

GRANT UPDATE (push_estado, correo_estado) ON tinotify_real.avisos TO tinotify_real_app;

DO $auditoria$
DECLARE rol text;
BEGIN
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        IF has_table_privilege(rol, 'tinotify_real.avisos', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
           OR has_any_column_privilege(rol, 'tinotify_real.avisos', 'SELECT,INSERT,UPDATE,REFERENCES') THEN
            RAISE EXCEPTION 'Permiso residual de cliente en tinotify_real.avisos';
        END IF;
    END LOOP;
END;
$auditoria$;
COMMIT;
