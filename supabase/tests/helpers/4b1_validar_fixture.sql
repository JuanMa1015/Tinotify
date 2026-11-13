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
