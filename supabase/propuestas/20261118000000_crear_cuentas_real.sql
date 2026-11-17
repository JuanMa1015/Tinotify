-- Cuentas multiusuario del monitor REAL (fase 1, SOLO ADITIVA). PROPUESTA: NO aplicada a Supabase.
-- Agrega tres tablas al esquema tinotify_real: usuarios, invitaciones y sesiones. NO modifica ninguna tabla existente,
-- asi que el monitor actual (un solo usuario) sigue funcionando igual tras aplicarla. El dato por usuario llega en la fase 2.
-- Guarda: hash de contrasena (scrypt), HMAC del correo (no el correo), hash SHA-256 de tokens e invitaciones. Nada en claro.
-- Requiere haber aplicado antes 20261117000000_crear_almacen_real. Un solo bloque transaccional; sin IF NOT EXISTS.
-- Reversion: supabase/propuestas/20261118000000_crear_cuentas_real_down.sql
-- Ubicacion: supabase/propuestas (NO la recoge la CLI). Al autorizar su aplicacion: git mv a supabase/migrations/.
BEGIN;

DO $precondiciones$
BEGIN
    IF to_regnamespace('tinotify_real') IS NULL OR to_regclass('tinotify_real.entorno') IS NULL
       OR to_regclass('tinotify_real.dispositivos') IS NULL THEN
        RAISE EXCEPTION 'Falta el almacen real (20261117000000_crear_almacen_real).';
    END IF;
    IF to_regclass('tinotify_real.usuarios') IS NOT NULL OR to_regclass('tinotify_real.invitaciones') IS NOT NULL
       OR to_regclass('tinotify_real.sesiones') IS NOT NULL THEN
        RAISE EXCEPTION 'Ya existen tablas de cuentas; revisar en lugar de reutilizar.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tinotify_real_app') THEN
        RAISE EXCEPTION 'Falta el rol tinotify_real_app.';
    END IF;
END;
$precondiciones$;

CREATE TABLE tinotify_real.usuarios (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    correo_ref text COLLATE "C" NOT NULL UNIQUE CHECK (correo_ref ~ '^[0-9a-f]{64}$'),
    pass_hash text COLLATE "C" NOT NULL CHECK (pass_hash ~ '^scrypt\$[0-9]+\$[0-9]+\$[0-9]+\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$' AND char_length(pass_hash) <= 300),
    es_admin boolean NOT NULL DEFAULT false,
    activo boolean NOT NULL DEFAULT true,
    consentimiento_version text COLLATE "C" NOT NULL CHECK (consentimiento_version ~ '^[a-z0-9._-]{1,40}$'),
    consentimiento_en timestamptz NOT NULL,
    intentos_fallidos smallint NOT NULL DEFAULT 0 CHECK (intentos_fallidos BETWEEN 0 AND 1000),
    bloqueado_hasta timestamptz,
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE tinotify_real.invitaciones (
    codigo_hash text COLLATE "C" PRIMARY KEY CHECK (codigo_hash ~ '^[0-9a-f]{64}$'),
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    expira_en timestamptz NOT NULL,
    usado_por uuid REFERENCES tinotify_real.usuarios(id) ON DELETE SET NULL,
    usado_en timestamptz,
    CONSTRAINT invitacion_vigencia CHECK (expira_en > creado_en)
);

CREATE TABLE tinotify_real.sesiones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES tinotify_real.usuarios(id) ON DELETE CASCADE,
    token_hash text COLLATE "C" NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    dispositivo text COLLATE "C" CHECK (dispositivo IS NULL OR char_length(dispositivo) BETWEEN 1 AND 60),
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    expira_en timestamptz NOT NULL,
    revocada_en timestamptz,
    ultimo_uso timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT sesion_vigencia CHECK (expira_en > creado_en)
);
CREATE INDEX sesiones_por_usuario ON tinotify_real.sesiones (usuario_id) WHERE revocada_en IS NULL;

DO $cierre$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['usuarios','invitaciones','sesiones'] LOOP
        EXECUTE format('ALTER TABLE tinotify_real.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE tinotify_real.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('REVOKE ALL ON tinotify_real.%I FROM PUBLIC, anon, authenticated, service_role', t);
    END LOOP;
END;
$cierre$;

-- Privilegios minimos. UPDATE solo en las columnas que la aplicacion modifica.
GRANT SELECT, INSERT, DELETE ON tinotify_real.usuarios TO tinotify_real_app;
GRANT UPDATE (pass_hash, activo, intentos_fallidos, bloqueado_hasta, consentimiento_version, consentimiento_en)
    ON tinotify_real.usuarios TO tinotify_real_app;
GRANT SELECT, INSERT, DELETE ON tinotify_real.invitaciones TO tinotify_real_app;
GRANT UPDATE (usado_por, usado_en) ON tinotify_real.invitaciones TO tinotify_real_app;
GRANT SELECT, INSERT, DELETE ON tinotify_real.sesiones TO tinotify_real_app;
GRANT UPDATE (revocada_en, ultimo_uso) ON tinotify_real.sesiones TO tinotify_real_app;

CREATE POLICY app_lectura ON tinotify_real.usuarios FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.usuarios FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.usuarios FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.usuarios FOR DELETE TO tinotify_real_app USING (true);
CREATE POLICY app_lectura ON tinotify_real.invitaciones FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.invitaciones FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.invitaciones FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.invitaciones FOR DELETE TO tinotify_real_app USING (true);
CREATE POLICY app_lectura ON tinotify_real.sesiones FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.sesiones FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.sesiones FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.sesiones FOR DELETE TO tinotify_real_app USING (true);

DO $auditoria$
DECLARE rol text; tabla regclass;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r' AND NOT (c.relrowsecurity AND c.relforcerowsecurity)) THEN
        RAISE EXCEPTION 'Hay tablas del almacen real sin RLS forzado';
    END IF;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        FOR tabla IN SELECT c.oid::regclass FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r' LOOP
            IF has_table_privilege(rol, tabla, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
            OR has_any_column_privilege(rol, tabla, 'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'Permiso residual de cliente en el almacen real';
            END IF;
        END LOOP;
    END LOOP;
END;
$auditoria$;
COMMIT;
