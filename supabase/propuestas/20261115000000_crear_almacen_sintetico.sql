-- Almacen PostgreSQL EXCLUSIVO del backend sintetico remoto. PROPUESTA: NO aplicada a Supabase.
-- Independiente de las migraciones 20261112050000..20261114020000: no usa ni modifica app, app_private, app_fixture,
-- auth ni sus roles. Solo datos ficticios; sin credenciales, sin SIGAC.
-- Sin IF NOT EXISTS: un objeto previo exige revision, no reutilizacion. Un solo bloque transaccional.
-- Ubicacion: supabase/propuestas (NO la recoge la CLI). Al autorizar su aplicacion: git mv a supabase/migrations/.
-- Reversion: supabase/propuestas/20261115000000_crear_almacen_sintetico_down.sql
-- No crea ningun rol LOGIN ni contraseña: el operador provisiona el login aparte (docs/despliegue-sintetico-render.md).
-- Revision 2: limites a prueba de concurrencia, contenido limitado a la gramatica del generador sintetico, privilegios
-- por columna y auditoria exacta de ACL. Revision 3: titulo del caso y textos de novedades cerrados a los valores
-- del generador/dominio, y los limites exigen READ COMMITTED (ver docs/despliegue-sintetico-render.md).
BEGIN;

DO $precondiciones$
BEGIN
    IF current_setting('server_version_num')::integer / 10000 < 15 THEN
        RAISE EXCEPTION 'Almacen sintetico revisado para PostgreSQL 15 o superior.';
    END IF;
    IF (SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname IN ('anon','authenticated','service_role')) <> 3 THEN
        RAISE EXCEPTION 'Se esperan los roles de cliente de Supabase (anon, authenticated, service_role).';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = CURRENT_USER AND (rolsuper OR rolcreaterole)) THEN
        RAISE EXCEPTION 'Se requiere una identidad con CREATEROLE; no se eleva automaticamente.';
    END IF;
END;
$precondiciones$;

CREATE SCHEMA tinotify_sintetico AUTHORIZATION CURRENT_USER;
CREATE ROLE tinotify_sintetico_app NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
-- NOINHERIT aqui no limita al login futuro: el operador lo crea con INHERIT y membresia explicita.
REVOKE ALL ON SCHEMA tinotify_sintetico FROM PUBLIC, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA tinotify_sintetico TO tinotify_sintetico_app;
COMMENT ON SCHEMA tinotify_sintetico IS 'Tinotify: datos FICTICIOS del backend sintetico. Nunca expuesto por la Data API.';

-- Marca de entorno: la aplicacion se niega a usar un esquema sin esta fila.
CREATE TABLE tinotify_sintetico.entorno (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    proposito text NOT NULL DEFAULT 'sintetico' CHECK (proposito = 'sintetico'),
    version_esquema smallint NOT NULL DEFAULT 1 CHECK (version_esquema = 1)
);
INSERT INTO tinotify_sintetico.entorno DEFAULT VALUES;

-- Los identificadores de caso viven en un espacio reservado y el titulo es EXACTAMENTE el del generador sintetico
-- (TITULO_OBSERVADO, el unico que escribe el adaptador): un UUID aleatorio (p. ej. de un caso real) o cualquier otro
-- titulo se rechazan. Los literales U&'...' evitan depender de la codificacion del cliente (\00e9 = e con tilde).
CREATE TABLE tinotify_sintetico.casos (
    id uuid PRIMARY KEY CHECK (id::text LIKE '00000000-0000-4000-8000-%'),
    titulo text NOT NULL CONSTRAINT titulo_del_generador CHECK (titulo = U&'Proceso sint\00e9tico observado'),
    generacion bigint NOT NULL DEFAULT 0 CHECK (generacion >= 0),
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    actualizado_en timestamptz NOT NULL DEFAULT clock_timestamp()
);
-- El contenido solo admite EXACTAMENTE la gramatica del generador sintetico: seis claves, frases fijas con un contador,
-- fecha ISO y ningun anexo. Una marca como «SINTETICO» no bastaria: los campos libres admitirian texto real.
-- Cada campo se envuelve en coalesce(...): una clave ausente o un null JSON darian NULL, y un CHECK con NULL pasa.
-- Un fixture sintetico distinto exige una migracion nueva (a proposito).
CREATE TABLE tinotify_sintetico.actuaciones (
    caso_id uuid NOT NULL REFERENCES tinotify_sintetico.casos(id) ON DELETE CASCADE,
    orden integer NOT NULL CHECK (orden BETWEEN 0 AND 199),
    huella text COLLATE "C" NOT NULL CHECK (huella ~ '^[0-9a-f]{64}$'),
    contenido jsonb NOT NULL CONSTRAINT contenido_sintetico CHECK (
        jsonb_typeof(contenido) = 'object'
        AND contenido ?& ARRAY['fecha','titulo','direccion','remitente','descripcion','anexos']
        AND contenido - 'fecha' - 'titulo' - 'direccion' - 'remitente' - 'descripcion' - 'anexos' = '{}'::jsonb
        AND coalesce(contenido->>'fecha' ~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$', false)
        AND coalesce(contenido->>'titulo' ~ '^TITULO SINTETICO [0-9]{1,3}$', false)
        AND coalesce(contenido->>'direccion' IN ('ESTUDIANTE-->ASESOR','ASESOR-->ESTUDIANTE'), false)
        AND coalesce(contenido->>'remitente' = 'REMITENTE SINTETICO', false)
        AND coalesce(contenido->>'descripcion' ~ '^Actuación sintética número [0-9]{1,3}\.$', false)
        AND coalesce(contenido->'anexos' = '[]'::jsonb, false)),
    PRIMARY KEY (caso_id, orden)
);
CREATE INDEX actuaciones_huella ON tinotify_sintetico.actuaciones (caso_id, huella);
CREATE TABLE tinotify_sintetico.novedades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    caso_id uuid NOT NULL REFERENCES tinotify_sintetico.casos(id) ON DELETE CASCADE,
    actuacion_huella text COLLATE "C" NOT NULL CHECK (actuacion_huella ~ '^[0-9a-f]{64}$'),
    generacion bigint NOT NULL CHECK (generacion > 0),
    tipo text NOT NULL CHECK (tipo IN ('primera_observacion','modificacion_confirmada','cambio_ambiguo')),
    prioridad text NOT NULL CHECK (prioridad IN ('alta','normal')),
    titulo text NOT NULL,
    mensaje text NOT NULL,
    -- Texto cerrado: solo los pares (tipo, titulo, mensaje) que produce tinotify.domain.notificaciones.crear_notificacion
    -- (el adaptador solo usa el primero con «disponible»; «importante» existe en el dominio y se admite). Nada libre.
    CONSTRAINT textos_del_dominio CHECK (
        (tipo = 'primera_observacion'
            AND titulo IN (U&'Nueva informaci\00f3n disponible', U&'Nueva informaci\00f3n importante')
            AND mensaje = U&'Hay informaci\00f3n observada por primera vez. Revisa la aplicaci\00f3n.')
        OR (tipo = 'modificacion_confirmada'
            AND titulo = U&'Informaci\00f3n actualizada'
            AND mensaje = U&'Se detect\00f3 una modificaci\00f3n. Revisa la aplicaci\00f3n.')
        OR (tipo = 'cambio_ambiguo'
            AND titulo = 'Cambios pendientes de clasificar'
            AND mensaje = U&'Se observaron diferencias que requieren revisi\00f3n.')),
    disposicion text NOT NULL DEFAULT 'pendiente' CHECK (disposicion IN ('pendiente','procesado')),
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    -- Idempotencia: una actuacion produce a lo sumo una novedad, aunque se reintente o haya dos escritores.
    UNIQUE (caso_id, actuacion_huella)
);
CREATE INDEX novedades_pendientes ON tinotify_sintetico.novedades (prioridad, creado_en, id)
    WHERE disposicion = 'pendiente';
CREATE TABLE tinotify_sintetico.monitor_estado (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    ciclos_correctos bigint NOT NULL DEFAULT 0 CHECK (ciclos_correctos >= 0),
    ciclos_fallidos bigint NOT NULL DEFAULT 0 CHECK (ciclos_fallidos >= 0),
    motivo text CHECK (motivo IS NULL OR char_length(motivo) <= 64),
    ultimo_ciclo jsonb CHECK (ultimo_ciclo IS NULL OR (jsonb_typeof(ultimo_ciclo) = 'object' AND pg_column_size(ultimo_ciclo) <= 1024)),
    actualizado_en timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO tinotify_sintetico.monitor_estado DEFAULT VALUES;

-- Crecimiento acotado dentro de la cuota gratuita: como maximo 10 casos y 200 novedades por caso (las actuaciones ya
-- estan acotadas por la clave primaria y orden < 200). Un conteo sin mas dejaria que dos transacciones abiertas a la vez
-- vieran el mismo total y ambas insertaran: el bloqueo asesor de transaccion las serializa (bajo READ COMMITTED, el
-- conteo posterior al bloqueo ve lo confirmado por la anterior). La clave 7402100002 es distinta de la del monitor.
CREATE FUNCTION tinotify_sintetico.limitar_casos() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
    -- Condicion del bloqueo: solo bajo READ COMMITTED el conteo posterior al bloqueo ve lo confirmado por la transaccion
    -- anterior. Bajo REPEATABLE READ/SERIALIZABLE la instantanea es anterior al bloqueo y la carrera volveria: se rechaza.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION USING ERRCODE = '25001', MESSAGE = 'El almacen sintetico requiere READ COMMITTED';
    END IF;
    PERFORM pg_advisory_xact_lock(7402100002);
    -- Un caso ya existente no cuenta como nuevo (ON CONFLICT DO NOTHING activa este trigger antes del conflicto).
    IF EXISTS (SELECT 1 FROM tinotify_sintetico.casos WHERE id = NEW.id) THEN
        RETURN NEW;
    END IF;
    IF (SELECT count(*) FROM tinotify_sintetico.casos) >= 10 THEN
        RAISE EXCEPTION USING ERRCODE = '54000', MESSAGE = 'Limite de casos sinteticos alcanzado';
    END IF;
    RETURN NEW;
END;
$fn$;
CREATE TRIGGER limitar_casos BEFORE INSERT ON tinotify_sintetico.casos
    FOR EACH ROW EXECUTE FUNCTION tinotify_sintetico.limitar_casos();
CREATE FUNCTION tinotify_sintetico.limitar_novedades() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION USING ERRCODE = '25001', MESSAGE = 'El almacen sintetico requiere READ COMMITTED';
    END IF;
    PERFORM pg_advisory_xact_lock(7402100002);
    IF EXISTS (SELECT 1 FROM tinotify_sintetico.novedades
               WHERE caso_id = NEW.caso_id AND actuacion_huella = NEW.actuacion_huella) THEN
        RETURN NEW;   -- ON CONFLICT DO NOTHING: no es una fila nueva
    END IF;
    IF (SELECT count(*) FROM tinotify_sintetico.novedades WHERE caso_id = NEW.caso_id) >= 200 THEN
        RAISE EXCEPTION USING ERRCODE = '54000', MESSAGE = 'Limite de novedades sinteticas alcanzado';
    END IF;
    RETURN NEW;
END;
$fn$;
CREATE TRIGGER limitar_novedades BEFORE INSERT ON tinotify_sintetico.novedades
    FOR EACH ROW EXECUTE FUNCTION tinotify_sintetico.limitar_novedades();
REVOKE ALL ON FUNCTION tinotify_sintetico.limitar_casos(), tinotify_sintetico.limitar_novedades()
    FROM PUBLIC, anon, authenticated, service_role;

-- Cierre por tabla: RLS forzado, sin acceso para clientes de la Data API.
DO $cierre$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['entorno','casos','actuaciones','novedades','monitor_estado'] LOOP
        EXECUTE format('ALTER TABLE tinotify_sintetico.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE tinotify_sintetico.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('REVOKE ALL ON tinotify_sintetico.%I FROM PUBLIC, anon, authenticated, service_role', t);
    END LOOP;
END;
$cierre$;
-- Privilegios minimos para el rol de la aplicacion; nunca TRUNCATE, DDL ni privilegios sobre otros esquemas.
-- UPDATE solo sobre las columnas que la aplicacion modifica (no id, creado_en ni la fila unica de estado).
GRANT SELECT ON tinotify_sintetico.entorno TO tinotify_sintetico_app;
GRANT SELECT, INSERT ON tinotify_sintetico.casos TO tinotify_sintetico_app;
GRANT UPDATE (titulo, generacion, actualizado_en) ON tinotify_sintetico.casos TO tinotify_sintetico_app;
GRANT SELECT ON tinotify_sintetico.monitor_estado TO tinotify_sintetico_app;
GRANT UPDATE (ciclos_correctos, ciclos_fallidos, motivo, ultimo_ciclo, actualizado_en)
    ON tinotify_sintetico.monitor_estado TO tinotify_sintetico_app;
GRANT SELECT, INSERT, DELETE ON tinotify_sintetico.actuaciones TO tinotify_sintetico_app;
GRANT SELECT, INSERT ON tinotify_sintetico.novedades TO tinotify_sintetico_app;
-- Una politica por orden y tabla, solo para el rol de la aplicacion (nada de FOR ALL): un privilegio futuro no se
-- activa por accidente.
CREATE POLICY app_lectura ON tinotify_sintetico.entorno FOR SELECT TO tinotify_sintetico_app USING (true);
CREATE POLICY app_lectura ON tinotify_sintetico.casos FOR SELECT TO tinotify_sintetico_app USING (true);
CREATE POLICY app_insercion ON tinotify_sintetico.casos FOR INSERT TO tinotify_sintetico_app WITH CHECK (true);
CREATE POLICY app_actualizacion ON tinotify_sintetico.casos FOR UPDATE TO tinotify_sintetico_app USING (true) WITH CHECK (true);
CREATE POLICY app_lectura ON tinotify_sintetico.monitor_estado FOR SELECT TO tinotify_sintetico_app USING (true);
CREATE POLICY app_actualizacion ON tinotify_sintetico.monitor_estado FOR UPDATE TO tinotify_sintetico_app USING (true) WITH CHECK (true);
CREATE POLICY app_lectura ON tinotify_sintetico.actuaciones FOR SELECT TO tinotify_sintetico_app USING (true);
CREATE POLICY app_insercion ON tinotify_sintetico.actuaciones FOR INSERT TO tinotify_sintetico_app WITH CHECK (true);
CREATE POLICY app_borrado ON tinotify_sintetico.actuaciones FOR DELETE TO tinotify_sintetico_app USING (true);
CREATE POLICY app_lectura ON tinotify_sintetico.novedades FOR SELECT TO tinotify_sintetico_app USING (true);
CREATE POLICY app_insercion ON tinotify_sintetico.novedades FOR INSERT TO tinotify_sintetico_app WITH CHECK (true);

-- Fallar ante ACL residuales o defaults ajenos en vez de repararlos concediendo o revocando a ciegas.
DO $auditoria$
DECLARE rol text; tabla regclass;
BEGIN
    IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'tinotify_sintetico' AND c.relkind = 'r' AND c.relrowsecurity AND c.relforcerowsecurity) <> 5 THEN
        RAISE EXCEPTION 'Tablas del almacen sintetico sin RLS forzado esperado';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tinotify_sintetico_app'
        AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)) THEN
        RAISE EXCEPTION 'Atributos inesperados del rol de la aplicacion sintetica';
    END IF;
    -- ACL exacta: en tablas, columnas, funciones y esquema solo aparecen el propietario y el rol de la aplicacion
    -- (el grantee 0 es PUBLIC, que tambien se rechaza) y nada es delegable.
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               CROSS JOIN LATERAL aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
               WHERE n.nspname = 'tinotify_sintetico' AND c.relkind = 'r'
                 AND (a.grantee NOT IN (c.relowner, 'tinotify_sintetico_app'::regrole::oid) OR a.is_grantable))
       OR EXISTS (SELECT 1 FROM pg_attribute t JOIN pg_class c ON c.oid = t.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
               CROSS JOIN LATERAL aclexplode(t.attacl) a
               WHERE n.nspname = 'tinotify_sintetico' AND t.attnum > 0 AND NOT t.attisdropped
                 AND (a.grantee <> 'tinotify_sintetico_app'::regrole::oid OR a.is_grantable))
       OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
               CROSS JOIN LATERAL aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
               WHERE n.nspname = 'tinotify_sintetico' AND a.grantee <> p.proowner)
       OR EXISTS (SELECT 1 FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl, acldefault('n', n.nspowner))) a
               WHERE n.nspname = 'tinotify_sintetico'
                 AND (a.grantee NOT IN (n.nspowner, 'tinotify_sintetico_app'::regrole::oid) OR a.is_grantable
                      OR a.privilege_type <> 'USAGE') AND a.grantee <> n.nspowner) THEN
        RAISE EXCEPTION 'ACL inesperada en el almacen sintetico; revisar defaults antes de reintentar';
    END IF;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        IF has_schema_privilege(rol, 'tinotify_sintetico', 'USAGE,CREATE') THEN
            RAISE EXCEPTION 'Acceso inesperado al esquema sintetico';
        END IF;
        FOR tabla IN SELECT c.oid::regclass FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'tinotify_sintetico' AND c.relkind = 'r' LOOP
            IF has_table_privilege(rol, tabla, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
            OR has_any_column_privilege(rol, tabla, 'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'Permiso residual de cliente en el almacen sintetico';
            END IF;
        END LOOP;
    END LOOP;
    IF has_schema_privilege('tinotify_sintetico_app', 'tinotify_sintetico', 'CREATE')
    OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname IN ('app','app_private','app_fixture')
                AND has_schema_privilege('tinotify_sintetico_app', n.oid, 'USAGE,CREATE'))
    OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname IN ('public','auth','storage')
                AND has_schema_privilege('tinotify_sintetico_app', n.oid, 'CREATE')) THEN
        RAISE EXCEPTION 'El rol de la aplicacion sintetica tiene alcance excesivo';
    END IF;
END;
$auditoria$;
COMMIT;
