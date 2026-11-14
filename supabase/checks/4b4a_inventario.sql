-- Inventario v1: solo catalogos, sin filas ni funciones de negocio.
-- Las identidades desconocidas se representan con hashes y se deben revisar.
-- JSON ordenado por claves estables; nunca OID como identidad entre servidores.
WITH objetivos(esquema,nombre,columnas) AS (VALUES
    ('app','estudiantes',ARRAY['id','auth_subject','estado','creado_en']::text[]),
    ('app','estados_reconciliacion',ARRAY['estudiante_id','id','epoca','situacion','schema_version','state_revision','fingerprint_version','trust_policy','creado_en']::text[]),
    ('app','expedientes',ARRAY['estudiante_id','estado_id','id','incluido_en_estado','generacion','fencing']::text[]),
    ('app','actuaciones',ARRAY['estudiante_id','estado_id','expediente_id','local_id','orden_registro','version_hash','status','source_id','contrato_version_decimal','contrato_revision']::text[]),
    ('app_private','accesos_sigac',ARRAY['estudiante_id','estado_id','expediente_id','estado','fuente','session_binding_id','session_epoch','access_epoch','comprobado_en','valido_hasta','comprobante_ref']::text[]),
    ('app_private','sincronizaciones',ARRAY['estudiante_id','estado_id','expediente_id','id','idempotency_key','modo','estado','generacion_base','generacion_confirmada','access_epoch','session_epoch','fencing','worker_id','lease_token','lease_hasta','creado_en','terminado_en']::text[]),
    ('app','eventos',ARRAY['estudiante_id','estado_id','expediente_id','id','sincronizacion_id','ordinal','local_id','generacion_resultado','tipo','prioridad','disposicion','creado_en']::text[]),
    ('app_private','importaciones',ARRAY['estudiante_id','id','idempotency_key','estado_id','source_bytes','estado','casos','registros','creado_en']::text[]),
    ('app_fixture','entorno',ARRAY['id','project_ref','habilitado']::text[]),
    ('app_fixture','ensayos',ARRAY['id','operador_oid','operador_nombre','clave','token_hash','ttl','creado_en','vence_en','estado','cantidad_perfiles','casos_por_perfil','politica','limpiado_en']::text[]),
    ('app_fixture','perfiles',ARRAY['ensayo_id','estudiante_id','estado_id','casos']::text[])
), firmas(esquema,firma) AS (VALUES
    ('app_private','actor()'),
    ('app_private','capacidad(text)'),
    ('app_private','acceso(uuid,uuid,uuid)'),
    ('app_private','seguir(bytea,bytea,text)'),
    ('app_private','reservar(uuid,uuid,uuid,uuid,uuid)'),
    ('app_private','leer_caso(uuid,uuid,uuid)'),
    ('app_private','confirmar(uuid,uuid,uuid,uuid,bigint,jsonb,jsonb,text)'),
    ('app_private','exportar(bytea,uuid)'),
    ('app_private','pendientes(uuid,integer)'),
    ('app_private','procesar_aviso(uuid,uuid)'),
    ('app_fixture','capacidad(text)'),
    ('app_fixture','aislamiento()'),
    ('app_fixture','obtener(uuid,text,boolean)'),
    ('app_fixture','resumen(uuid)'),
    ('app_fixture','registrar(uuid,text,integer)'),
    ('app_fixture','provisionar(uuid,text,integer,integer,text)'),
    ('app_fixture','proteger_perfil()'),
    ('app_fixture','depurar(uuid)'),
    ('app_fixture','cerrar(uuid,text)'),
    ('app_fixture','limpiar(uuid,text)'),
    ('app_fixture','consultar(uuid,text)'),
    ('app_fixture','recuperar_expirado(uuid)')
), nombres_roles(nombre) AS (VALUES
    ('postgres'),('anon'),('authenticated'),('service_role'),('tinotify_api'),('tinotify_sync'),
    ('tinotify_notifications'),('tinotify_guard_reader'),('tinotify_state_writer'),
    ('tinotify_fixture_control'),('tinotify_fixture_recovery'),('tinotify_fixture_owner')
), roles AS (
    SELECT n.nombre,r.oid,r.rolcanlogin,r.rolinherit,r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls
    FROM nombres_roles n LEFT JOIN pg_catalog.pg_roles r ON r.rolname=n.nombre
), espacios AS (
    SELECT n.* FROM pg_catalog.pg_namespace n WHERE n.nspname IN ('app','app_private','app_fixture')
), tablas AS (
    SELECT o.*,c.oid,c.relkind,c.relowner,c.relrowsecurity,c.relforcerowsecurity,c.relacl
    FROM objetivos o LEFT JOIN espacios n ON n.nspname=o.esquema
    LEFT JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid AND c.relname=o.nombre
), columnas AS (
    SELECT t.esquema,t.nombre,t.columnas,a.*,tipo.typnamespace,tipo.typname,
        d.adbin,d.adrelid,col.collname,col.collnamespace
    FROM tablas t JOIN pg_catalog.pg_attribute a ON a.attrelid=t.oid AND a.attnum>0
    LEFT JOIN pg_catalog.pg_type tipo ON tipo.oid=a.atttypid
    LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
    LEFT JOIN pg_catalog.pg_collation col ON col.oid=a.attcollation
), rutinas AS (
    SELECT p.*,n.nspname,p.proname||'('||pg_catalog.replace(pg_catalog.oidvectortypes(p.proargtypes),' ','')||')' AS firma
    FROM pg_catalog.pg_proc p JOIN espacios n ON n.oid=p.pronamespace
), funciones AS (
    SELECT f.esquema,f.firma,p.oid,p.proowner,p.prokind,p.prosecdef,p.proisstrict,p.provolatile,p.proparallel,p.proacl FROM firmas f LEFT JOIN rutinas p
    ON p.nspname=f.esquema AND p.firma=f.firma
), permisos(permiso) AS (VALUES ('SELECT'),('INSERT'),('UPDATE'),('DELETE'),('TRUNCATE'),('REFERENCES'),('TRIGGER'),('MAINTAIN'))
SELECT pg_catalog.jsonb_build_object(
    'formato','tinotify_catalogo_v1',
    'contexto',pg_catalog.jsonb_build_object(
        'server_version',pg_catalog.current_setting('server_version'),
        'server_version_num',pg_catalog.current_setting('server_version_num')::integer,
        'pg17',pg_catalog.current_setting('server_version_num')::integer/10000=17,
        'block_size',pg_catalog.current_setting('block_size')::integer,
        'encoding',pg_catalog.current_setting('server_encoding'),
        'quote_all_identifiers',pg_catalog.current_setting('quote_all_identifiers'),
        'search_path_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.current_setting('search_path'),'UTF8')),'hex')),
    'esquemas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'nombre',nspname,'owner',CASE WHEN r.nombre IS NOT NULL THEN r.nombre ELSE '<rol_no_previsto>' END)
        ORDER BY nspname) FROM espacios n LEFT JOIN roles r ON r.oid=n.nspowner),'[]'::jsonb),
    'roles', (SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r)-'oid' ORDER BY nombre) FROM roles r),
    'tablas',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',t.esquema,'nombre',t.nombre,'presente',t.oid IS NOT NULL,'tipo',t.relkind,
        'owner',CASE WHEN r.nombre IS NOT NULL THEN r.nombre ELSE '<rol_no_previsto>' END,
        'rls',t.relrowsecurity,'force_rls',t.relforcerowsecurity) ORDER BY t.esquema,t.nombre)
        FROM tablas t LEFT JOIN roles r ON r.oid=t.relowner),
    'columnas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',c.esquema,'tabla',c.nombre,'orden',c.attnum,
        'nombre',CASE WHEN c.attname=ANY(c.columnas) THEN c.attname ELSE '<columna_no_prevista>' END,
        'nombre_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(c.attname,'UTF8')),'hex'),
        'tipo',CASE WHEN c.typnamespace='pg_catalog'::regnamespace THEN pg_catalog.format_type(c.atttypid,c.atttypmod) ELSE '<tipo_no_previsto>' END,
        'typmod',c.atttypmod,'not_null',c.attnotnull,'dropped',c.attisdropped,
        'identity',c.attidentity,'generated',c.attgenerated,'has_missing',c.atthasmissing,
        'collation',CASE WHEN c.attcollation=0 THEN NULL WHEN c.collnamespace='pg_catalog'::regnamespace THEN c.collname ELSE '<collation_no_prevista>' END,
        'default_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_expr(c.adbin,c.adrelid,false),'UTF8')),'hex'))
        ORDER BY c.esquema,c.nombre,c.attnum) FROM columnas c),'[]'::jsonb),
    'constraints',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',t.esquema,'tabla',t.nombre,
        'nombre',CASE WHEN k.conname='actuaciones_orden_uq' THEN k.conname ELSE NULL END,
        'nombre_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(k.conname,'UTF8')),'hex'),
        'tipo',k.contype,'validado',k.convalidated,'diferible',k.condeferrable,'inicialmente_diferido',k.condeferred,
        'definicion_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_constraintdef(k.oid,false),'UTF8')),'hex'))
        ORDER BY t.esquema,t.nombre,k.conname COLLATE pg_catalog."C") FROM tablas t JOIN pg_catalog.pg_constraint k ON k.conrelid=t.oid),'[]'::jsonb),
    'indices',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',t.esquema,'tabla',t.nombre,
        'nombre_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(c.relname,'UTF8')),'hex'),
        'valido',i.indisvalid,'listo',i.indisready,'unico',i.indisunique,'primario',i.indisprimary,
        'nulls_not_distinct',i.indnullsnotdistinct,
        'definicion_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_indexdef(i.indexrelid),'UTF8')),'hex'))
        ORDER BY t.esquema,t.nombre,c.relname COLLATE pg_catalog."C") FROM tablas t JOIN pg_catalog.pg_index i ON i.indrelid=t.oid
        JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid),'[]'::jsonb),
    'politicas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',t.esquema,'tabla',t.nombre,
        'nombre_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.polname,'UTF8')),'hex'),
        'comando',p.polcmd,'permisiva',p.polpermissive,
        'roles',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
            'nombre',CASE WHEN x.oid=0 THEN 'PUBLIC' WHEN r.nombre IS NOT NULL THEN r.nombre ELSE '<rol_no_previsto>' END,
            'identidad_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(CASE WHEN x.oid=0 THEN 'PUBLIC' ELSE rr.rolname END,'UTF8')),'hex'))
            ORDER BY rr.rolname COLLATE pg_catalog."C" NULLS FIRST)
            FROM pg_catalog.unnest(p.polroles) x(oid) LEFT JOIN roles r ON r.oid=x.oid LEFT JOIN pg_catalog.pg_roles rr ON rr.oid=x.oid),
        'using_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_expr(p.polqual,p.polrelid,false),'UTF8')),'hex'),
        'check_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid,false),'UTF8')),'hex'))
        ORDER BY t.esquema,t.nombre,p.polname COLLATE pg_catalog."C") FROM tablas t JOIN pg_catalog.pg_policy p ON p.polrelid=t.oid),'[]'::jsonb),
    'funciones',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',f.esquema,'firma',f.firma,'presente',f.oid IS NOT NULL,'tipo',f.prokind,
        'owner',CASE WHEN r.nombre IS NOT NULL THEN r.nombre ELSE '<rol_no_previsto>' END,
        'security_definer',f.prosecdef,'strict',f.proisstrict,'volatility',f.provolatile,'parallel',f.proparallel,
        'definicion_sha256',CASE WHEN f.prokind IN ('f','p') THEN
            pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_functiondef(f.oid),'UTF8')),'hex') END)
        ORDER BY f.esquema,f.firma COLLATE pg_catalog."C") FROM funciones f LEFT JOIN roles r ON r.oid=f.proowner),
    'acl_tablas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',t.esquema,'tabla',t.nombre,'rol',CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE coalesce(r.nombre,'<rol_no_previsto>') END,
        'rol_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE rr.rolname END,'UTF8')),'hex'),
        'otorgante_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(otorga.rolname,'UTF8')),'hex'),
        'permiso',a.privilege_type,'delegable',a.is_grantable)
        ORDER BY t.esquema,t.nombre,rr.rolname COLLATE pg_catalog."C" NULLS FIRST,a.privilege_type,otorga.rolname COLLATE pg_catalog."C",a.is_grantable)
        FROM tablas t CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(t.relacl,pg_catalog.acldefault('r',t.relowner))) a
        LEFT JOIN roles r ON r.oid=a.grantee LEFT JOIN pg_catalog.pg_roles rr ON rr.oid=a.grantee
        LEFT JOIN pg_catalog.pg_roles otorga ON otorga.oid=a.grantor),'[]'::jsonb),
    'permisos_tabla_efectivos',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',t.esquema,'tabla',t.nombre,'rol',r.nombre,'permiso',p.permiso) ORDER BY t.esquema,t.nombre,r.nombre,p.permiso)
        FROM tablas t CROSS JOIN roles r CROSS JOIN permisos p WHERE t.oid IS NOT NULL AND r.oid IS NOT NULL
        AND pg_catalog.has_table_privilege(r.oid,t.oid,p.permiso)),'[]'::jsonb),
    'permisos_columna_efectivos',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',c.esquema,'tabla',c.nombre,'orden',c.attnum,'rol',r.nombre,'permiso',p.permiso)
        ORDER BY c.esquema,c.nombre,c.attnum,r.nombre,p.permiso)
        FROM columnas c CROSS JOIN roles r CROSS JOIN permisos p WHERE NOT c.attisdropped AND r.oid IS NOT NULL
        AND CASE WHEN p.permiso IN ('SELECT','INSERT','UPDATE','REFERENCES') THEN pg_catalog.has_column_privilege(r.oid,c.attrelid,c.attnum,p.permiso) ELSE false END),'[]'::jsonb),
    'acl_columnas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',c.esquema,'tabla',c.nombre,'orden',c.attnum,
        'rol',CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE coalesce(r.nombre,'<rol_no_previsto>') END,
        'rol_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE rr.rolname END,'UTF8')),'hex'),
        'otorgante_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(otorga.rolname,'UTF8')),'hex'),
        'permiso',a.privilege_type,'delegable',a.is_grantable)
        ORDER BY c.esquema,c.nombre,c.attnum,rr.rolname COLLATE pg_catalog."C" NULLS FIRST,a.privilege_type,otorga.rolname COLLATE pg_catalog."C",a.is_grantable)
        FROM columnas c CROSS JOIN LATERAL pg_catalog.aclexplode(c.attacl) a
        LEFT JOIN roles r ON r.oid=a.grantee LEFT JOIN pg_catalog.pg_roles rr ON rr.oid=a.grantee
        LEFT JOIN pg_catalog.pg_roles otorga ON otorga.oid=a.grantor WHERE NOT c.attisdropped),'[]'::jsonb),
    'execute_efectivo',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',f.esquema,'firma',f.firma,'rol',r.nombre) ORDER BY f.esquema,f.firma,r.nombre)
        FROM funciones f CROSS JOIN roles r WHERE f.oid IS NOT NULL AND r.oid IS NOT NULL
        AND pg_catalog.has_function_privilege(r.oid,f.oid,'EXECUTE')),'[]'::jsonb),
    'acl_funciones',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',f.esquema,'firma',f.firma,'rol',CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE coalesce(r.nombre,'<rol_no_previsto>') END,
        'rol_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE rr.rolname END,'UTF8')),'hex'),
        'otorgante_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(otorga.rolname,'UTF8')),'hex'),
        'permiso',a.privilege_type,'delegable',a.is_grantable) ORDER BY f.esquema,f.firma,rr.rolname COLLATE pg_catalog."C" NULLS FIRST,a.privilege_type,otorga.rolname COLLATE pg_catalog."C",a.is_grantable)
        FROM funciones f CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(f.proacl,pg_catalog.acldefault('f',f.proowner))) a
        LEFT JOIN roles r ON r.oid=a.grantee LEFT JOIN pg_catalog.pg_roles rr ON rr.oid=a.grantee
        LEFT JOIN pg_catalog.pg_roles otorga ON otorga.oid=a.grantor WHERE f.oid IS NOT NULL),'[]'::jsonb),
    'permisos_esquema',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',n.nspname,'rol',r.nombre,'usage',pg_catalog.has_schema_privilege(r.oid,n.oid,'USAGE'),
        'create',pg_catalog.has_schema_privilege(r.oid,n.oid,'CREATE')) ORDER BY n.nspname,r.nombre)
        FROM espacios n CROSS JOIN roles r WHERE r.oid IS NOT NULL),'[]'::jsonb),
    'acl_esquemas',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',n.nspname,'rol',CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE coalesce(r.nombre,'<rol_no_previsto>') END,
        'rol_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE rr.rolname END,'UTF8')),'hex'),
        'otorgante_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(otorga.rolname,'UTF8')),'hex'),
        'permiso',a.privilege_type,'delegable',a.is_grantable)
        ORDER BY n.nspname,rr.rolname COLLATE pg_catalog."C" NULLS FIRST,a.privilege_type,otorga.rolname COLLATE pg_catalog."C",a.is_grantable)
        FROM espacios n CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) a
        LEFT JOIN roles r ON r.oid=a.grantee LEFT JOIN pg_catalog.pg_roles rr ON rr.oid=a.grantee
        LEFT JOIN pg_catalog.pg_roles otorga ON otorga.oid=a.grantor),'[]'::jsonb),
    'membresias',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'rol',coalesce(rol.nombre,'<rol_no_previsto>'),'miembro',coalesce(miembro.nombre,'<rol_no_previsto>'),
        'rol_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(rr.rolname,'UTF8')),'hex'),
        'miembro_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(mm.rolname,'UTF8')),'hex'),
        'otorgante_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(otorga.rolname,'UTF8')),'hex'),
        'admin',a.admin_option,'inherit',a.inherit_option,'set',a.set_option)
        ORDER BY rr.rolname COLLATE pg_catalog."C",mm.rolname COLLATE pg_catalog."C",otorga.rolname COLLATE pg_catalog."C")
        FROM pg_catalog.pg_auth_members a JOIN pg_catalog.pg_roles rr ON rr.oid=a.roleid JOIN pg_catalog.pg_roles mm ON mm.oid=a.member
        LEFT JOIN roles rol ON rol.oid=a.roleid LEFT JOIN roles miembro ON miembro.oid=a.member
        LEFT JOIN pg_catalog.pg_roles otorga ON otorga.oid=a.grantor
        WHERE rol.oid IS NOT NULL OR miembro.oid IS NOT NULL),'[]'::jsonb),
    'defaults',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'creador',r.nombre,'esquema',CASE WHEN d.defaclnamespace=0 THEN '<global>' ELSE n.nspname END,
        'tipo',d.defaclobjtype,'destinatario',CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE coalesce(destino.nombre,'<rol_no_previsto>') END,
        'destinatario_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE rr.rolname END,'UTF8')),'hex'),
        'otorgante_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(otorga.rolname,'UTF8')),'hex'),
        'permiso',a.privilege_type,'delegable',a.is_grantable)
        ORDER BY r.nombre,d.defaclnamespace=0,n.nspname,d.defaclobjtype,rr.rolname COLLATE pg_catalog."C" NULLS FIRST,a.privilege_type,otorga.rolname COLLATE pg_catalog."C",a.is_grantable)
        FROM pg_catalog.pg_default_acl d JOIN roles r ON r.oid=d.defaclrole LEFT JOIN espacios n ON n.oid=d.defaclnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) a LEFT JOIN roles destino ON destino.oid=a.grantee
        LEFT JOIN pg_catalog.pg_roles rr ON rr.oid=a.grantee LEFT JOIN pg_catalog.pg_roles otorga ON otorga.oid=a.grantor
        WHERE d.defaclnamespace=0 OR n.oid IS NOT NULL),'[]'::jsonb),
    'triggers',coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'esquema',t.esquema,'tabla',t.nombre,
        'nombre_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(g.tgname,'UTF8')),'hex'),
        'habilitado',g.tgenabled,'definicion_sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_triggerdef(g.oid,false),'UTF8')),'hex'))
        ORDER BY t.esquema,t.nombre,g.tgname COLLATE pg_catalog."C") FROM tablas t JOIN pg_catalog.pg_trigger g ON g.tgrelid=t.oid WHERE NOT g.tgisinternal),'[]'::jsonb),
    'extras',pg_catalog.jsonb_build_object(
        'relaciones',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_class c JOIN espacios n ON n.oid=c.relnamespace
            WHERE c.relkind<>'i' AND NOT EXISTS(SELECT 1 FROM objetivos t WHERE t.esquema=n.nspname AND t.nombre=c.relname)),
        'rutinas',(SELECT pg_catalog.count(*) FROM rutinas p WHERE NOT EXISTS(SELECT 1 FROM firmas f WHERE f.esquema=p.nspname AND f.firma=p.firma))),
    'proveedor',pg_catalog.jsonb_build_object(
        'event_triggers',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_event_trigger WHERE evtenabled<>'D'),
        'ajustes_supautils',(SELECT pg_catalog.count(*) FROM pg_catalog.pg_settings WHERE name LIKE 'supautils.%'))
) AS inventario_4b4a;
