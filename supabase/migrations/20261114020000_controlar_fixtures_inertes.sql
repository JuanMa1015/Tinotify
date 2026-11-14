-- 4B.4-A PROPUESTA. No aplicada a Supabase. No administra auth.users.
-- Solo perfiles nuevos e inertes: sin sujeto Auth, activacion o comprobantes.
BEGIN;
DO $precondiciones$
BEGIN
    IF current_user<>'postgres' OR current_setting('server_version_num')::integer/10000<>17
       OR to_regprocedure('app_private.confirmar(uuid,uuid,uuid,uuid,bigint,jsonb,jsonb,text)') IS NULL THEN
        RAISE EXCEPTION 'Se requiere PG17, postgres y 4B.2-B; no reparar permisos automaticamente';
    END IF;
    IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE (n.nspname,c.relname) IN (('app','estudiantes'),('app','estados_reconciliacion'),
            ('app','expedientes'),('app','actuaciones'),('app','eventos'),('app_private','accesos_sigac'),
            ('app_private','sincronizaciones'),('app_private','importaciones'))
        AND c.relkind='r' AND c.relowner='postgres'::regrole AND c.relrowsecurity AND c.relforcerowsecurity)<>8 THEN
        RAISE EXCEPTION 'Base de persistencia sin propiedad y RLS esperados';
    END IF;
END;
$precondiciones$;
CREATE ROLE tinotify_fixture_control NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tinotify_fixture_recovery NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tinotify_fixture_owner NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE SCHEMA app_fixture AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA app_fixture FROM PUBLIC,anon,authenticated,service_role,tinotify_api,tinotify_sync,tinotify_notifications;
GRANT tinotify_fixture_owner TO CURRENT_USER WITH INHERIT TRUE, SET TRUE;
GRANT USAGE ON SCHEMA app,app_private,app_fixture TO tinotify_fixture_owner;
GRANT CREATE ON SCHEMA app_fixture TO tinotify_fixture_owner;

CREATE TABLE app_fixture.entorno (
    id boolean PRIMARY KEY CHECK(id),
    project_ref text NOT NULL CHECK(project_ref='urxfnmyuwbvnvrxkkppw'),
    habilitado boolean NOT NULL DEFAULT false
);
-- Habilitar requiere una accion humana independiente; ningun servicio la ofrece.
INSERT INTO app_fixture.entorno VALUES(true,'urxfnmyuwbvnvrxkkppw',false);
CREATE TABLE app_fixture.ensayos (
    id uuid PRIMARY KEY,
    operador_oid oid NOT NULL,
    operador_nombre name NOT NULL,
    clave uuid NOT NULL,
    token_hash bytea NOT NULL CHECK(octet_length(token_hash)=32),
    ttl integer NOT NULL CHECK(ttl BETWEEN 60 AND 900),
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    vence_en timestamptz NOT NULL,
    estado text NOT NULL CHECK(estado IN ('registrado','provisionado','cerrado','limpio')),
    cantidad_perfiles integer NOT NULL DEFAULT 0 CHECK(cantidad_perfiles BETWEEN 0 AND 2),
    casos_por_perfil integer NOT NULL DEFAULT 0 CHECK(casos_por_perfil BETWEEN 0 AND 2),
    politica text CHECK(politica ~ '^[0-9a-f]{64}$'),
    limpiado_en timestamptz,
    UNIQUE(operador_oid,clave),
    CHECK(vence_en>creado_en),
    CHECK((cantidad_perfiles=0 AND casos_por_perfil=0 AND politica IS NULL)
       OR (cantidad_perfiles>0 AND casos_por_perfil>0 AND politica IS NOT NULL)),
    CHECK((estado='limpio')=(limpiado_en IS NOT NULL))
);
CREATE TABLE app_fixture.perfiles (
    ensayo_id uuid NOT NULL REFERENCES app_fixture.ensayos(id),
    estudiante_id uuid PRIMARY KEY,
    estado_id uuid NOT NULL,
    casos uuid[] NOT NULL CHECK(cardinality(casos) BETWEEN 1 AND 2 AND array_position(casos,NULL) IS NULL),
    FOREIGN KEY(estudiante_id) REFERENCES app.estudiantes(id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(estudiante_id,estado_id) REFERENCES app.estados_reconciliacion(estudiante_id,id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX perfiles_por_ensayo ON app_fixture.perfiles(ensayo_id);
GRANT SELECT ON app_fixture.entorno,app_fixture.ensayos,app_fixture.perfiles TO tinotify_fixture_owner;
GRANT UPDATE(id) ON app_fixture.entorno TO tinotify_fixture_owner;
GRANT INSERT,UPDATE ON app_fixture.ensayos TO tinotify_fixture_owner;
GRANT INSERT,DELETE ON app_fixture.perfiles TO tinotify_fixture_owner;
DO $registro_rls$
DECLARE tabla text;
BEGIN
    FOREACH tabla IN ARRAY ARRAY['entorno','ensayos','perfiles'] LOOP
        EXECUTE format('ALTER TABLE app_fixture.%I ENABLE ROW LEVEL SECURITY',tabla);
        EXECUTE format('ALTER TABLE app_fixture.%I FORCE ROW LEVEL SECURITY',tabla);
        EXECUTE format('REVOKE ALL ON app_fixture.%I FROM PUBLIC,anon,authenticated,service_role,tinotify_api,tinotify_sync,tinotify_notifications,tinotify_fixture_control,tinotify_fixture_recovery',tabla);
        EXECUTE format('CREATE POLICY propietario_interno ON app_fixture.%I TO tinotify_fixture_owner USING (true) WITH CHECK (true)',tabla);
    END LOOP;
END;
$registro_rls$;
-- El propietario interno no es propietario de tablas, no tiene LOGIN/miembros
-- operativos y sus funciones tienen capacidades finitas. No acepta SQL del cliente.
GRANT SELECT ON app.estudiantes,app.estados_reconciliacion,app.expedientes,app.actuaciones,
    app.eventos,app_private.accesos_sigac,app_private.sincronizaciones,app_private.importaciones TO tinotify_fixture_owner;
GRANT INSERT,DELETE ON app.estudiantes,app.estados_reconciliacion,app.expedientes,app_private.accesos_sigac TO tinotify_fixture_owner;
GRANT UPDATE(id) ON app.estudiantes TO tinotify_fixture_owner;
CREATE POLICY fixture_lectura ON app.estudiantes FOR SELECT TO tinotify_fixture_owner
USING(EXISTS(SELECT 1 FROM app_fixture.perfiles f WHERE f.estudiante_id=id));
CREATE POLICY fixture_insercion ON app.estudiantes FOR INSERT TO tinotify_fixture_owner
WITH CHECK(auth_subject IS NULL AND estado='pendiente');
CREATE POLICY fixture_bloqueo ON app.estudiantes FOR UPDATE TO tinotify_fixture_owner
USING(EXISTS(SELECT 1 FROM app_fixture.perfiles f WHERE f.estudiante_id=id))
WITH CHECK(auth_subject IS NULL AND estado='pendiente');
CREATE POLICY fixture_borrado ON app.estudiantes FOR DELETE TO tinotify_fixture_owner
USING(EXISTS(SELECT 1 FROM app_fixture.perfiles f WHERE f.estudiante_id=id));
DO $datos_rls$
DECLARE tabla text;
BEGIN
    FOREACH tabla IN ARRAY ARRAY['app.estados_reconciliacion','app.expedientes','app.actuaciones','app.eventos',
        'app_private.accesos_sigac','app_private.sincronizaciones','app_private.importaciones'] LOOP
        EXECUTE format('CREATE POLICY fixture_lectura ON %s FOR SELECT TO tinotify_fixture_owner USING (EXISTS(SELECT 1 FROM app_fixture.perfiles f WHERE f.estudiante_id=%s.estudiante_id))',tabla,tabla);
    END LOOP;
    FOREACH tabla IN ARRAY ARRAY['app.estados_reconciliacion','app.expedientes','app_private.accesos_sigac'] LOOP
        EXECUTE format('CREATE POLICY fixture_insercion ON %s FOR INSERT TO tinotify_fixture_owner WITH CHECK (EXISTS(SELECT 1 FROM app_fixture.perfiles f WHERE f.estudiante_id=%s.estudiante_id))',tabla,tabla);
        EXECUTE format('CREATE POLICY fixture_borrado ON %s FOR DELETE TO tinotify_fixture_owner USING (EXISTS(SELECT 1 FROM app_fixture.perfiles f WHERE f.estudiante_id=%s.estudiante_id))',tabla,tabla);
    END LOOP;
END;
$datos_rls$;

CREATE FUNCTION app_fixture.capacidad(cap text) RETURNS void LANGUAGE plpgsql
SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
    IF current_user<>'tinotify_fixture_owner'
       OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND
            (rolsuper OR rolbypassrls OR rolcanlogin OR rolcreatedb OR rolcreaterole OR rolreplication OR rolinherit))
       OR cap NOT IN ('tinotify_fixture_control','tinotify_fixture_recovery') OR cap IS NULL
       OR NOT pg_has_role(session_user,cap,'USAGE')
       OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname=session_user AND
            (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication))
       OR EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.admin_option AND pg_has_role(session_user,m.member,'MEMBER'))
       OR has_database_privilege(session_user,current_database(),'CREATE')
       OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname IN ('app','app_private','app_fixture')
           AND has_schema_privilege(session_user,n.oid,'CREATE'))
       OR EXISTS(SELECT 1 FROM pg_roles r WHERE r.rolname<>cap AND r.oid<>(session_user::regrole)::oid
           AND pg_has_role(session_user,r.oid,'MEMBER'))
       OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname IN ('app','app_private','app_fixture') AND c.relkind='r'
             AND (has_table_privilege(session_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
               OR has_any_column_privilege(session_user,c.oid,'SELECT,INSERT,UPDATE,REFERENCES'))) THEN
        RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Capacidad de fixtures no autorizada';
    END IF;
    IF pg_has_role(session_user,'tinotify_fixture_control','USAGE') AND pg_has_role(session_user,'tinotify_fixture_recovery','USAGE') THEN
        RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Separar control y recuperacion';
    END IF;
END;
$fn$;
CREATE FUNCTION app_fixture.aislamiento() RETURNS void LANGUAGE plpgsql
SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
    IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION USING ERRCODE='25001',MESSAGE='Fixtures requiere READ COMMITTED';
    END IF;
END;
$fn$;
CREATE FUNCTION app_fixture.obtener(ensayo uuid,credencial text,bloquear boolean) RETURNS app_fixture.ensayos LANGUAGE plpgsql
SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e app_fixture.ensayos;
BEGIN
    IF bloquear THEN
        PERFORM app_fixture.aislamiento();
        SELECT * INTO e FROM app_fixture.ensayos WHERE id=ensayo FOR UPDATE;
    ELSE SELECT * INTO e FROM app_fixture.ensayos WHERE id=ensayo; END IF;
    IF e.id IS NULL OR e.operador_oid<>(session_user::regrole)::oid OR e.operador_nombre<>session_user
       OR credencial IS NULL OR e.token_hash IS DISTINCT FROM sha256(convert_to(credencial,'UTF8')) THEN
        RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Ensayo no autorizado';
    END IF;
    RETURN e;
END;
$fn$;
CREATE FUNCTION app_fixture.resumen(ensayo uuid) RETURNS jsonb LANGUAGE sql
SET search_path=pg_catalog,pg_temp AS $fn$
    SELECT jsonb_build_object('id',e.id,'estado',e.estado,'vence_en',e.vence_en,
        'perfiles_restantes',(SELECT count(*) FROM app_fixture.perfiles f WHERE f.ensayo_id=e.id),
        'limpiado_en',e.limpiado_en) FROM app_fixture.ensayos e WHERE e.id=ensayo
$fn$;
CREATE FUNCTION app_fixture.registrar(clave uuid,credencial text,segundos integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e app_fixture.ensayos; config app_fixture.entorno; ahora timestamptz:=clock_timestamp();
BEGIN
    PERFORM app_fixture.capacidad('tinotify_fixture_control');
    PERFORM app_fixture.aislamiento();
    IF clave IS NULL OR credencial IS NULL OR credencial !~ '^[0-9a-f]{64}$' OR segundos IS NULL OR segundos NOT BETWEEN 60 AND 900 THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Parametros de registro no validos';
    END IF;
    SELECT * INTO STRICT config FROM app_fixture.entorno WHERE id FOR UPDATE;
    SELECT * INTO e FROM app_fixture.ensayos WHERE operador_oid=(session_user::regrole)::oid AND ensayos.clave=registrar.clave FOR UPDATE;
    IF FOUND THEN
        e:=app_fixture.obtener(e.id,credencial,true);
        IF e.ttl<>segundos THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Solicitud distinta para la misma clave'; END IF;
        RETURN app_fixture.resumen(e.id);
    END IF;
    IF NOT config.habilitado OR config.project_ref<>'urxfnmyuwbvnvrxkkppw' THEN
        RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Fixtures Development deshabilitados';
    END IF;
    IF (SELECT count(*) FROM app_fixture.ensayos)>=1000
       OR (SELECT count(*) FROM app_fixture.ensayos WHERE estado<>'limpio')>=8
       OR (SELECT count(*) FROM app_fixture.ensayos WHERE estado<>'limpio' AND operador_oid=(session_user::regrole)::oid)>=2 THEN
        RAISE EXCEPTION USING ERRCODE='54000',MESSAGE='Cuota de ensayos alcanzada';
    END IF;
    INSERT INTO app_fixture.ensayos(id,operador_oid,operador_nombre,clave,token_hash,ttl,creado_en,vence_en,estado)
    VALUES(gen_random_uuid(),(session_user::regrole)::oid,session_user,clave,sha256(convert_to(credencial,'UTF8')),segundos,
        ahora,ahora+make_interval(secs=>segundos),'registrado') RETURNING * INTO e;
    RETURN app_fixture.resumen(e.id);
END;
$fn$;
CREATE FUNCTION app_fixture.provisionar(ensayo uuid,credencial text,perfiles integer,casos integer,politica text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e app_fixture.ensayos; estudiante uuid; cabecera uuid; expedientes uuid[]; indice integer; k integer;
BEGIN
    PERFORM app_fixture.capacidad('tinotify_fixture_control');
    e:=app_fixture.obtener(ensayo,credencial,true);
    IF perfiles IS NULL OR casos IS NULL OR perfiles NOT BETWEEN 1 AND 2 OR casos NOT BETWEEN 1 AND 2
       OR politica IS NULL OR politica !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Cuota o politica no valida';
    END IF;
    IF e.estado='provisionado' THEN
        IF ROW(e.cantidad_perfiles,e.casos_por_perfil,e.politica) IS DISTINCT FROM ROW(perfiles,casos,politica) THEN
            RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Provision repetida con parametros distintos';
        END IF;
        RETURN app_fixture.resumen(e.id);
    END IF;
    IF e.estado<>'registrado' OR e.vence_en<=clock_timestamp()
       OR NOT (SELECT habilitado FROM app_fixture.entorno WHERE id) THEN
        RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Ensayo no provisionable';
    END IF;
    FOR indice IN 1..perfiles LOOP
        estudiante:=gen_random_uuid(); cabecera:=gen_random_uuid();
        SELECT array_agg(gen_random_uuid()) INTO expedientes FROM generate_series(1,casos);
        -- Nunca ON CONFLICT: una colision revierte, no adopta un recurso previo.
        INSERT INTO app.estudiantes(id,auth_subject,estado) VALUES(estudiante,NULL,'pendiente');
        INSERT INTO app_fixture.perfiles VALUES(e.id,estudiante,cabecera,expedientes);
        INSERT INTO app.estados_reconciliacion
            (estudiante_id,id,instancia_utf8,epoca,situacion,schema_version,state_revision,fingerprint_version,trust_policy,migrated_from_v1)
        VALUES(estudiante,cabecera,convert_to('TINOTIFY_FIXTURE_'||e.id,'UTF8'),1,'activo',2,2,1,politica,false);
        FOR k IN 1..casos LOOP
            INSERT INTO app.expedientes(estudiante_id,estado_id,id,clave_caso_utf8)
            VALUES(estudiante,cabecera,expedientes[k],convert_to('CASO_SINTETICO_'||k,'UTF8'));
            INSERT INTO app_private.accesos_sigac(estudiante_id,estado_id,expediente_id) VALUES(estudiante,cabecera,expedientes[k]);
        END LOOP;
    END LOOP;
    UPDATE app_fixture.ensayos SET estado='provisionado',cantidad_perfiles=perfiles,casos_por_perfil=casos,politica=provisionar.politica WHERE id=e.id;
    RETURN app_fixture.resumen(e.id);
END;
$fn$;
CREATE FUNCTION app_fixture.proteger_perfil() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
    IF EXISTS(SELECT 1 FROM app_fixture.perfiles WHERE estudiante_id=OLD.id)
       AND (NEW.id IS DISTINCT FROM OLD.id OR NEW.auth_subject IS NOT NULL OR NEW.estado IS DISTINCT FROM 'pendiente') THEN
        RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Vinculo Auth y activacion de fixtures bloqueados';
    END IF;
    RETURN NEW;
END;
$fn$;
CREATE TRIGGER fixture_perfil_inerte BEFORE UPDATE OF id,auth_subject,estado ON app.estudiantes
FOR EACH ROW EXECUTE FUNCTION app_fixture.proteger_perfil();

CREATE FUNCTION app_fixture.depurar(ensayo uuid) RETURNS jsonb LANGUAGE plpgsql
SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e app_fixture.ensayos; f app_fixture.perfiles; p app.estudiantes; total integer;
BEGIN
    SELECT * INTO STRICT e FROM app_fixture.ensayos WHERE id=ensayo FOR UPDATE;
    IF e.estado='limpio' THEN
        IF EXISTS(SELECT 1 FROM app_fixture.perfiles WHERE ensayo_id=e.id) THEN
            RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Recibo de limpieza inconsistente';
        END IF;
        RETURN app_fixture.resumen(e.id);
    END IF;
    IF e.estado<>'cerrado' THEN RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Cerrar antes de limpiar'; END IF;
    IF (SELECT count(*) FROM app_fixture.perfiles WHERE ensayo_id=e.id)<>e.cantidad_perfiles THEN
        RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Pertenencia de fixtures inconsistente';
    END IF;
    FOR f IN SELECT * FROM app_fixture.perfiles WHERE ensayo_id=e.id ORDER BY estudiante_id LOOP
        SELECT * INTO STRICT p FROM app.estudiantes WHERE id=f.estudiante_id FOR UPDATE;
        IF p.auth_subject IS NOT NULL OR p.estado<>'pendiente'
           OR (SELECT count(*) FROM app.estados_reconciliacion WHERE estudiante_id=p.id)<>1
           OR NOT EXISTS(SELECT 1 FROM app.estados_reconciliacion WHERE estudiante_id=p.id AND id=f.estado_id
               AND instancia_utf8=convert_to('TINOTIFY_FIXTURE_'||e.id,'UTF8') AND trust_policy=e.politica
               AND epoca=1 AND situacion='activo' AND NOT migrated_from_v1)
           OR (SELECT count(*) FROM app.expedientes WHERE estudiante_id=p.id)<>e.casos_por_perfil
           OR EXISTS(SELECT 1 FROM app.expedientes WHERE estudiante_id=p.id AND
               (estado_id<>f.estado_id OR NOT(id=ANY(f.casos)) OR incluido_en_estado OR generacion<>0 OR fencing<>0
                OR clave_caso_utf8<>convert_to('CASO_SINTETICO_'||array_position(f.casos,id),'UTF8')))
           OR (SELECT count(*) FROM app_private.accesos_sigac WHERE estudiante_id=p.id)<>e.casos_por_perfil
           OR EXISTS(SELECT 1 FROM app_private.accesos_sigac WHERE estudiante_id=p.id AND
               (estado<>'no_verificado' OR fuente<>'ninguna' OR session_epoch<>0 OR access_epoch<>0
                OR session_binding_id IS NOT NULL OR comprobante_ref IS NOT NULL OR comprobado_en IS NOT NULL OR valido_hasta IS NOT NULL))
           OR EXISTS(SELECT 1 FROM app.actuaciones WHERE estudiante_id=p.id)
           OR EXISTS(SELECT 1 FROM app.eventos WHERE estudiante_id=p.id)
           OR EXISTS(SELECT 1 FROM app_private.sincronizaciones WHERE estudiante_id=p.id)
           OR EXISTS(SELECT 1 FROM app_private.importaciones WHERE estudiante_id=p.id) THEN
            RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Fixture alterado o con datos no permitidos; limpieza detenida';
        END IF;
    END LOOP;
    -- Listas cerradas y pertenencias del servidor, nunca IDs de recursos del cliente.
    DELETE FROM app_private.accesos_sigac WHERE estudiante_id IN (SELECT estudiante_id FROM app_fixture.perfiles WHERE ensayo_id=e.id);
    DELETE FROM app.expedientes WHERE estudiante_id IN (SELECT estudiante_id FROM app_fixture.perfiles WHERE ensayo_id=e.id);
    DELETE FROM app.estados_reconciliacion WHERE estudiante_id IN (SELECT estudiante_id FROM app_fixture.perfiles WHERE ensayo_id=e.id);
    DELETE FROM app.estudiantes WHERE id IN (SELECT estudiante_id FROM app_fixture.perfiles WHERE ensayo_id=e.id);
    GET DIAGNOSTICS total=ROW_COUNT;
    IF total<>e.cantidad_perfiles THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Limpieza incompleta'; END IF;
    IF EXISTS(SELECT 1 FROM app.estudiantes WHERE id IN (SELECT estudiante_id FROM app_fixture.perfiles WHERE ensayo_id=e.id)) THEN
        RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Residuos del ensayo';
    END IF;
    DELETE FROM app_fixture.perfiles WHERE ensayo_id=e.id;
    UPDATE app_fixture.ensayos SET estado='limpio',limpiado_en=clock_timestamp() WHERE id=e.id;
    RETURN app_fixture.resumen(e.id);
END;
$fn$;
CREATE FUNCTION app_fixture.cerrar(ensayo uuid,credencial text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e app_fixture.ensayos;
BEGIN
    PERFORM app_fixture.capacidad('tinotify_fixture_control'); e:=app_fixture.obtener(ensayo,credencial,true);
    UPDATE app_fixture.ensayos SET estado='cerrado' WHERE id=e.id AND estado IN ('registrado','provisionado');
    RETURN app_fixture.resumen(e.id);
END;
$fn$;
CREATE FUNCTION app_fixture.limpiar(ensayo uuid,credencial text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
    PERFORM app_fixture.capacidad('tinotify_fixture_control'); PERFORM app_fixture.obtener(ensayo,credencial,true);
    RETURN app_fixture.depurar(ensayo);
END;
$fn$;
CREATE FUNCTION app_fixture.consultar(ensayo uuid,credencial text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
    PERFORM app_fixture.capacidad('tinotify_fixture_control'); PERFORM app_fixture.obtener(ensayo,credencial,false);
    RETURN app_fixture.resumen(ensayo);
END;
$fn$;
CREATE FUNCTION app_fixture.recuperar_expirado(ensayo uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e app_fixture.ensayos;
BEGIN
    PERFORM app_fixture.capacidad('tinotify_fixture_recovery'); PERFORM app_fixture.aislamiento();
    SELECT * INTO e FROM app_fixture.ensayos WHERE id=ensayo FOR UPDATE;
    IF e.id IS NULL OR e.vence_en>clock_timestamp() THEN
        RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Ensayo no recuperable';
    END IF;
    UPDATE app_fixture.ensayos SET estado='cerrado' WHERE id=e.id AND estado IN ('registrado','provisionado');
    RETURN app_fixture.depurar(e.id);
END;
$fn$;

-- Propiedad y ACL explicitas, incluidos helpers y trigger. Fallar ante defaults
-- inesperados en vez de conceder permisos para hacer funcionar una conexion.
DO $cierre$
DECLARE funcion record; tabla regclass; rol text;
BEGIN
    FOR funcion IN SELECT p.oid::regprocedure AS firma FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='app_fixture' LOOP
        EXECUTE format('ALTER FUNCTION %s OWNER TO tinotify_fixture_owner',funcion.firma);
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,tinotify_api,tinotify_sync,tinotify_notifications,tinotify_fixture_control,tinotify_fixture_recovery',funcion.firma);
    END LOOP;
    FOREACH tabla IN ARRAY ARRAY['app_fixture.entorno'::regclass,'app_fixture.ensayos'::regclass,'app_fixture.perfiles'::regclass] LOOP
        IF EXISTS(SELECT 1 FROM pg_class c CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
            WHERE c.oid=tabla AND a.grantee<>c.relowner AND
                (a.grantee<>'tinotify_fixture_owner'::regrole OR a.is_grantable)) THEN
            RAISE EXCEPTION 'ACL inesperada en registro de fixtures';
        END IF;
    END LOOP;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role','tinotify_api','tinotify_sync','tinotify_notifications','tinotify_fixture_control','tinotify_fixture_recovery'] LOOP
        IF pg_has_role(rol,'tinotify_fixture_owner','MEMBER') THEN RAISE EXCEPTION 'Membresia de propietario no permitida'; END IF;
    END LOOP;
END;
$cierre$;
GRANT USAGE ON SCHEMA app_fixture TO tinotify_fixture_control,tinotify_fixture_recovery;
GRANT EXECUTE ON FUNCTION app_fixture.registrar(uuid,text,integer),app_fixture.provisionar(uuid,text,integer,integer,text),
    app_fixture.cerrar(uuid,text),app_fixture.limpiar(uuid,text),app_fixture.consultar(uuid,text) TO tinotify_fixture_control;
GRANT EXECUTE ON FUNCTION app_fixture.recuperar_expirado(uuid) TO tinotify_fixture_recovery;
REVOKE CREATE ON SCHEMA app_fixture FROM tinotify_fixture_owner;
REVOKE tinotify_fixture_owner FROM CURRENT_USER;
DO $auditoria$
DECLARE tabla regclass; rol text;
BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='app_fixture' AND nspowner='postgres'::regrole) THEN
        RAISE EXCEPTION 'Propietario del esquema fixture incompatible';
    END IF;
    IF (SELECT count(*) FROM pg_roles WHERE rolname IN
        ('tinotify_fixture_control','tinotify_fixture_recovery','tinotify_fixture_owner')
        AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb
        AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)<>3 THEN
        RAISE EXCEPTION 'Atributos de roles de fixtures incompatibles';
    END IF;
    IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='app_fixture' AND c.relkind='r' AND c.relrowsecurity AND c.relforcerowsecurity
        AND c.relowner='postgres'::regrole)<>3 THEN RAISE EXCEPTION 'Registro sin cierre RLS'; END IF;
    IF (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='app_fixture')<>12
       OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='app_fixture'
           AND (p.proowner<>'tinotify_fixture_owner'::regrole OR NOT coalesce('search_path=pg_catalog, pg_temp'=ANY(p.proconfig),false)
             OR p.prosecdef<>(p.proname IN ('registrar','provisionar','proteger_perfil','cerrar','limpiar','consultar','recuperar_expirado')))) THEN
        RAISE EXCEPTION 'Propiedad o contexto inesperado de funciones de fixtures';
    END IF;
    IF EXISTS(SELECT 1 FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a
        LEFT JOIN pg_roles r ON r.oid=a.grantee WHERE n.nspname='app_fixture' AND a.grantee<>n.nspowner AND
        NOT coalesce(a.privilege_type='USAGE' AND NOT a.is_grantable AND
            r.rolname IN ('tinotify_fixture_owner','tinotify_fixture_control','tinotify_fixture_recovery'),false)) THEN
        RAISE EXCEPTION 'ACL de esquema fixture inesperada';
    END IF;
    IF EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
        LEFT JOIN pg_roles r ON r.oid=a.grantee WHERE n.nspname='app_fixture' AND a.grantee<>p.proowner
        AND NOT coalesce(a.privilege_type='EXECUTE' AND NOT a.is_grantable AND
            ((p.proname IN ('registrar','provisionar','cerrar','limpiar','consultar') AND r.rolname='tinotify_fixture_control')
             OR (p.proname='recuperar_expirado' AND r.rolname='tinotify_fixture_recovery')),false)) THEN
        RAISE EXCEPTION 'ACL inesperada de funcion de fixtures';
    END IF;
    FOREACH tabla IN ARRAY ARRAY['app_fixture.entorno'::regclass,'app_fixture.ensayos'::regclass,'app_fixture.perfiles'::regclass] LOOP
        IF EXISTS(SELECT 1 FROM pg_attribute c CROSS JOIN LATERAL aclexplode(c.attacl) a
            WHERE c.attrelid=tabla AND c.attnum>0 AND NOT c.attisdropped AND
            NOT (tabla='app_fixture.entorno'::regclass AND c.attname='id' AND
                 a.grantee='tinotify_fixture_owner'::regrole AND a.privilege_type='UPDATE' AND NOT a.is_grantable)) THEN
            RAISE EXCEPTION 'ACL residual de columna en fixtures';
        END IF;
        FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role','tinotify_api','tinotify_sync','tinotify_notifications','tinotify_fixture_control','tinotify_fixture_recovery'] LOOP
            IF has_table_privilege(rol,tabla,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
               OR has_any_column_privilege(rol,tabla,'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'Permiso efectivo directo de fixture no autorizado';
            END IF;
        END LOOP;
    END LOOP;
END;
$auditoria$;
COMMIT;
