-- Novedades del monitor REAL: una ficha CIFRADA por cada actuacion nueva detectada. PROPUESTA: NO aplicada a Supabase. SOLO ADITIVA.
-- Cada ficha (fecha, etapa, origen/destino, remitente y un extracto corto) se cifra con AES-256-GCM en el backend (la llave no esta en la
-- base) y queda ligada a su caso_ref. La app muestra con ellas el feed de Novedades. Se conservan 90 dias (limpieza en la aplicacion).
-- Requiere, en este orden: almacen real (20261117000000) y expedientes (20261118010000).
-- Reversion: 20261118050000_novedades_down.sql
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.estado_expediente') IS NULL OR to_regclass('tinotify_real.expedientes') IS NULL THEN
        RAISE EXCEPTION 'Faltan las migraciones previas (almacen real y expedientes).';
    END IF;
    IF to_regclass('tinotify_real.novedades') IS NOT NULL THEN
        RAISE EXCEPTION 'Ya existe tinotify_real.novedades; revisar en lugar de reutilizar.';
    END IF;
END;
$precondiciones$;

CREATE TABLE tinotify_real.novedades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    caso_ref text COLLATE "C" NOT NULL REFERENCES tinotify_real.estado_expediente(caso_ref) ON DELETE CASCADE
        CHECK (caso_ref ~ '^[0-9a-f]{64}$'),
    version_llave smallint NOT NULL CHECK (version_llave BETWEEN 1 AND 100),
    nonce bytea NOT NULL CHECK (octet_length(nonce) = 12),
    cifrado bytea NOT NULL CHECK (octet_length(cifrado) BETWEEN 17 AND 4096),
    vista boolean NOT NULL DEFAULT false,
    detectada_en timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX novedades_por_expediente ON tinotify_real.novedades (caso_ref, detectada_en DESC);
CREATE INDEX novedades_por_fecha ON tinotify_real.novedades (detectada_en DESC);
ALTER TABLE tinotify_real.novedades ENABLE ROW LEVEL SECURITY;
ALTER TABLE tinotify_real.novedades FORCE ROW LEVEL SECURITY;
REVOKE ALL ON tinotify_real.novedades FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, DELETE ON tinotify_real.novedades TO tinotify_real_app;
GRANT UPDATE (vista) ON tinotify_real.novedades TO tinotify_real_app;
CREATE POLICY app_lectura ON tinotify_real.novedades FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.novedades FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.novedades FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.novedades FOR DELETE TO tinotify_real_app USING (true);

DO $auditoria$
DECLARE rol text;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r' AND NOT (c.relrowsecurity AND c.relforcerowsecurity)) THEN
        RAISE EXCEPTION 'Hay tablas del almacen real sin RLS forzado';
    END IF;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        IF has_table_privilege(rol, 'tinotify_real.novedades', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
           OR has_any_column_privilege(rol, 'tinotify_real.novedades', 'SELECT,INSERT,UPDATE,REFERENCES') THEN
            RAISE EXCEPTION 'Permiso residual de cliente en tinotify_real.novedades';
        END IF;
    END LOOP;
END;
$auditoria$;
COMMIT;
