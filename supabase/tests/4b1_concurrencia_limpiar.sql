\set ON_ERROR_STOP on
-- FUTURO: solo run_id y recibo del setup exitoso. Sin recibo, revision manual.
BEGIN;
SET LOCAL lock_timeout = '3s';
SELECT pg_catalog.set_config('tinotify.prueba_run', :'run_id'::uuid::text, true);
SELECT pg_catalog.set_config('tinotify.prueba_creado', :'fixture_creado_en'::timestamptz::text, true);
DO $guardia$
DECLARE perfil app.estudiantes%ROWTYPE;
BEGIN
    -- FOR UPDATE bloquea FK nuevas y cambios al perfil; NOWAIT detecta sesiones vivas.
    SELECT * INTO STRICT perfil FROM app.estudiantes
    WHERE id=current_setting('tinotify.prueba_run')::uuid FOR UPDATE NOWAIT;
    IF perfil.auth_subject IS NOT NULL OR perfil.estado<>'pendiente'
       OR perfil.creado_en<>current_setting('tinotify.prueba_creado')::timestamptz THEN
        RAISE EXCEPTION 'Recibo incorrecto: no borrar.';
    END IF;
    PERFORM 1 FROM app.estados_reconciliacion
    WHERE estudiante_id=perfil.id FOR UPDATE NOWAIT;
    IF EXISTS (SELECT 1 FROM app.expedientes WHERE estudiante_id=perfil.id)
       OR EXISTS (SELECT 1 FROM app_private.importaciones WHERE estudiante_id=perfil.id)
       OR EXISTS (SELECT 1 FROM app.estados_reconciliacion
          WHERE estudiante_id=perfil.id
            AND (id<>md5('a:'||perfil.id::text)::uuid
                 OR instancia_utf8<>convert_to('CONCURRENCIA_FICTICIA_4B1:'||perfil.id::text,'UTF8')
                 OR situacion<>'activo' OR epoca<>1
                 OR schema_version<>2 OR state_revision<>2 OR fingerprint_version<>1
                 OR trust_policy<>repeat('0',64) OR migrated_from_v1)) THEN
        RAISE EXCEPTION 'Fixture inesperado: no borrar, revisar manualmente.';
    END IF;
END;
$guardia$;
DELETE FROM app.estados_reconciliacion
WHERE estudiante_id=current_setting('tinotify.prueba_run')::uuid
  AND id=md5('a:'||current_setting('tinotify.prueba_run'))::uuid;
DELETE FROM app.estudiantes WHERE id=current_setting('tinotify.prueba_run')::uuid
  AND creado_en=current_setting('tinotify.prueba_creado')::timestamptz
  AND auth_subject IS NULL AND estado='pendiente';
COMMIT;
