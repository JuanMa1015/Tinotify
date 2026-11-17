-- Listado CIFRADO de expedientes del monitor REAL. PROPUESTA: NO aplicada a Supabase. SOLO ADITIVA (una tabla nueva).
-- Guarda, por expediente (caso_ref = HMAC del numero), el numero, el cliente y el estado del listado de SIGAC CIFRADOS con
-- AES-256-GCM por el backend (la llave no esta en la base; el dato queda ligado a su caso_ref), mas conteos de novedades sin ver.
-- Requiere el almacen real (20261117000000). Un solo bloque transaccional; sin IF NOT EXISTS.
-- Reversion: 20261118010000_crear_expedientes_real_down.sql
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.estado_expediente') IS NULL THEN
        RAISE EXCEPTION 'Falta el almacen real (20261117000000_crear_almacen_real).';
    END IF;
    IF to_regclass('tinotify_real.expedientes') IS NOT NULL THEN
        RAISE EXCEPTION 'Ya existe tinotify_real.expedientes; revisar en lugar de reutilizar.';
    END IF;
END;
$precondiciones$;

CREATE TABLE tinotify_real.expedientes (
    caso_ref text COLLATE "C" PRIMARY KEY REFERENCES tinotify_real.estado_expediente(caso_ref) ON DELETE CASCADE
        CHECK (caso_ref ~ '^[0-9a-f]{64}$'),
    version_llave smallint NOT NULL CHECK (version_llave BETWEEN 1 AND 100),
    nonce bytea NOT NULL CHECK (octet_length(nonce) = 12),
    cifrado bytea NOT NULL CHECK (octet_length(cifrado) BETWEEN 17 AND 2048),
    novedades_no_vistas integer NOT NULL DEFAULT 0 CHECK (novedades_no_vistas BETWEEN 0 AND 100000),
    nuevo boolean NOT NULL DEFAULT false,
    ultima_novedad timestamptz,
    actualizado_en timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE tinotify_real.expedientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE tinotify_real.expedientes FORCE ROW LEVEL SECURITY;
REVOKE ALL ON tinotify_real.expedientes FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, DELETE ON tinotify_real.expedientes TO tinotify_real_app;
GRANT UPDATE (version_llave, nonce, cifrado, novedades_no_vistas, nuevo, ultima_novedad, actualizado_en) ON tinotify_real.expedientes TO tinotify_real_app;
CREATE POLICY app_lectura ON tinotify_real.expedientes FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.expedientes FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.expedientes FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.expedientes FOR DELETE TO tinotify_real_app USING (true);

DO $auditoria$
DECLARE rol text;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r' AND NOT (c.relrowsecurity AND c.relforcerowsecurity)) THEN
        RAISE EXCEPTION 'Hay tablas del almacen real sin RLS forzado';
    END IF;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        IF has_table_privilege(rol, 'tinotify_real.expedientes', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
           OR has_any_column_privilege(rol, 'tinotify_real.expedientes', 'SELECT,INSERT,UPDATE,REFERENCES') THEN
            RAISE EXCEPTION 'Permiso residual de cliente en tinotify_real.expedientes';
        END IF;
    END LOOP;
END;
$auditoria$;
COMMIT;
