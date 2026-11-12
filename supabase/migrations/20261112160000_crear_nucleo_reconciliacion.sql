-- Etapa 4B.1: propuesta local pendiente de revision y autorizacion remota.
-- Ocho tablas; sin datos, funciones de negocio, politicas permisivas ni GRANT.
-- Requiere 4A intacta y current_user = postgres. No cambia roles/propietarios.
-- No usar IF NOT EXISTS: colisiones abortan, no reutilizan objetos desconocidos.
BEGIN;

DO $precondiciones_4b1$
BEGIN
    IF current_setting('server_version_num')::integer / 10000 <> 17 THEN
        RAISE EXCEPTION '4B.1 revisada para PostgreSQL 17; revisar otra version antes de continuar.';
    END IF;
    IF CURRENT_USER <> 'postgres' THEN
        RAISE EXCEPTION USING ERRCODE = '42501',
            MESSAGE = '4B.1 requiere identidad efectiva postgres; revisar conexion, sin elevacion automatica.';
    END IF;
    IF (SELECT count(*) FROM pg_catalog.pg_namespace n
        JOIN pg_catalog.pg_roles r ON r.oid = n.nspowner
        WHERE n.nspname IN ('app','app_private') AND r.rolname = 'postgres') <> 2
        OR pg_catalog.to_regclass('auth.users') IS NULL THEN
        RAISE EXCEPTION 'Precondiciones de esquemas de 4A/Auth no satisfechas.';
    END IF;
    IF (SELECT count(*) FROM pg_catalog.pg_roles
        WHERE rolname IN ('tinotify_api','tinotify_sync','tinotify_notifications')
          AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
          AND NOT rolbypassrls) <> 3 THEN
        RAISE EXCEPTION 'Roles de 4A ausentes o con atributos incompatibles.';
    END IF;
END;
$precondiciones_4b1$;

CREATE TABLE app.estudiantes (
    id uuid PRIMARY KEY,
    auth_subject uuid UNIQUE REFERENCES auth.users(id) ON DELETE SET NULL,
    estado text NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente','activo','suspendido','borrado_solicitado')),
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE app.estados_reconciliacion (
    estudiante_id uuid NOT NULL REFERENCES app.estudiantes(id),
    id uuid NOT NULL,
    instancia_utf8 bytea NOT NULL CHECK (octet_length(instancia_utf8) BETWEEN 1 AND 512),
    epoca bigint NOT NULL CHECK (epoca > 0),
    situacion text NOT NULL CHECK (situacion IN ('activo','transicion_requerida','archivado')),
    schema_version smallint NOT NULL CHECK (schema_version = 2),
    state_revision smallint NOT NULL CHECK (state_revision = 2),
    fingerprint_version smallint NOT NULL CHECK (fingerprint_version = 1),
    trust_policy text COLLATE "C" NOT NULL CHECK (trust_policy ~ '^[0-9a-f]{64}$'),
    migrated_from_v1 boolean NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (estudiante_id,id),
    UNIQUE (estudiante_id,instancia_utf8,epoca),
    UNIQUE (estudiante_id,id,instancia_utf8)
);
CREATE UNIQUE INDEX una_cabecera_viva ON app.estados_reconciliacion
    (estudiante_id,instancia_utf8)
    WHERE situacion IN ('activo','transicion_requerida');
CREATE TABLE app.expedientes (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    id uuid NOT NULL,
    clave_caso_utf8 bytea NOT NULL CHECK (octet_length(clave_caso_utf8) BETWEEN 1 AND 512),
    incluido_en_estado boolean NOT NULL DEFAULT false,
    generacion bigint NOT NULL DEFAULT 0 CHECK (generacion >= 0),
    fencing bigint NOT NULL DEFAULT 0 CHECK (fencing >= 0),
    PRIMARY KEY (estudiante_id,estado_id,id),
    FOREIGN KEY (estudiante_id,estado_id)
        REFERENCES app.estados_reconciliacion(estudiante_id,id),
    UNIQUE (estudiante_id,estado_id,clave_caso_utf8),
    UNIQUE (estudiante_id,estado_id,id,clave_caso_utf8)
);
CREATE TABLE app.actuaciones (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    expediente_id uuid NOT NULL,
    local_id uuid NOT NULL,
    orden_registro bigint NOT NULL CHECK (orden_registro >= 0),
    version_hash text COLLATE "C" NOT NULL CHECK (version_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN (
        'linea_base','sin_cambios','primera_observacion','modificada','ambigua')),
    source_id text COLLATE "C",
    contrato_clave_utf8 bytea,
    contrato_version_decimal text COLLATE "C",
    contrato_revision text COLLATE "C",
    alcance_instancia_utf8 bytea,
    alcance_caso_utf8 bytea,
    PRIMARY KEY (estudiante_id,estado_id,expediente_id,local_id),
    UNIQUE (estudiante_id,estado_id,local_id),
    CONSTRAINT actuaciones_orden_uq UNIQUE (estudiante_id,estado_id,expediente_id,orden_registro)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (estudiante_id,estado_id,expediente_id)
        REFERENCES app.expedientes(estudiante_id,estado_id,id),
    FOREIGN KEY (estudiante_id,estado_id,alcance_instancia_utf8)
        REFERENCES app.estados_reconciliacion(estudiante_id,id,instancia_utf8),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id,alcance_caso_utf8)
        REFERENCES app.expedientes(estudiante_id,estado_id,id,clave_caso_utf8),
    CHECK (
        (source_id IS NULL AND contrato_clave_utf8 IS NULL
         AND contrato_version_decimal IS NULL AND contrato_revision IS NULL
         AND alcance_instancia_utf8 IS NULL AND alcance_caso_utf8 IS NULL)
        OR
        (source_id IS NOT NULL AND contrato_clave_utf8 IS NOT NULL
         AND contrato_version_decimal IS NOT NULL AND contrato_revision IS NOT NULL
         AND alcance_instancia_utf8 IS NOT NULL AND alcance_caso_utf8 IS NOT NULL)
    ),
    CHECK (source_id IS NOT NULL OR status <> 'modificada'),
    CHECK (source_id IS NULL OR source_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'),
    CHECK (contrato_clave_utf8 IS NULL OR octet_length(contrato_clave_utf8) BETWEEN 1 AND 512),
    CHECK (contrato_version_decimal IS NULL OR
        (contrato_version_decimal ~ '^[1-9][0-9]*$' AND length(contrato_version_decimal) <= 128)),
    CHECK (contrato_revision IS NULL OR contrato_revision ~ '^[0-9a-f]{64}$')
);
CREATE UNIQUE INDEX una_identidad_estable_por_alcance ON app.actuaciones
    (estudiante_id,estado_id,expediente_id,contrato_clave_utf8,
     contrato_version_decimal,contrato_revision,source_id)
    WHERE source_id IS NOT NULL;
CREATE INDEX actuaciones_huella ON app.actuaciones
    (estudiante_id,estado_id,expediente_id,version_hash);
CREATE TABLE app_private.accesos_sigac (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    expediente_id uuid NOT NULL,
    estado text NOT NULL DEFAULT 'no_verificado'
        CHECK (estado IN ('no_verificado','verificado','denegado','caducado')),
    fuente text NOT NULL DEFAULT 'ninguna' CHECK (fuente IN ('ninguna','simulador','sigac')),
    session_binding_id uuid,
    session_epoch bigint NOT NULL DEFAULT 0 CHECK (session_epoch >= 0),
    access_epoch bigint NOT NULL DEFAULT 0 CHECK (access_epoch >= 0),
    comprobado_en timestamptz,
    valido_hasta timestamptz,
    comprobante_ref uuid,
    PRIMARY KEY (estudiante_id,estado_id,expediente_id),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id)
        REFERENCES app.expedientes(estudiante_id,estado_id,id),
    CHECK (valido_hasta IS NULL OR
        (comprobado_en IS NOT NULL AND valido_hasta > comprobado_en)),
    CHECK (estado <> 'verificado' OR
        (fuente IN ('simulador','sigac') AND session_binding_id IS NOT NULL
         AND session_epoch > 0 AND access_epoch > 0 AND comprobante_ref IS NOT NULL
         AND comprobado_en IS NOT NULL AND valido_hasta IS NOT NULL))
);
CREATE INDEX accesos_caducidad ON app_private.accesos_sigac (estado,valido_hasta);
CREATE TABLE app_private.sincronizaciones (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    expediente_id uuid NOT NULL,
    id uuid NOT NULL,
    idempotency_key uuid NOT NULL,
    modo text NOT NULL DEFAULT 'sintetico' CHECK (modo IN ('sintetico','institucional')),
    estado text NOT NULL CHECK (estado IN (
        'reservada','ejecutando','confirmada','fallida','cancelada','expirada')),
    generacion_base bigint NOT NULL CHECK (generacion_base >= 0),
    generacion_confirmada bigint,
    access_epoch bigint NOT NULL CHECK (access_epoch >= 0),
    session_epoch bigint NOT NULL CHECK (session_epoch >= 0),
    fencing bigint NOT NULL CHECK (fencing > 0),
    worker_id uuid,
    lease_token uuid,
    lease_hasta timestamptz,
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    terminado_en timestamptz,
    PRIMARY KEY (estudiante_id,estado_id,expediente_id,id),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id)
        REFERENCES app.expedientes(estudiante_id,estado_id,id),
    UNIQUE (estudiante_id,estado_id,expediente_id,idempotency_key),
    UNIQUE (estudiante_id,estado_id,expediente_id,fencing),
    CHECK (estado NOT IN ('reservada','ejecutando') OR
        (worker_id IS NOT NULL AND lease_token IS NOT NULL AND lease_hasta IS NOT NULL)),
    CHECK ((estado = 'confirmada' AND generacion_confirmada IS NOT NULL)
        OR (estado <> 'confirmada' AND generacion_confirmada IS NULL)),
    CHECK (generacion_confirmada IS NULL OR generacion_confirmada >= generacion_base),
    CHECK ((estado IN ('reservada','ejecutando') AND terminado_en IS NULL)
        OR (estado IN ('confirmada','fallida','cancelada','expirada') AND terminado_en IS NOT NULL))
);
CREATE UNIQUE INDEX una_sincronizacion_activa ON app_private.sincronizaciones
    (estudiante_id,estado_id,expediente_id) WHERE estado IN ('reservada','ejecutando');
CREATE INDEX sincronizaciones_cola ON app_private.sincronizaciones (estado,lease_hasta,creado_en);
CREATE TABLE app.eventos (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    expediente_id uuid NOT NULL,
    id uuid NOT NULL,
    sincronizacion_id uuid NOT NULL,
    ordinal bigint NOT NULL CHECK (ordinal >= 0),
    local_id uuid NOT NULL,
    generacion_resultado bigint NOT NULL CHECK (generacion_resultado >= 0),
    tipo text NOT NULL CHECK (tipo IN (
        'primera_observacion','modificacion_confirmada','cambio_ambiguo')),
    prioridad text NOT NULL CHECK (prioridad IN ('alta','normal')),
    disposicion text NOT NULL DEFAULT 'pendiente'
        CHECK (disposicion IN ('pendiente','procesado','descartado_por_politica')),
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (estudiante_id,id),
    UNIQUE (estudiante_id,estado_id,expediente_id,sincronizacion_id,ordinal),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id,sincronizacion_id)
        REFERENCES app_private.sincronizaciones(estudiante_id,estado_id,expediente_id,id),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id,local_id)
        REFERENCES app.actuaciones(estudiante_id,estado_id,expediente_id,local_id)
);
CREATE INDEX eventos_actuacion ON app.eventos (estudiante_id,estado_id,expediente_id,local_id);
CREATE INDEX eventos_pendientes ON app.eventos (prioridad,creado_en) WHERE disposicion = 'pendiente';
CREATE TABLE app_private.importaciones (
    estudiante_id uuid NOT NULL REFERENCES app.estudiantes(id),
    id uuid NOT NULL,
    idempotency_key uuid NOT NULL,
    estado_id uuid,
    source_sha256 text COLLATE "C" NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    source_bytes bigint NOT NULL CHECK (source_bytes BETWEEN 0 AND 67108864),
    estado text NOT NULL CHECK (estado IN ('reservada','confirmada','rechazada')),
    casos bigint CHECK (casos >= 0),
    registros bigint CHECK (registros >= 0),
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (estudiante_id,id),
    UNIQUE (estudiante_id,idempotency_key),
    FOREIGN KEY (estudiante_id,estado_id)
        REFERENCES app.estados_reconciliacion(estudiante_id,id),
    CHECK ((estado = 'confirmada' AND estado_id IS NOT NULL AND casos IS NOT NULL AND registros IS NOT NULL)
        OR (estado <> 'confirmada' AND estado_id IS NULL))
);
CREATE INDEX importaciones_estado ON app_private.importaciones (estudiante_id,estado_id);
CREATE INDEX importaciones_digest ON app_private.importaciones (estudiante_id,source_sha256);

-- Cierre por tabla, dentro de la misma transaccion que su creacion.
ALTER TABLE app.estudiantes ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.estudiantes FORCE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE app.estudiantes
    FROM PUBLIC, anon, authenticated, service_role,
         tinotify_api, tinotify_sync, tinotify_notifications;
ALTER TABLE app.estados_reconciliacion ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.estados_reconciliacion FORCE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE app.estados_reconciliacion
    FROM PUBLIC, anon, authenticated, service_role,
         tinotify_api, tinotify_sync, tinotify_notifications;
ALTER TABLE app.expedientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.expedientes FORCE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE app.expedientes
    FROM PUBLIC, anon, authenticated, service_role,
         tinotify_api, tinotify_sync, tinotify_notifications;
ALTER TABLE app.actuaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.actuaciones FORCE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE app.actuaciones
    FROM PUBLIC, anon, authenticated, service_role,
         tinotify_api, tinotify_sync, tinotify_notifications;
ALTER TABLE app.eventos ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.eventos FORCE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE app.eventos
    FROM PUBLIC, anon, authenticated, service_role,
         tinotify_api, tinotify_sync, tinotify_notifications;
ALTER TABLE app_private.accesos_sigac ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.accesos_sigac FORCE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE app_private.accesos_sigac
    FROM PUBLIC, anon, authenticated, service_role,
         tinotify_api, tinotify_sync, tinotify_notifications;
ALTER TABLE app_private.sincronizaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.sincronizaciones FORCE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE app_private.sincronizaciones
    FROM PUBLIC, anon, authenticated, service_role,
         tinotify_api, tinotify_sync, tinotify_notifications;
ALTER TABLE app_private.importaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.importaciones FORCE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE app_private.importaciones
    FROM PUBLIC, anon, authenticated, service_role,
         tinotify_api, tinotify_sync, tinotify_notifications;

-- Abortamos si default privileges ajenos dejaron ACL residuales.
-- No revocamos privilegios desconocidos silenciosamente ni alteramos defaults.
DO $cierre_4b1$
DECLARE total integer; t regclass; rol text; permiso text;
BEGIN
    SELECT count(*) INTO total FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE (n.nspname,c.relname) IN (
        ('app','estudiantes'),('app','estados_reconciliacion'),
        ('app','expedientes'),('app','actuaciones'),('app','eventos'),
        ('app_private','accesos_sigac'),('app_private','sincronizaciones'),
        ('app_private','importaciones')
    ) AND c.relkind = 'r' AND c.relrowsecurity AND c.relforcerowsecurity
      AND c.relowner = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'postgres');
    IF total <> 8 THEN
        RAISE EXCEPTION 'Tablas de 4B.1 sin cierre RLS/propiedad esperados.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
        WHERE n.nspname IN ('app','app_private')
          AND c.relkind = 'r' AND a.grantee <> c.relowner
    ) THEN
        RAISE EXCEPTION 'ACL residual inesperada; revisar defaults antes de reintentar.';
    END IF;
    -- Las ACL de columna sobreviven a REVOKE de tabla. Inspeccionar todo
    -- grantee no propietario cubre PUBLIC y grupos, no solo clientes directos.
    FOREACH t IN ARRAY ARRAY[
        'app.estudiantes'::regclass,'app.estados_reconciliacion'::regclass,
        'app.expedientes'::regclass,'app.actuaciones'::regclass,'app.eventos'::regclass,
        'app_private.accesos_sigac'::regclass,'app_private.sincronizaciones'::regclass,
        'app_private.importaciones'::regclass]
    LOOP
        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                coalesce(a.attacl,ARRAY[]::aclitem[])) privilegio
            WHERE a.attrelid=t AND a.attnum>0 AND NOT a.attisdropped
              AND privilegio.grantee<>c.relowner
        ) THEN
            RAISE EXCEPTION 'ACL residual de columna; revisar sin ampliar permisos.';
        END IF;
        FOREACH rol IN ARRAY ARRAY[
            'anon','authenticated','service_role',
            'tinotify_api','tinotify_sync','tinotify_notifications']
        LOOP
            IF pg_catalog.pg_has_role(rol,'postgres','USAGE')
               OR pg_catalog.pg_has_role(rol,'postgres','SET') THEN
                RAISE EXCEPTION 'Rol operativo con acceso al propietario; revisar membresias.';
            END IF;
            FOREACH permiso IN ARRAY ARRAY[
                'SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN']
            LOOP
                IF pg_catalog.has_table_privilege(rol,t,permiso) THEN
                    RAISE EXCEPTION 'Privilegio efectivo de tabla inesperado.';
                END IF;
            END LOOP;
            FOREACH permiso IN ARRAY ARRAY['SELECT','INSERT','UPDATE','REFERENCES']
            LOOP
                IF pg_catalog.has_any_column_privilege(rol,t,permiso) THEN
                    RAISE EXCEPTION 'Privilegio efectivo de columna inesperado.';
                END IF;
            END LOOP;
        END LOOP;
    END LOOP;
END;
$cierre_4b1$;

COMMIT;
