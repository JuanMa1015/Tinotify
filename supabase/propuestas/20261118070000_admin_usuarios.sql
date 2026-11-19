-- Panel de administracion: permisos para que la aplicacion pueda BORRAR los datos de seguimiento de UN usuario (sin borrar su cuenta) y
-- cambiar quien es administrador. PROPUESTA: NO aplicada a Supabase. SOLO AMPLIA permisos (sin tablas ni datos nuevos).
--   * DELETE + politica de borrado en estado_expediente, avisos y ejecuciones (huellas, expedientes y novedades caen en cascada).
--   * UPDATE de la columna es_admin en usuarios.
-- Requiere cuentas, datos por usuario y novedades. Reversion: 20261118070000_admin_usuarios_down.sql
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.novedades') IS NULL OR to_regclass('tinotify_real.credenciales_usuario') IS NULL THEN
        RAISE EXCEPTION 'Faltan migraciones previas (datos por usuario y novedades).';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'tinotify_real' AND policyname = 'app_borrado'
               AND tablename IN ('estado_expediente', 'avisos', 'ejecuciones')) THEN
        RAISE EXCEPTION 'Ya existe una politica de borrado; revisar en lugar de duplicar.';
    END IF;
END;
$precondiciones$;

GRANT DELETE ON tinotify_real.estado_expediente TO tinotify_real_app;
GRANT DELETE ON tinotify_real.avisos TO tinotify_real_app;
GRANT DELETE ON tinotify_real.ejecuciones TO tinotify_real_app;
CREATE POLICY app_borrado ON tinotify_real.estado_expediente FOR DELETE TO tinotify_real_app USING (true);
CREATE POLICY app_borrado ON tinotify_real.avisos FOR DELETE TO tinotify_real_app USING (true);
CREATE POLICY app_borrado ON tinotify_real.ejecuciones FOR DELETE TO tinotify_real_app USING (true);
GRANT UPDATE (es_admin) ON tinotify_real.usuarios TO tinotify_real_app;

DO $auditoria$
DECLARE rol text; t text;
BEGIN
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        FOREACH t IN ARRAY ARRAY['estado_expediente','avisos','ejecuciones','usuarios'] LOOP
            IF has_table_privilege(rol, 'tinotify_real.' || t, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR has_any_column_privilege(rol, 'tinotify_real.' || t, 'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'Permiso residual de cliente en tinotify_real.%', t;
            END IF;
        END LOOP;
    END LOOP;
END;
$auditoria$;
COMMIT;
