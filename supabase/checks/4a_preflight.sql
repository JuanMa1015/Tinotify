-- Solo lectura. Ejecutar con db query --read-only; no es una migracion.
-- No consulta usuarios de Auth, expedientes, credenciales ni datos de negocio.
-- Que un ajuste pgrst no aparezca NO demuestra que no exista en el servicio.
WITH runtime_roles AS (
    SELECT oid, rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
           rolcreaterole, rolreplication, rolbypassrls
    FROM pg_catalog.pg_roles
    WHERE rolname LIKE 'tinotify!_%' ESCAPE '!'
), private_schemas AS (
    SELECT oid, nspname, nspowner
    FROM pg_catalog.pg_namespace
    WHERE nspname IN ('app', 'app_private')
), defaults AS (
    SELECT CASE WHEN r.rolname = 'postgres' THEN 'postgres'
                ELSE '<rol_actual>' END AS creador,
           CASE WHEN d.defaclnamespace = 0 THEN '<global>'
                ELSE n.nspname END AS esquema,
           d.defaclobjtype::text AS tipo,
           CASE WHEN a.grantee = 0 THEN 'PUBLIC'
                WHEN g.rolname IN (
                    'postgres', 'anon', 'authenticated', 'service_role',
                    'tinotify_api', 'tinotify_sync', 'tinotify_notifications'
                ) THEN g.rolname ELSE '<otro_rol>' END AS destinatario,
           a.privilege_type AS privilegio, a.is_grantable AS delegable
    FROM pg_catalog.pg_default_acl AS d
    JOIN pg_catalog.pg_roles AS r ON r.oid = d.defaclrole
    LEFT JOIN pg_catalog.pg_namespace AS n ON n.oid = d.defaclnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) AS a
    LEFT JOIN pg_catalog.pg_roles AS g ON g.oid = a.grantee
    WHERE r.rolname IN ('postgres', CURRENT_USER)
      AND (d.defaclnamespace = 0 OR n.nspname IN ('public', 'app', 'app_private'))
      AND d.defaclobjtype IN ('r', 'S', 'f', 'n')
), memberships AS (
    SELECT CASE WHEN p.rolname IN (
                    'postgres', 'anon', 'authenticated', 'service_role', 'authenticator',
                    'tinotify_api', 'tinotify_sync', 'tinotify_notifications'
                ) THEN p.rolname ELSE '<otro_rol>' END AS rol_concedido,
           CASE WHEN m.rolname IN (
                    'postgres', 'anon', 'authenticated', 'service_role', 'authenticator',
                    'tinotify_api', 'tinotify_sync', 'tinotify_notifications'
                ) THEN m.rolname ELSE '<otro_rol>' END AS miembro,
           am.admin_option AS puede_delegar,
           (pg_catalog.to_jsonb(am) ->> 'inherit_option')::boolean AS hereda,
           (pg_catalog.to_jsonb(am) ->> 'set_option')::boolean AS puede_asumir
    FROM pg_catalog.pg_auth_members AS am
    JOIN pg_catalog.pg_roles AS p ON p.oid = am.roleid
    JOIN pg_catalog.pg_roles AS m ON m.oid = am.member
    WHERE p.oid IN (SELECT oid FROM runtime_roles)
       OR m.oid IN (SELECT oid FROM runtime_roles)
), schema_roles AS (
    SELECT oid, rolname FROM pg_catalog.pg_roles
    WHERE rolname IN (
        'tinotify_api', 'tinotify_sync', 'tinotify_notifications',
        'anon', 'authenticated', 'service_role', 'authenticator'
    )
), schema_access AS (
    SELECT r.rolname AS rol, n.nspname AS esquema,
           pg_catalog.has_schema_privilege(r.oid, n.oid, 'USAGE') AS puede_usar,
           pg_catalog.has_schema_privilege(r.oid, n.oid, 'CREATE') AS puede_crear
    FROM schema_roles AS r CROSS JOIN private_schemas AS n
), pgrst_settings AS (
    SELECT CASE WHEN s.setrole = 0 THEN '<todos>'
                ELSE r.rolname END AS rol,
           CASE WHEN s.setdatabase = 0 THEN '<todas>'
                ELSE '<base_actual>' END AS base,
           pg_catalog.substr(v.setting, pg_catalog.length('pgrst.db_schemas=') + 1)
               AS esquemas_configurados
    FROM pg_catalog.pg_db_role_setting AS s
    LEFT JOIN pg_catalog.pg_roles AS r ON r.oid = s.setrole
    CROSS JOIN LATERAL pg_catalog.unnest(s.setconfig) AS v(setting)
    WHERE (s.setrole = 0 OR r.rolname IN ('authenticator', 'postgres'))
      AND (s.setdatabase = 0 OR s.setdatabase = (
          SELECT oid FROM pg_catalog.pg_database WHERE datname = CURRENT_DATABASE()
      ))
      AND v.setting LIKE 'pgrst.db_schemas=%'
)
SELECT pg_catalog.jsonb_build_object(
    'requisitos', pg_catalog.jsonb_build_object(
        'version_postgresql', pg_catalog.current_setting('server_version'),
        'identidad_efectiva_es_postgres', CURRENT_USER = 'postgres',
        'identidad_efectiva_es_la_de_sesion', CURRENT_USER = SESSION_USER,
        'conexion_puede_crear_esquemas',
            pg_catalog.has_database_privilege(CURRENT_USER, CURRENT_DATABASE(), 'CREATE'),
        'conexion_puede_crear_roles', (
            SELECT rolcreaterole OR rolsuper FROM pg_catalog.pg_roles WHERE rolname = CURRENT_USER
        ),
        'conexion_puede_asignar_propietario_postgres', CASE
            WHEN pg_catalog.current_setting('server_version_num')::integer >= 160000
            THEN pg_catalog.pg_has_role(CURRENT_USER, 'postgres', 'SET')
            ELSE pg_catalog.pg_has_role(CURRENT_USER, 'postgres', 'MEMBER') END,
        'conexion_puede_administrar_esquemas_de_postgres',
            pg_catalog.pg_has_role(CURRENT_USER, 'postgres', 'USAGE'),
        'conexion_puede_usar_plpgsql',
            pg_catalog.has_language_privilege(CURRENT_USER, 'plpgsql', 'USAGE')
    ),
    'esquemas_existentes', COALESCE((
        SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
            'esquema', nspname,
            'propietario_postgres', nspowner = 'postgres'::regrole
        ) ORDER BY nspname) FROM private_schemas
    ), '[]'::jsonb),
    'roles_existentes', COALESCE((
        SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) - 'oid' ORDER BY rolname)
        FROM runtime_roles AS r
    ), '[]'::jsonb),
    'membresias_runtime', COALESCE((
        SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(m) ORDER BY rol_concedido, miembro)
        FROM memberships AS m
    ), '[]'::jsonb),
    'acceso_efectivo_a_esquemas', COALESCE((
        SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(a) ORDER BY rol, esquema)
        FROM schema_access AS a
    ), '[]'::jsonb),
    'default_acl_explicitos', COALESCE((
        SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d)
            ORDER BY creador, esquema, tipo, destinatario, privilegio)
        FROM defaults AS d
    ), '[]'::jsonb),
    'ajustes_sql_pgrst', COALESCE((
        SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(p) ORDER BY rol, base)
        FROM pgrst_settings AS p
    ), '[]'::jsonb),
    'nota_defaults', 'Sin override global, PostgreSQL concede EXECUTE a PUBLIC en funciones; las ACL por esquema se suman a las globales.',
    'nota_identidad', 'La Management API puede usar una identidad distinta de db push. Estos permisos solo acreditan la conexion que ejecuto esta consulta; no autorizan aplicar migraciones.',
    'nota_data_api', 'Revisar tambien Exposed schemas en Dashboard; este informe no confirma la configuracion externa de PostgREST.'
) AS revision_4a;
