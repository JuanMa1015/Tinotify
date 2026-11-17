-- Almacen PostgreSQL del MONITOR REAL de Tinotify. PROPUESTA: NO aplicada a Supabase.
-- Independiente de las migraciones 20261112050000..20261114020000 y del esquema tinotify_sintetico: no los usa ni los modifica.
-- NO guarda texto judicial: solo huellas con clave (HMAC), conteos, credenciales CIFRADAS por el backend y tokens de dispositivo.
-- La llave de cifrado NO esta en la base: vive solo como secreto del servicio (Render). Sin ella, la fila de credenciales es inutil.
-- Sin IF NOT EXISTS: un objeto previo exige revision, no reutilizacion. Un solo bloque transaccional.
-- Ubicacion: supabase/propuestas (NO la recoge la CLI). Al autorizar su aplicacion: git mv a supabase/migrations/.
-- Reversion: supabase/propuestas/20261117000000_crear_almacen_real_down.sql
-- No crea ningun rol LOGIN ni contraseña: el operador provisiona el login aparte (docs/monitor-real-supabase.md).
BEGIN;

DO $precondiciones$
BEGIN
    IF current_setting('server_version_num')::integer / 10000 < 15 THEN
        RAISE EXCEPTION 'Almacen real revisado para PostgreSQL 15 o superior.';
    END IF;
    IF (SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname IN ('anon','authenticated','service_role')) <> 3 THEN
        RAISE EXCEPTION 'Se esperan los roles de cliente de Supabase (anon, authenticated, service_role).';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = CURRENT_USER AND (rolsuper OR rolcreaterole)) THEN
        RAISE EXCEPTION 'Se requiere una identidad con CREATEROLE; no se eleva automaticamente.';
    END IF;
END;
$precondiciones$;

CREATE SCHEMA tinotify_real AUTHORIZATION CURRENT_USER;
CREATE ROLE tinotify_real_app NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
-- NOINHERIT aqui no limita al login futuro: el operador lo crea con INHERIT y membresia explicita.
REVOKE ALL ON SCHEMA tinotify_real FROM PUBLIC, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA tinotify_real TO tinotify_real_app;
COMMENT ON SCHEMA tinotify_real IS 'Tinotify: estado del monitor REAL (huellas con clave, credenciales cifradas). Nunca expuesto por la Data API.';

-- Marca de entorno: la aplicacion se niega a usar un esquema sin esta fila.
CREATE TABLE tinotify_real.entorno (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    proposito text NOT NULL DEFAULT 'real' CHECK (proposito = 'real'),
    version_esquema smallint NOT NULL DEFAULT 1 CHECK (version_esquema = 1)
);
INSERT INTO tinotify_real.entorno DEFAULT VALUES;

-- Credenciales SIGAC CIFRADAS (AES-256-GCM hecho por el backend; la base nunca ve el texto claro ni la llave).
-- Una sola cuenta (fila unica). `nonce` de 12 bytes; `cifrado` incluye la etiqueta de autenticacion (16 bytes).
CREATE TABLE tinotify_real.credenciales (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    version_llave smallint NOT NULL CHECK (version_llave BETWEEN 1 AND 100),
    nonce bytea NOT NULL CHECK (octet_length(nonce) = 12),
    cifrado bytea NOT NULL CHECK (octet_length(cifrado) BETWEEN 17 AND 2048),
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    actualizado_en timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Un expediente observado. `caso_ref` es un HMAC-SHA256 del numero de caso con una subclave del servicio: no se puede
-- recuperar el numero ni enlazarlo con otra fuente sin la llave. `acreditado` marca los expedientes con contrato de
-- identidad vigente; los demas son provisionales (una huella previa ausente se trata como anomalia, no como novedad).
CREATE TABLE tinotify_real.estado_expediente (
    caso_ref text COLLATE "C" PRIMARY KEY CHECK (caso_ref ~ '^[0-9a-f]{64}$'),
    acreditado boolean NOT NULL DEFAULT false,
    actuaciones integer NOT NULL CHECK (actuaciones BETWEEN 0 AND 20000),
    generacion bigint NOT NULL DEFAULT 1 CHECK (generacion >= 1),
    anomalia boolean NOT NULL DEFAULT false,
    primera_vista timestamptz NOT NULL DEFAULT clock_timestamp(),
    ultima_lectura timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Multiconjunto de huellas con clave por expediente (con multiplicidad). Sin fechas, remitentes ni textos.
CREATE TABLE tinotify_real.huellas (
    caso_ref text COLLATE "C" NOT NULL REFERENCES tinotify_real.estado_expediente(caso_ref) ON DELETE CASCADE,
    huella text COLLATE "C" NOT NULL CHECK (huella ~ '^[0-9a-f]{64}$'),
    cantidad integer NOT NULL CHECK (cantidad BETWEEN 1 AND 20000),
    PRIMARY KEY (caso_ref, huella)
);

-- Bandeja de avisos (outbox): SOLO conteos. Se crea ANTES de enviar y se marca entregada despues, de modo que un fallo
-- entre ambos pasos pueda repetir un aviso pero nunca perder una novedad.
CREATE TABLE tinotify_real.avisos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    expedientes_con_novedades smallint NOT NULL CHECK (expedientes_con_novedades BETWEEN 0 AND 1000),
    novedades integer NOT NULL CHECK (novedades BETWEEN 0 AND 100000),
    expedientes_nuevos smallint NOT NULL DEFAULT 0 CHECK (expedientes_nuevos BETWEEN 0 AND 1000),
    anomalias smallint NOT NULL DEFAULT 0 CHECK (anomalias BETWEEN 0 AND 1000),
    intentos smallint NOT NULL DEFAULT 0 CHECK (intentos BETWEEN 0 AND 1000),
    entregado_en timestamptz,
    CONSTRAINT aviso_con_contenido CHECK (novedades > 0 OR expedientes_nuevos > 0 OR anomalias > 0)
);
CREATE INDEX avisos_pendientes ON tinotify_real.avisos (creado_en, id) WHERE entregado_en IS NULL;

-- Historial de ejecuciones del monitor (observabilidad): codigos de catalogo y conteos, sin identificadores ni contenido.
CREATE TABLE tinotify_real.ejecuciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    inicio timestamptz NOT NULL DEFAULT clock_timestamp(),
    fin timestamptz,
    resultado text NOT NULL DEFAULT 'en_curso'
        CHECK (resultado IN ('en_curso','ok','linea_base','anomalia','error_acceso','error_sigac','error_estado','error_interno')),
    expedientes smallint CHECK (expedientes IS NULL OR expedientes BETWEEN 0 AND 1000),
    novedades integer CHECK (novedades IS NULL OR novedades BETWEEN 0 AND 100000),
    codigo text CHECK (codigo IS NULL OR codigo ~ '^[a-z0-9_]{1,64}$')
);
CREATE INDEX ejecuciones_recientes ON tinotify_real.ejecuciones (inicio DESC);

-- Dispositivos Android para el push (token de Firebase Cloud Messaging). No es una credencial SIGAC.
CREATE TABLE tinotify_real.dispositivos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token text COLLATE "C" NOT NULL UNIQUE CHECK (char_length(token) BETWEEN 20 AND 4096 AND token !~ '\s'),
    plataforma text NOT NULL DEFAULT 'android' CHECK (plataforma = 'android'),
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    ultimo_uso timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Cierre por tabla: RLS forzado, sin acceso para clientes de la Data API.
DO $cierre$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['entorno','credenciales','estado_expediente','huellas','avisos','ejecuciones','dispositivos'] LOOP
        EXECUTE format('ALTER TABLE tinotify_real.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE tinotify_real.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('REVOKE ALL ON tinotify_real.%I FROM PUBLIC, anon, authenticated, service_role', t);
    END LOOP;
END;
$cierre$;

-- Privilegios minimos para el rol de la aplicacion; nunca TRUNCATE, DDL ni privilegios sobre otros esquemas.
-- UPDATE solo sobre las columnas que la aplicacion modifica (no ids, claves ni fechas de creacion).
GRANT SELECT ON tinotify_real.entorno TO tinotify_real_app;
GRANT SELECT, INSERT, DELETE ON tinotify_real.credenciales TO tinotify_real_app;
GRANT UPDATE (version_llave, nonce, cifrado, actualizado_en) ON tinotify_real.credenciales TO tinotify_real_app;
GRANT SELECT, INSERT ON tinotify_real.estado_expediente TO tinotify_real_app;
GRANT UPDATE (acreditado, actuaciones, generacion, anomalia, ultima_lectura) ON tinotify_real.estado_expediente TO tinotify_real_app;
GRANT SELECT, INSERT, DELETE ON tinotify_real.huellas TO tinotify_real_app;
GRANT UPDATE (cantidad) ON tinotify_real.huellas TO tinotify_real_app;
GRANT SELECT, INSERT ON tinotify_real.avisos TO tinotify_real_app;
GRANT UPDATE (intentos, entregado_en) ON tinotify_real.avisos TO tinotify_real_app;
GRANT SELECT, INSERT ON tinotify_real.ejecuciones TO tinotify_real_app;
GRANT UPDATE (fin, resultado, expedientes, novedades, codigo) ON tinotify_real.ejecuciones TO tinotify_real_app;
GRANT SELECT, INSERT, DELETE ON tinotify_real.dispositivos TO tinotify_real_app;
GRANT UPDATE (ultimo_uso) ON tinotify_real.dispositivos TO tinotify_real_app;
-- Una politica por orden y tabla, solo para el rol de la aplicacion (nada de FOR ALL): un privilegio futuro no se
-- activa por accidente.
CREATE POLICY app_lectura ON tinotify_real.entorno FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_lectura ON tinotify_real.credenciales FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.credenciales FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.credenciales FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.credenciales FOR DELETE TO tinotify_real_app USING (true);
CREATE POLICY app_lectura ON tinotify_real.estado_expediente FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.estado_expediente FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.estado_expediente FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_lectura ON tinotify_real.huellas FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.huellas FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.huellas FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.huellas FOR DELETE TO tinotify_real_app USING (true);
CREATE POLICY app_lectura ON tinotify_real.avisos FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.avisos FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.avisos FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_lectura ON tinotify_real.ejecuciones FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.ejecuciones FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.ejecuciones FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_lectura ON tinotify_real.dispositivos FOR SELECT TO tinotify_real_app USING (true);
CREATE POLICY app_insercion ON tinotify_real.dispositivos FOR INSERT TO tinotify_real_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_real.dispositivos FOR UPDATE TO tinotify_real_app USING (true) WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_real.dispositivos FOR DELETE TO tinotify_real_app USING (true);

-- Fallar ante ACL residuales o defaults ajenos en vez de repararlos concediendo o revocando a ciegas.
DO $auditoria$
DECLARE rol text; tabla regclass;
BEGIN
    IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r' AND c.relrowsecurity AND c.relforcerowsecurity) <> 7 THEN
        RAISE EXCEPTION 'Tablas del almacen real sin RLS forzado esperado';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tinotify_real_app'
        AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)) THEN
        RAISE EXCEPTION 'Atributos inesperados del rol de la aplicacion real';
    END IF;
    -- ACL exacta: en tablas, columnas y esquema solo aparecen el propietario y el rol de la aplicacion
    -- (el grantee 0 es PUBLIC, que tambien se rechaza) y nada es delegable.
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               CROSS JOIN LATERAL aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
               WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r'
                 AND (a.grantee NOT IN (c.relowner, 'tinotify_real_app'::regrole::oid) OR a.is_grantable))
       OR EXISTS (SELECT 1 FROM pg_attribute t JOIN pg_class c ON c.oid = t.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
               CROSS JOIN LATERAL aclexplode(t.attacl) a
               WHERE n.nspname = 'tinotify_real' AND t.attnum > 0 AND NOT t.attisdropped
                 AND (a.grantee <> 'tinotify_real_app'::regrole::oid OR a.is_grantable))
       OR EXISTS (SELECT 1 FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl, acldefault('n', n.nspowner))) a
               WHERE n.nspname = 'tinotify_real'
                 AND (a.grantee NOT IN (n.nspowner, 'tinotify_real_app'::regrole::oid) OR a.is_grantable
                      OR a.privilege_type <> 'USAGE') AND a.grantee <> n.nspowner) THEN
        RAISE EXCEPTION 'ACL inesperada en el almacen real; revisar defaults antes de reintentar';
    END IF;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        IF has_schema_privilege(rol, 'tinotify_real', 'USAGE,CREATE') THEN
            RAISE EXCEPTION 'Acceso inesperado al esquema real';
        END IF;
        FOR tabla IN SELECT c.oid::regclass FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r' LOOP
            IF has_table_privilege(rol, tabla, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
            OR has_any_column_privilege(rol, tabla, 'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'Permiso residual de cliente en el almacen real';
            END IF;
        END LOOP;
    END LOOP;
    IF has_schema_privilege('tinotify_real_app', 'tinotify_real', 'CREATE')
    OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname IN ('app','app_private','app_fixture','tinotify_sintetico')
                AND has_schema_privilege('tinotify_real_app', n.oid, 'USAGE,CREATE'))
    OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname IN ('public','auth','storage')
                AND has_schema_privilege('tinotify_real_app', n.oid, 'CREATE')) THEN
        RAISE EXCEPTION 'El rol de la aplicacion real tiene alcance excesivo';
    END IF;
END;
$auditoria$;
COMMIT;
