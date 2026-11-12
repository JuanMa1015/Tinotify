\set ON_ERROR_STOP on
-- FUTURO: requiere run_id/fixture_creado_en del setup exitoso.
BEGIN;
SET LOCAL application_name = 'tinotify_4b1_a';
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '20s';
SELECT pg_catalog.set_config('tinotify.prueba_run', :'run_id'::uuid::text, true);
SELECT pg_catalog.set_config('tinotify.prueba_creado', :'fixture_creado_en'::timestamptz::text, true);
DO $fixture$
DECLARE perfil app.estudiantes%ROWTYPE;
BEGIN
    SELECT * INTO STRICT perfil FROM app.estudiantes
    WHERE id=current_setting('tinotify.prueba_run')::uuid FOR KEY SHARE;
    IF perfil.auth_subject IS NOT NULL OR perfil.estado<>'pendiente'
       OR perfil.creado_en<>current_setting('tinotify.prueba_creado')::timestamptz THEN
        RAISE EXCEPTION 'Recibo de fixture incorrecto; no adoptar filas.';
    END IF;
END;
$fixture$;
INSERT INTO app.estados_reconciliacion
(estudiante_id,id,instancia_utf8,epoca,situacion,schema_version,state_revision,fingerprint_version,trust_policy,migrated_from_v1)
VALUES (current_setting('tinotify.prueba_run')::uuid,
        md5('a:'||current_setting('tinotify.prueba_run'))::uuid,
        convert_to('CONCURRENCIA_FICTICIA_4B1:'||current_setting('tinotify.prueba_run'),'UTF8'),
        1,'activo',2,2,1,repeat('0',64),false);
SELECT pg_catalog.pg_sleep(10);
\if :{?abortar}
ROLLBACK;
\else
COMMIT;
\endif
