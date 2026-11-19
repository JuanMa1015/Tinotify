-- Reversion de 20261118070000_admin_usuarios. NO es una migracion de la CLI. Quita los permisos agregados.
BEGIN;
DROP POLICY app_borrado ON tinotify_real.estado_expediente;
DROP POLICY app_borrado ON tinotify_real.avisos;
DROP POLICY app_borrado ON tinotify_real.ejecuciones;
REVOKE DELETE ON tinotify_real.estado_expediente FROM tinotify_real_app;
REVOKE DELETE ON tinotify_real.avisos FROM tinotify_real_app;
REVOKE DELETE ON tinotify_real.ejecuciones FROM tinotify_real_app;
REVOKE UPDATE (es_admin) ON tinotify_real.usuarios FROM tinotify_real_app;
COMMIT;
