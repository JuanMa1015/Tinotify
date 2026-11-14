-- Una sentencia de catalogos. No ejecuta funciones de negocio ni lee Auth.
-- Ejecutar solo con autorizacion separada, dentro de una transaccion READ ONLY.
-- El historial se lee aparte con 4b3_historial.sql si esta accesible y sin RLS.
WITH espacios AS (
    SELECT oid,nspname,nspowner FROM pg_catalog.pg_namespace
    WHERE nspname IN ('app','app_private','app_fixture')
), relaciones AS (
    SELECT c.*,n.nspname FROM pg_catalog.pg_class c JOIN espacios n ON n.oid=c.relnamespace
), operador AS (
    SELECT oid,rolsuper,rolcreaterole FROM pg_catalog.pg_roles WHERE rolname='postgres'
), historial AS (
    SELECT c.*,n.oid AS esquema_oid FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='supabase_migrations' AND c.relname='schema_migrations'
), auth_id AS (
    SELECT a.* FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='auth' AND c.relname='users' AND a.attname='id' AND NOT a.attisdropped
)
SELECT pg_catalog.jsonb_build_object(
    'formato','tinotify_precondiciones_4b4b_v1',
    'lectura',pg_catalog.jsonb_build_object(
        'read_only',pg_catalog.current_setting('transaction_read_only')='on',
        'row_security',pg_catalog.current_setting('row_security')='on',
        'sin_cambio_identidad',CURRENT_USER=SESSION_USER),
    'pg17',pg_catalog.current_setting('server_version_num')::integer/10000=17,
    'colisiones',pg_catalog.jsonb_build_object(
        'esquema_fixture',(SELECT pg_catalog.count(*) FROM espacios WHERE nspname='app_fixture'),
        'roles_fixture',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_roles
            WHERE rolname IN ('tinotify_fixture_owner','tinotify_fixture_control','tinotify_fixture_recovery')),
        'roles_tinotify_extra',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_roles
            WHERE rolname LIKE 'tinotify!_%' ESCAPE '!' AND rolname NOT IN
            ('tinotify_api','tinotify_sync','tinotify_notifications','tinotify_guard_reader','tinotify_state_writer')),
        'politicas_reservadas',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_policy p
            JOIN relaciones c ON c.oid=p.polrelid WHERE p.polname IN
            ('fixture_lectura','fixture_insercion','fixture_bloqueo','fixture_borrado')),
        'trigger_reservado',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_trigger g
            JOIN relaciones c ON c.oid=g.tgrelid
            WHERE c.nspname='app' AND c.relname='estudiantes' AND g.tgname='fixture_perfil_inerte'),
        'rutinas_fixture',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_proc p
            JOIN espacios n ON n.oid=p.pronamespace WHERE n.nspname='app_fixture')),
    'ddl_observable',pg_catalog.jsonb_build_object(
        'postgres_existe',EXISTS(SELECT 1 FROM operador),
        'createrole',coalesce((SELECT rolcreaterole OR rolsuper FROM operador),false),
        'create_database',coalesce((SELECT pg_catalog.has_database_privilege(oid,pg_catalog.current_database(),'CREATE') FROM operador),false),
        'esquemas_propios',(SELECT pg_catalog.count(*) FROM espacios WHERE nspname IN ('app','app_private')
            AND nspowner=(SELECT oid FROM operador))=2,
        'tablas_propias',(SELECT pg_catalog.count(*) FROM relaciones WHERE relkind='r'
            AND relowner=(SELECT oid FROM operador))=8),
    'dependencias',pg_catalog.jsonb_build_object(
        'plpgsql',EXISTS(SELECT 1 FROM pg_catalog.pg_language WHERE lanname='plpgsql' AND lanpltrusted),
        'uuid_nativo',pg_catalog.to_regprocedure('pg_catalog.gen_random_uuid()') IS NOT NULL,
        'sha256_nativo',pg_catalog.to_regprocedure('pg_catalog.sha256(bytea)') IS NOT NULL,
        'auth_id_uuid',EXISTS(SELECT 1 FROM auth_id WHERE atttypid='pg_catalog.uuid'::regtype AND attnotnull),
        'objetos_controlados_extension',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_depend d
            WHERE d.deptype='e' AND ((d.classid='pg_catalog.pg_class'::regclass AND d.objid IN (SELECT oid FROM relaciones))
                OR (d.classid='pg_catalog.pg_proc'::regclass AND d.objid IN
                    (SELECT p.oid FROM pg_catalog.pg_proc p JOIN espacios n ON n.oid=p.pronamespace))))),
    'historial',pg_catalog.jsonb_build_object(
        'existe',EXISTS(SELECT 1 FROM historial WHERE relkind='r'),
        'sin_rls',coalesce((SELECT NOT relrowsecurity AND NOT relforcerowsecurity FROM historial),false),
        'usage',coalesce((SELECT pg_catalog.has_schema_privilege(CURRENT_USER,esquema_oid,'USAGE') FROM historial),false),
        'select_version',coalesce((SELECT pg_catalog.has_column_privilege(CURRENT_USER,h.oid,a.attnum,'SELECT')
            FROM historial h JOIN pg_catalog.pg_attribute a ON a.attrelid=h.oid
            WHERE a.attname='version' AND NOT a.attisdropped),false)),
    'no_verificable',pg_catalog.jsonb_build_object(
        'identidad_futura_cli',true,'restricciones_proveedor_ddl',true,
        'data_api',true,'proyecto_endpoint_tls',true)
) AS preflight_4b4b;
