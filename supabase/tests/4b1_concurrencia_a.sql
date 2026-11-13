\set ON_ERROR_STOP on
-- FUTURO: requiere run_id/fixture_creado_en del setup exitoso.
BEGIN;
SET LOCAL application_name = 'tinotify_4b1_a';
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '20s';
\ir helpers/4b1_validar_fixture.sql
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
