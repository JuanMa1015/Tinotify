\set ON_ERROR_STOP on
-- FUTURO: A confirma -> 23505 del indice exacto. Con -v aceptar=1, A debe revertir.
BEGIN;
SET LOCAL application_name = 'tinotify_4b1_b';
SET LOCAL lock_timeout = '15s';
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
\if :{?aceptar}
SET LOCAL tinotify.prueba_resultado = 'insertar';
\else
SET LOCAL tinotify.prueba_resultado = 'duplicado';
\endif
DO $resultado$
DECLARE restriccion text;
BEGIN
    BEGIN
        INSERT INTO app.estados_reconciliacion
(estudiante_id,id,instancia_utf8,epoca,situacion,schema_version,state_revision,fingerprint_version,trust_policy,migrated_from_v1)
VALUES (current_setting('tinotify.prueba_run')::uuid,
        md5('b:'||current_setting('tinotify.prueba_run'))::uuid,
        convert_to('CONCURRENCIA_FICTICIA_4B1:'||current_setting('tinotify.prueba_run'),'UTF8'),
        2,'activo',2,2,1,repeat('0',64),false);
        IF current_setting('tinotify.prueba_resultado')<>'insertar' THEN
            RAISE EXCEPTION 'Se esperaba 23505; INSERT aceptado inesperadamente.';
        END IF;
    EXCEPTION WHEN unique_violation THEN
        GET STACKED DIAGNOSTICS restriccion = CONSTRAINT_NAME;
        IF current_setting('tinotify.prueba_resultado')<>'duplicado'
           OR restriccion<>'una_cabecera_viva' THEN
            RAISE EXCEPTION 'Unicidad distinta de la esperada en el ensayo.';
        END IF;
        -- unique_violation es exactamente SQLSTATE 23505. Otros errores se propagan.
    END;
END;
$resultado$;
ROLLBACK;
