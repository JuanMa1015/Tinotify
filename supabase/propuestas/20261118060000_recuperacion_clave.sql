-- Recuperacion de contrasena por correo (codigo de un solo uso). PROPUESTA: NO aplicada a Supabase. SOLO ADITIVA (una tabla nueva).
-- Guarda solo el HASH del codigo (SHA-256 ligado al usuario), su vencimiento (15 min), si se uso y cuantos intentos fallidos lleva.
-- Requiere las cuentas (20261118000000). Reversion: 20261118060000_recuperacion_clave_down.sql
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.usuarios') IS NULL THEN
        RAISE EXCEPTION 'Faltan las cuentas (20261118000000).';
    END IF;
    IF to_regclass('tinotify_real.recuperaciones') IS NOT NULL THEN
        RAISE EXCEPTION 'Ya existe tinotify_real.recuperaciones; revisar en lugar de reutilizar.';
    END IF;
END;
$precondiciones$;

CREATE TABLE tinotify_real.recuperaciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES tinotify_real.usuarios(id) ON DELETE CASCADE,
    codigo_hash text COLLATE "C" NOT NULL CHECK (codigo_hash ~ '^[0-9a-f]{64}$'),
    expira_en timestamptz NOT NULL,
    usado_en timestamptz,
    intentos smallint NOT NULL DEFAULT 0 CHECK (intentos BETWEEN 0 AND 1000),
    creada_en timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX recuperaciones_por_usuario ON tinotify_real.recuperaciones (usuario_id, creada_en DESC);
ALTER TABLE tinotify_real.recuperaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE tinotify_real.recuperaciones FORCE ROW LEVEL SECURITY;
REVOKE ALL ON tinotify_real.recuperaciones FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, DELETE ON tinotify_real.recuperaciones TO tinotify_real_app;
GRANT UPDATE (usado_en, intentos) ON tinotify_real.recuperaciones TO tinotify_real_app;
CREATE POLICY app_lectura ON tinotify_real.recuperaciones FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.recuperaciones FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.recuperaciones FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.recuperaciones FOR DELETE TO tinotify_real_app USING (true);

DO $auditoria$
DECLARE rol text;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r' AND NOT (c.relrowsecurity AND c.relforcerowsecurity)) THEN
        RAISE EXCEPTION 'Hay tablas del almacen real sin RLS forzado';
    END IF;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        IF has_table_privilege(rol, 'tinotify_real.recuperaciones', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
           OR has_any_column_privilege(rol, 'tinotify_real.recuperaciones', 'SELECT,INSERT,UPDATE,REFERENCES') THEN
            RAISE EXCEPTION 'Permiso residual de cliente en tinotify_real.recuperaciones';
        END IF;
    END LOOP;
END;
$auditoria$;
COMMIT;
