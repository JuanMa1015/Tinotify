\set ON_ERROR_STOP on
-- FUTURO: run_id UUID v4 NUEVO por ejecucion. Guardar el recibo solo si COMMIT se confirma.
BEGIN;
SET LOCAL lock_timeout = '3s';
SELECT pg_catalog.set_config('tinotify.prueba_run', :'run_id'::uuid::text, true);
DO $guardia$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=CURRENT_USER AND (rolsuper OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Se requiere administrador autorizado, sin cambiar privilegios.';
    END IF;
    IF substring(current_setting('tinotify.prueba_run'),15,1)<>'4' THEN
        RAISE EXCEPTION 'Usar UUID v4 nuevo generado localmente para el fixture.';
    END IF;
END;
$guardia$;
-- Una colision falla por PK y revierte; nunca adoptar ni modificar fila existente.
INSERT INTO app.estudiantes(id) VALUES (current_setting('tinotify.prueba_run')::uuid)
RETURNING creado_en AS fixture_creado_en \gset
COMMIT;
\echo RECIBO_FICTICIO run_id=:run_id fixture_creado_en=:fixture_creado_en
