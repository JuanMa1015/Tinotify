-- Solo catalogos y funciones de inspeccion de pg_catalog. Nunca ejecuta funciones app*.
-- CLI 3.1.0: db query --remote=<ref> --read-only --file <este archivo>.
-- SQL Editor: envolver en BEGIN TRANSACTION READ ONLY; ... ROLLBACK;
-- No acredita Exposed schemas, restricciones del proveedor ni identidad de db push.
WITH tablas(esquema,nombre) AS (VALUES
    ('app','estudiantes'),('app','estados_reconciliacion'),('app','expedientes'),
    ('app','actuaciones'),('app','eventos'),('app_private','accesos_sigac'),
    ('app_private','sincronizaciones'),('app_private','importaciones')
), roles_esperados(nombre,interno) AS (VALUES
    ('tinotify_api',false),('tinotify_sync',false),('tinotify_notifications',false),
    ('tinotify_guard_reader',true),('tinotify_state_writer',true)
), funciones_esperadas(firma,propietario,definer) AS (VALUES
    ('actor()','tinotify_guard_reader',true),
    ('capacidad(text)','tinotify_guard_reader',false),
    ('acceso(uuid,uuid,uuid)','tinotify_guard_reader',false),
    ('seguir(bytea,bytea,text)','tinotify_state_writer',true),
    ('reservar(uuid,uuid,uuid,uuid,uuid)','tinotify_state_writer',true),
    ('leer_caso(uuid,uuid,uuid)','tinotify_state_writer',true),
    ('confirmar(uuid,uuid,uuid,uuid,bigint,jsonb,jsonb,text)','tinotify_state_writer',true),
    ('exportar(bytea,uuid)','tinotify_state_writer',true),
    ('pendientes(uuid,integer)','tinotify_state_writer',true),
    ('procesar_aviso(uuid,uuid)','tinotify_state_writer',true)
), referencias AS (
    SELECT c.oid,n.nspname,c.relname FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE (n.nspname,c.relname) IN (('auth','users'),('supabase_migrations','schema_migrations'))
), esquemas AS (
    SELECT n.oid,n.nspname,n.nspowner,n.nspacl
    FROM pg_catalog.pg_namespace n WHERE n.nspname IN ('app','app_private')
), relaciones AS (
    SELECT c.*,n.nspname FROM pg_catalog.pg_class c
    JOIN esquemas n ON n.oid=c.relnamespace
), encontradas AS (
    SELECT t.*,c.oid,c.relowner,c.relrowsecurity,c.relforcerowsecurity,c.relkind
    FROM tablas t LEFT JOIN relaciones c ON (c.nspname,c.relname)=(t.esquema,t.nombre)
), funciones AS (
    SELECT p.*,p.proname||'('||pg_catalog.replace(pg_catalog.oidvectortypes(p.proargtypes),' ','')||')' AS firma
    FROM pg_catalog.pg_proc p JOIN esquemas n ON n.oid=p.pronamespace
    WHERE n.nspname='app_private'
), roles AS (
    SELECT e.*,r.oid,r.rolcanlogin,r.rolinherit,r.rolsuper,r.rolcreatedb,
           r.rolcreaterole,r.rolreplication,r.rolbypassrls
    FROM roles_esperados e LEFT JOIN pg_catalog.pg_roles r ON r.rolname=e.nombre
), clientes AS (
    SELECT oid,rolname FROM pg_catalog.pg_roles WHERE rolname IN
        ('anon','authenticated','service_role','tinotify_api','tinotify_sync','tinotify_notifications')
), defaults AS (
    SELECT CASE WHEN d.defaclnamespace=0 THEN '<global>' ELSE n.nspname END AS esquema,
        d.defaclobjtype::text AS tipo,
        CASE WHEN a.grantee=0 THEN 'PUBLIC'
             WHEN r.rolname IN ('postgres','anon','authenticated','service_role',
                'tinotify_api','tinotify_sync','tinotify_notifications') THEN r.rolname
             ELSE '<otro_rol>' END AS destinatario,
        a.privilege_type AS privilegio,a.is_grantable AS delegable,
        a.grantee<>d.defaclrole AND a.grantee<>0 AND NOT coalesce(r.rolname IN
            ('anon','authenticated','service_role','tinotify_api','tinotify_sync','tinotify_notifications'),false)
            AS no_cerrado_por_revokes
    FROM pg_catalog.pg_default_acl d
    LEFT JOIN pg_catalog.pg_namespace n ON n.oid=d.defaclnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) a
    LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee
    WHERE d.defaclrole=pg_catalog.to_regrole('postgres')
      AND (d.defaclnamespace=0 OR n.nspname IN ('app','app_private'))
      AND d.defaclobjtype IN ('r','S','f')
), acl_tablas AS (
    SELECT r.rolname AS rol,t.esquema,t.nombre,
        pg_catalog.has_table_privilege(r.oid,t.oid,
            CASE WHEN pg_catalog.current_setting('server_version_num')::integer>=170000
                THEN 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN'
                ELSE 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER' END) AS tabla,
        pg_catalog.has_any_column_privilege(r.oid,t.oid,'SELECT,INSERT,UPDATE,REFERENCES') AS columna
    FROM clientes r CROSS JOIN encontradas t WHERE t.oid IS NOT NULL AND t.relkind IN ('r','p')
), membresias AS (
    SELECT e.nombre AS rol,
        CASE WHEN m.rolname IN ('postgres','supabase_admin','anon','authenticated','service_role',
            'tinotify_api','tinotify_sync','tinotify_notifications','tinotify_guard_reader','tinotify_state_writer')
            THEN m.rolname ELSE '<otro_rol>' END AS miembro,
        am.admin_option AS admin,
        (pg_catalog.to_jsonb(am)->>'inherit_option')::boolean AS hereda,
        (pg_catalog.to_jsonb(am)->>'set_option')::boolean AS puede_asumir
    FROM roles e JOIN pg_catalog.pg_auth_members am ON am.roleid=e.oid
    JOIN pg_catalog.pg_roles m ON m.oid=am.member
), resumen AS (
    SELECT (SELECT pg_catalog.count(*) FROM esquemas) AS esquemas,
        (SELECT pg_catalog.count(*) FROM roles WHERE NOT interno AND oid IS NOT NULL) AS roles_4a,
        (SELECT pg_catalog.count(*) FROM roles WHERE interno AND oid IS NOT NULL) AS roles_nuevos,
        (SELECT pg_catalog.count(*) FROM encontradas WHERE oid IS NOT NULL AND relkind='r') AS tablas,
        (SELECT pg_catalog.count(*) FROM funciones) AS funciones,
        (SELECT pg_catalog.count(*) FROM relaciones c WHERE c.relkind<>'i' AND NOT EXISTS
            (SELECT 1 FROM tablas t WHERE (t.esquema,t.nombre)=(c.nspname,c.relname))) AS objetos_ajenos
)
SELECT pg_catalog.jsonb_build_object(
    'revision_informe',1,
    'limite','Inventario, no autorizacion de migracion ni validacion completa del DDL',
    'ejecucion',pg_catalog.jsonb_build_object(
        'rol',CASE WHEN CURRENT_USER IN ('postgres','supabase_read_only_user','cli_login_postgres')
            THEN CURRENT_USER ELSE '<otro_rol>' END,
        'sesion_es_rol_efectivo',CURRENT_USER=SESSION_USER,
        'transaction_read_only',pg_catalog.current_setting('transaction_read_only'),
        'row_security',pg_catalog.current_setting('row_security')),
    'servidor',pg_catalog.jsonb_build_object(
        'version',pg_catalog.current_setting('server_version'),
        'version_num',pg_catalog.current_setting('server_version_num')::integer,
        'major_17',pg_catalog.current_setting('server_version_num')::integer/10000=17,
        'block_size',pg_catalog.current_setting('block_size')::integer,
        'encoding',pg_catalog.current_setting('server_encoding'),
        'collation_c',EXISTS(SELECT 1 FROM pg_catalog.pg_collation WHERE collname='C' AND collnamespace='pg_catalog'::regnamespace),
        'gen_random_uuid_nativo',pg_catalog.to_regprocedure('pg_catalog.gen_random_uuid()') IS NOT NULL,
        'plpgsql',pg_catalog.to_regnamespace('pg_catalog') IS NOT NULL AND EXISTS
            (SELECT 1 FROM pg_catalog.pg_language WHERE lanname='plpgsql')),
    'operador_postgres',(
        SELECT pg_catalog.jsonb_build_object('existe',true,'superuser',r.rolsuper,'createrole',r.rolcreaterole,
            'crea_en_base',pg_catalog.has_database_privilege(r.oid,pg_catalog.current_database(),'CREATE'),
            'usa_plpgsql',pg_catalog.has_language_privilege(r.oid,'plpgsql','USAGE'),
            'usa_auth',pg_catalog.has_schema_privilege(r.oid,(SELECT oid FROM pg_catalog.pg_namespace WHERE nspname='auth'),'USAGE'),
            'referencia_auth_id',CASE WHEN (SELECT oid FROM referencias WHERE nspname='auth' AND relname='users') IS NOT NULL THEN
                pg_catalog.has_column_privilege(r.oid,(SELECT oid FROM referencias WHERE nspname='auth' AND relname='users'),'id','REFERENCES') ELSE false END,
            'nota','Permisos de postgres observables, no identidad acreditada de db push ni prueba de permisos futuros')
        FROM pg_catalog.pg_roles r WHERE r.rolname='postgres'),
    'auth_id_referenciable',EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_index i ON i.indrelid=a.attrelid
        WHERE a.attrelid=(SELECT oid FROM referencias WHERE nspname='auth' AND relname='users') AND a.attname='id'
          AND a.atttypid='pg_catalog.uuid'::regtype AND a.attnotnull AND NOT a.attisdropped
          AND i.indisunique AND i.indisvalid AND i.indimmediate AND i.indnkeyatts=1
          AND i.indkey[0]=a.attnum AND i.indpred IS NULL AND i.indexprs IS NULL),
    'catalogo',pg_catalog.to_jsonb(resumen),
    'roles_tinotify_no_previstos',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_roles r
        WHERE r.rolname LIKE 'tinotify!_%' ESCAPE '!' AND NOT EXISTS
            (SELECT 1 FROM roles_esperados e WHERE e.nombre=r.rolname)),
    'rutinas_en_app_no_previstas',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_proc p
        JOIN esquemas n ON n.oid=p.pronamespace WHERE n.nspname='app'),
    'esquemas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'nombre',nspname,'propietario_postgres',nspowner=pg_catalog.to_regrole('postgres'),
        'postgres_crea',pg_catalog.has_schema_privilege(pg_catalog.to_regrole('postgres'),oid,'CREATE'),
        'public_usage_o_create',EXISTS(SELECT 1 FROM pg_catalog.aclexplode(coalesce(nspacl,pg_catalog.acldefault('n',nspowner))) a
            WHERE a.grantee=0 AND a.privilege_type IN ('USAGE','CREATE')))
        ORDER BY nspname) FROM esquemas),'[]'::jsonb),
    'roles',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r)-'oid' ORDER BY nombre) FROM roles r),'[]'::jsonb),
    'membresias',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(m) ORDER BY rol,miembro) FROM membresias m),'[]'::jsonb),
    'clientes_pueden_asumir_propietarios',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'rol',c.rolname,'propietario',CASE WHEN r.rolname IN
            ('postgres','supabase_admin','tinotify_guard_reader','tinotify_state_writer') THEN r.rolname ELSE '<otro_rol>' END))
        FROM clientes c CROSS JOIN pg_catalog.pg_roles r
        WHERE (r.rolname IN ('postgres','supabase_admin','tinotify_guard_reader','tinotify_state_writer')
               OR r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb)
        AND pg_catalog.pg_has_role(c.oid,r.oid,'MEMBER') AND c.oid<>r.oid),'[]'::jsonb),
    'acceso_esquemas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'rol',c.rolname,'esquema',n.nspname,'usage',pg_catalog.has_schema_privilege(c.oid,n.oid,'USAGE'),
        'create',pg_catalog.has_schema_privilege(c.oid,n.oid,'CREATE')) ORDER BY c.rolname,n.nspname)
        FROM clientes c CROSS JOIN esquemas n),'[]'::jsonb),
    'tablas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',t.esquema,'nombre',t.nombre,'existe',t.oid IS NOT NULL,'tabla_ordinaria',t.relkind='r',
        'propietario_postgres',t.relowner=pg_catalog.to_regrole('postgres'),
        'rls',t.relrowsecurity,'force_rls',t.relforcerowsecurity,
        'constraints_no_validos',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_constraint k WHERE k.conrelid=t.oid AND NOT k.convalidated),
        'politicas',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_policy p WHERE p.polrelid=t.oid))
        ORDER BY t.esquema,t.nombre) FROM encontradas t),'[]'::jsonb),
    'indices',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'tabla',t.esquema||'.'||t.nombre,'valido',i.indisvalid,'listo',i.indisready,
        'unico',i.indisunique,'primario',i.indisprimary,
        'definicion_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_indexdef(i.indexrelid),'UTF8')),'hex')) ORDER BY t.esquema,t.nombre,i.indexrelid)
        FROM encontradas t JOIN pg_catalog.pg_index i ON i.indrelid=t.oid),'[]'::jsonb),
    'privilegios_directos_de_cliente',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(a))
        FROM acl_tablas a WHERE tabla OR columna),'[]'::jsonb),
    'acl_tablas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'tabla',t.esquema||'.'||t.nombre,
        'destinatario',CASE WHEN a.grantee=0 THEN 'PUBLIC' WHEN r.rolname IN
            ('anon','authenticated','service_role','tinotify_api','tinotify_sync','tinotify_notifications',
             'tinotify_guard_reader','tinotify_state_writer') THEN r.rolname ELSE '<otro_rol>' END,
        'privilegio',a.privilege_type,'delegable',a.is_grantable))
        FROM encontradas t JOIN pg_catalog.pg_class c ON c.oid=t.oid
        CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
        LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee WHERE a.grantee<>c.relowner),'[]'::jsonb),
    'constraints',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'tabla',t.esquema||'.'||t.nombre,'tipo',k.contype,'valido',k.convalidated,
        'diferible',k.condeferrable,'inicialmente_diferido',k.condeferred,
        'definicion_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_constraintdef(k.oid),'UTF8')),'hex')))
        FROM encontradas t JOIN pg_catalog.pg_constraint k ON k.conrelid=t.oid),'[]'::jsonb),
    'acl_columnas_no_propietario',(SELECT pg_catalog.count(*) FROM relaciones c JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
        CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) p
        WHERE a.attnum>0 AND NOT a.attisdropped AND p.grantee<>c.relowner),
    'acl_columnas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'tabla',t.esquema||'.'||t.nombre,
        'columna',CASE WHEN a.attname IN ('id','estudiante_id') THEN a.attname ELSE '<otra_columna>' END,
        'destinatario',CASE WHEN p.grantee=0 THEN 'PUBLIC' WHEN r.rolname IN
            ('anon','authenticated','service_role','tinotify_api','tinotify_sync','tinotify_notifications',
             'tinotify_guard_reader','tinotify_state_writer') THEN r.rolname ELSE '<otro_rol>' END,
        'privilegio',p.privilege_type,'delegable',p.is_grantable))
        FROM encontradas t JOIN pg_catalog.pg_class c ON c.oid=t.oid
        JOIN pg_catalog.pg_attribute a ON a.attrelid=t.oid
        CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) p
        LEFT JOIN pg_catalog.pg_roles r ON r.oid=p.grantee
        WHERE a.attnum>0 AND NOT a.attisdropped AND p.grantee<>c.relowner),'[]'::jsonb),
    'defaults_postgres',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d) ORDER BY esquema,tipo,destinatario,privilegio) FROM defaults d),'[]'::jsonb),
    'funciones',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'firma',e.firma,'existe',p.oid IS NOT NULL,
        'propietario_correcto',p.proowner=pg_catalog.to_regrole(e.propietario),
        'security_correcta',p.prosecdef=e.definer,
        'search_path_fijo','search_path=pg_catalog, pg_temp'=ANY(p.proconfig),
        'definicion_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_functiondef(p.oid),'UTF8')),'hex'),
        'public_execute',EXISTS(SELECT 1 FROM pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE a.grantee=0 AND a.privilege_type='EXECUTE')) ORDER BY e.firma)
        FROM funciones_esperadas e LEFT JOIN funciones p ON p.firma=e.firma),'[]'::jsonb),
    'funciones_no_previstas',(SELECT pg_catalog.count(*) FROM funciones p WHERE NOT EXISTS
        (SELECT 1 FROM funciones_esperadas e WHERE e.firma=p.firma)),
    'acl_funciones',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'firma',e.firma,'destinatario',CASE WHEN a.grantee=0 THEN 'PUBLIC' WHEN r.rolname IN
            ('anon','authenticated','service_role','tinotify_api','tinotify_sync','tinotify_notifications',
             'tinotify_guard_reader','tinotify_state_writer') THEN r.rolname ELSE '<otro_rol>' END,
        'privilegio',a.privilege_type,'delegable',a.is_grantable))
        FROM funciones_esperadas e JOIN funciones p ON p.firma=e.firma
        CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
        LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee WHERE a.grantee<>p.proowner),'[]'::jsonb),
    'funciones_acceso_efectivo',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'firma',e.firma,'rol',c.rolname)) FROM funciones_esperadas e
        JOIN funciones p ON p.firma=e.firma CROSS JOIN clientes c
        WHERE pg_catalog.has_function_privilege(c.oid,p.oid,'EXECUTE')),'[]'::jsonb),
    'politicas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'tabla',t.esquema||'.'||t.nombre,'comando',p.polcmd,'permisiva',p.polpermissive,
        'public',0=ANY(p.polroles),
        'rol_no_interno',EXISTS(SELECT 1 FROM pg_catalog.unnest(p.polroles) r(oid) WHERE NOT EXISTS
            (SELECT 1 FROM roles e WHERE e.interno AND e.oid=r.oid)),
        'using_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_expr(p.polqual,p.polrelid),'UTF8')),'hex'),
        'check_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid),'UTF8')),'hex')))
        FROM encontradas t JOIN pg_catalog.pg_policy p ON p.polrelid=t.oid),'[]'::jsonb),
    'plataforma',pg_catalog.jsonb_build_object(
        'event_triggers_habilitados',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_event_trigger WHERE evtenabled<>'D'),
        'ajustes_supautils',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_settings WHERE name LIKE 'supautils.%'),
        'nota','Sin leer configuraciones de extensiones, secretos ni definiciones de triggers ajenos'),
    'historial',pg_catalog.jsonb_build_object(
        'existe',(SELECT oid FROM referencias WHERE nspname='supabase_migrations' AND relname='schema_migrations') IS NOT NULL,
        'usage_disponible',coalesce(pg_catalog.has_schema_privilege(CURRENT_USER,
            (SELECT oid FROM pg_catalog.pg_namespace WHERE nspname='supabase_migrations'),'USAGE'),false),
        'select_disponible',CASE WHEN (SELECT oid FROM referencias WHERE nspname='supabase_migrations' AND relname='schema_migrations') IS NOT NULL
            THEN pg_catalog.has_table_privilege(CURRENT_USER,(SELECT oid FROM referencias WHERE nspname='supabase_migrations' AND relname='schema_migrations'),'SELECT') ELSE false END,
        'consulta','Ejecutar 4b3_historial.sql por separado solo si es accesible; no consulta statements ni name'),
    'data_api','Verificar Exposed schemas y Automatically expose new tables por separado en Dashboard; catalogos no acreditan la configuracion externa'
) AS preflight_4b3 FROM resumen;
