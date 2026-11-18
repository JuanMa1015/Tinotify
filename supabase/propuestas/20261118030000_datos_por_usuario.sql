-- Datos del monitor REAL por USUARIO (fase 2 del multiusuario). PROPUESTA: NO aplicada a Supabase.
-- ADITIVA y retrocompatible: las filas actuales quedan con usuario_id NULL = el PROPIETARIO (tu cuenta de siempre, token de siempre).
-- Cada usuario nuevo tiene sus propios datos; nada del propietario se mueve, se borra ni se reescribe.
--   * estado_expediente, avisos, ejecuciones, dispositivos: columna usuario_id (NULL = propietario) con borrado en cascada.
--     (huellas y expedientes cuelgan de estado_expediente por caso_ref y se borran con el usuario.)
--   * credenciales_usuario: credenciales SIGAC CIFRADAS de cada usuario (el propietario sigue en la tabla `credenciales`).
-- Requiere, en este orden: 20261117000000 (almacen real), 20261118000000 (cuentas), 20261118010000 (expedientes), 20261118020000 (canales).
-- Reversion: 20261118030000_datos_por_usuario_down.sql
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.usuarios') IS NULL OR to_regclass('tinotify_real.expedientes') IS NULL THEN
        RAISE EXCEPTION 'Faltan las migraciones previas (cuentas y expedientes).';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'tinotify_real' AND table_name = 'avisos'
                   AND column_name = 'push_estado') THEN
        RAISE EXCEPTION 'Falta la migracion de canales de avisos (20261118020000).';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'tinotify_real'
               AND table_name IN ('estado_expediente', 'avisos', 'ejecuciones', 'dispositivos') AND column_name = 'usuario_id')
       OR to_regclass('tinotify_real.credenciales_usuario') IS NOT NULL THEN
        RAISE EXCEPTION 'Ya existen columnas o tablas por usuario; revisar en lugar de reutilizar.';
    END IF;
END;
$precondiciones$;

ALTER TABLE tinotify_real.estado_expediente ADD COLUMN usuario_id uuid REFERENCES tinotify_real.usuarios(id) ON DELETE CASCADE;
ALTER TABLE tinotify_real.avisos ADD COLUMN usuario_id uuid REFERENCES tinotify_real.usuarios(id) ON DELETE CASCADE;
ALTER TABLE tinotify_real.ejecuciones ADD COLUMN usuario_id uuid REFERENCES tinotify_real.usuarios(id) ON DELETE CASCADE;
ALTER TABLE tinotify_real.dispositivos ADD COLUMN usuario_id uuid REFERENCES tinotify_real.usuarios(id) ON DELETE CASCADE;
CREATE INDEX estado_expediente_por_usuario ON tinotify_real.estado_expediente (usuario_id);
CREATE INDEX avisos_por_usuario ON tinotify_real.avisos (usuario_id) WHERE entregado_en IS NULL;
CREATE INDEX ejecuciones_por_usuario ON tinotify_real.ejecuciones (usuario_id, inicio DESC);
CREATE INDEX dispositivos_por_usuario ON tinotify_real.dispositivos (usuario_id);
-- Un telefono puede pasar de una cuenta a otra: la aplicacion reasigna el dueno del token.
GRANT UPDATE (usuario_id) ON tinotify_real.dispositivos TO tinotify_real_app;

CREATE TABLE tinotify_real.credenciales_usuario (
    usuario_id uuid PRIMARY KEY REFERENCES tinotify_real.usuarios(id) ON DELETE CASCADE,
    version_llave smallint NOT NULL CHECK (version_llave BETWEEN 1 AND 100),
    nonce bytea NOT NULL CHECK (octet_length(nonce) = 12),
    cifrado bytea NOT NULL CHECK (octet_length(cifrado) BETWEEN 17 AND 2048),
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    actualizado_en timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE tinotify_real.credenciales_usuario ENABLE ROW LEVEL SECURITY;
ALTER TABLE tinotify_real.credenciales_usuario FORCE ROW LEVEL SECURITY;
REVOKE ALL ON tinotify_real.credenciales_usuario FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, DELETE ON tinotify_real.credenciales_usuario TO tinotify_real_app;
GRANT UPDATE (version_llave, nonce, cifrado, actualizado_en) ON tinotify_real.credenciales_usuario TO tinotify_real_app;
CREATE POLICY app_lectura ON tinotify_real.credenciales_usuario FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.credenciales_usuario FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.credenciales_usuario FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.credenciales_usuario FOR DELETE TO tinotify_real_app USING (true);

DO $auditoria$
DECLARE rol text; t text;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r' AND NOT (c.relrowsecurity AND c.relforcerowsecurity)) THEN
        RAISE EXCEPTION 'Hay tablas del almacen real sin RLS forzado';
    END IF;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        FOREACH t IN ARRAY ARRAY['credenciales_usuario','estado_expediente','avisos','ejecuciones','dispositivos'] LOOP
            IF has_table_privilege(rol, 'tinotify_real.' || t, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR has_any_column_privilege(rol, 'tinotify_real.' || t, 'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'Permiso residual de cliente en tinotify_real.%', t;
            END IF;
        END LOOP;
    END LOOP;
END;
$auditoria$;
COMMIT;
