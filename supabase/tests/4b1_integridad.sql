\set ON_ERROR_STOP on
-- FUTURO: no ejecutar sin aprobacion posterior a aplicar 4B.1.
-- Solo fixtures sinteticos dentro de una transaccion que termina en ROLLBACK.
-- Necesita identidad administrativa YA autorizada capaz de superar FORCE RLS.
BEGIN;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '3s';
DO $preflight$
DECLARE t regclass; rol text; permiso text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles
                   WHERE rolname=CURRENT_USER AND (rolsuper OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Pruebas bloqueadas: se requiere administrador autorizado; no cambiar RLS/roles.';
    END IF;
    FOREACH t IN ARRAY ARRAY['app.estudiantes'::regclass,'app.estados_reconciliacion'::regclass,
        'app.expedientes'::regclass,'app.actuaciones'::regclass,'app.eventos'::regclass,
        'app_private.accesos_sigac'::regclass,'app_private.sincronizaciones'::regclass,
        'app_private.importaciones'::regclass]
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class
                       WHERE oid=t AND relrowsecurity AND relforcerowsecurity)
           OR EXISTS (SELECT 1 FROM pg_catalog.pg_policy WHERE polrelid=t) THEN
            RAISE EXCEPTION 'Cierre RLS incorrecto en %',t;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_class c,
                   LATERAL pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
                   WHERE c.oid=t AND a.grantee<>c.relowner) THEN
            RAISE EXCEPTION 'ACL residual, incluido PUBLIC, en %',t;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
            CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) p
            WHERE a.attrelid=t AND a.attnum>0 AND NOT a.attisdropped AND p.grantee<>c.relowner
        ) THEN
            RAISE EXCEPTION 'ACL de columna residual en %',t;
        END IF;
        FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role','tinotify_api','tinotify_sync','tinotify_notifications']
        LOOP
            IF pg_catalog.pg_has_role(rol,'postgres','USAGE') OR pg_catalog.pg_has_role(rol,'postgres','SET') THEN
                RAISE EXCEPTION 'Rol operativo con acceso al propietario.';
            END IF;
            FOREACH permiso IN ARRAY ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN']
            LOOP
                IF pg_catalog.has_table_privilege(rol,t,permiso) THEN
                    RAISE EXCEPTION 'Permiso operativo inesperado en %',t;
                END IF;
                IF permiso IN ('SELECT','INSERT','UPDATE','REFERENCES') THEN
                    IF pg_catalog.has_any_column_privilege(rol,t,permiso) THEN
                        RAISE EXCEPTION 'Permiso de columna inesperado en %',t;
                    END IF;
                END IF;
            END LOOP;
        END LOOP;
    END LOOP;
END;
$preflight$;

INSERT INTO app.estudiantes(id) VALUES ('4b100000-0000-4000-8000-000000000001'),('4b100000-0000-4000-8000-000000000002');
INSERT INTO app.estados_reconciliacion
(estudiante_id,id,instancia_utf8,epoca,situacion,schema_version,state_revision,fingerprint_version,trust_policy,migrated_from_v1)
VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001',convert_to('INSTANCIA_FICTICIA','UTF8'),1,'activo',2,2,1,repeat('0',64),false),
       ('4b100000-0000-4000-8000-000000000002','4b110000-0000-4000-8000-000000000002',convert_to('INSTANCIA_FICTICIA','UTF8'),1,'activo',2,2,1,repeat('0',64),false),
       ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000003',convert_to('INSTANCIA_FICTICIA','UTF8'),2,'archivado',2,2,1,repeat('0',64),false);
INSERT INTO app.expedientes(estudiante_id,estado_id,id,clave_caso_utf8,incluido_en_estado)
VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000001',convert_to('CASO_FICTICIO_A','UTF8'),true),
       ('4b100000-0000-4000-8000-000000000002','4b110000-0000-4000-8000-000000000002','4b120000-0000-4000-8000-000000000002',convert_to('CASO_FICTICIO_B','UTF8'),true),
       ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000003',convert_to('CASO_FICTICIO_C','UTF8'),true);
INSERT INTO app.actuaciones
(estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status)
VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000001','4b130000-0000-4000-8000-000000000001',0,repeat('a',64),'linea_base'),
       ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000001','4b130000-0000-4000-8000-000000000002',1,repeat('a',64),'linea_base');
INSERT INTO app.actuaciones
(estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status,
 source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,alcance_caso_utf8)
VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000001','4b130000-0000-4000-8000-000000000003',2,repeat('b',64),'linea_base','ID_FICTICIO',
        convert_to('CONTRATO_FICTICIO','UTF8'),'1',repeat('c',64),
        convert_to('INSTANCIA_FICTICIA','UTF8'),convert_to('CASO_FICTICIO_A','UTF8')),
       ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000001','4b130000-0000-4000-8000-000000000004',3,repeat('b',64),'linea_base','ID_FICTICIO',
        convert_to('OTRO_CONTRATO_FICTICIO','UTF8'),'1',repeat('c',64),
        convert_to('INSTANCIA_FICTICIA','UTF8'),convert_to('CASO_FICTICIO_A','UTF8'));
INSERT INTO app_private.accesos_sigac(estudiante_id,estado_id,expediente_id)
VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000001');
INSERT INTO app_private.sincronizaciones
(estudiante_id,estado_id,expediente_id,id,idempotency_key,estado,generacion_base,
 generacion_confirmada,access_epoch,session_epoch,fencing,worker_id,lease_token,lease_hasta,terminado_en)
VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000001','4b140000-0000-4000-8000-000000000001','4b150000-0000-4000-8000-000000000001',
        'confirmada',0,1,0,0,1,NULL,NULL,NULL,now()),
       ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000001','4b140000-0000-4000-8000-000000000002','4b150000-0000-4000-8000-000000000002',
        'reservada',1,NULL,0,0,2,'4b1a0000-0000-4000-8000-000000000001',
        '4b1b0000-0000-4000-8000-000000000001',now()+interval '5 minutes',NULL);
INSERT INTO app.eventos
(estudiante_id,estado_id,expediente_id,id,sincronizacion_id,ordinal,local_id,generacion_resultado,tipo,prioridad)
VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000001','4b160000-0000-4000-8000-000000000001','4b140000-0000-4000-8000-000000000001',
        0,'4b130000-0000-4000-8000-000000000001',1,'primera_observacion','normal');
INSERT INTO app_private.importaciones
(estudiante_id,id,idempotency_key,estado_id,source_sha256,source_bytes,estado,casos,registros)
VALUES ('4b100000-0000-4000-8000-000000000001','4b170000-0000-4000-8000-000000000001','4b180000-0000-4000-8000-000000000001',
        '4b110000-0000-4000-8000-000000000001',repeat('d',64),42,'confirmada',2,8);

-- Claves distintas por componente, sin incluir version_hash en identidad.
INSERT INTO app.estados_reconciliacion
(estudiante_id,id,instancia_utf8,epoca,situacion,schema_version,state_revision,fingerprint_version,trust_policy,migrated_from_v1)
VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000020',convert_to('INSTANCIA_FICTICIA_B','UTF8'),1,'activo',2,2,1,repeat('0',64),false);
INSERT INTO app.expedientes(estudiante_id,estado_id,id,clave_caso_utf8,incluido_en_estado)
VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000020','4b120000-0000-4000-8000-000000000020',convert_to('CASO_FICTICIO_A','UTF8'),true);
INSERT INTO app.actuaciones (estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status,source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,alcance_caso_utf8)
SELECT estudiante_id,estado_id,expediente_id,'4b130000-0000-4000-8000-000000000020'::uuid,20,version_hash,status,source_id,contrato_clave_utf8,'2',contrato_revision,alcance_instancia_utf8,alcance_caso_utf8 FROM app.actuaciones
WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003';
INSERT INTO app.actuaciones (estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status,source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,alcance_caso_utf8)
SELECT estudiante_id,estado_id,expediente_id,'4b130000-0000-4000-8000-000000000021'::uuid,21,version_hash,status,source_id,contrato_clave_utf8,contrato_version_decimal,repeat('d',64),alcance_instancia_utf8,alcance_caso_utf8 FROM app.actuaciones
WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003';
INSERT INTO app.actuaciones (estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status,source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,alcance_caso_utf8)
SELECT estudiante_id,estado_id,expediente_id,'4b130000-0000-4000-8000-000000000022'::uuid,22,version_hash,status,'OTRO_ID_FICTICIO',contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,alcance_caso_utf8 FROM app.actuaciones
WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003';
INSERT INTO app.actuaciones (estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status,source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,alcance_caso_utf8)
SELECT estudiante_id,estado_id,'4b120000-0000-4000-8000-000000000003','4b130000-0000-4000-8000-000000000023'::uuid,0,version_hash,status,source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,convert_to('CASO_FICTICIO_C','UTF8') FROM app.actuaciones
WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003';
INSERT INTO app.actuaciones (estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status,source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,alcance_caso_utf8)
SELECT estudiante_id,'4b110000-0000-4000-8000-000000000020','4b120000-0000-4000-8000-000000000020','4b130000-0000-4000-8000-000000000024'::uuid,0,version_hash,status,source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,convert_to('INSTANCIA_FICTICIA_B','UTF8'),alcance_caso_utf8 FROM app.actuaciones
WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003';

SET CONSTRAINTS app.actuaciones_orden_uq IMMEDIATE;
DO $casos$
DECLARE prueba record; obtenido text; restriccion text;
BEGIN
    FOR prueba IN SELECT * FROM (VALUES
        ('cabecera_sin_estudiante','23503',$q$INSERT INTO app.estados_reconciliacion VALUES ('4b100000-0000-4000-8000-000000000099','4b110000-0000-4000-8000-000000000099',convert_to('INSTANCIA_FICTICIA','UTF8'),1,'activo',2,2,1,repeat('0',64),false,now())$q$),
        ('cabecera_activa_duplicada','23505',$q$INSERT INTO app.estados_reconciliacion VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000010',convert_to('INSTANCIA_FICTICIA','UTF8'),3,'activo',2,2,1,repeat('0',64),false,now())$q$),
        ('transicion_ocupa_cabecera','23505',$q$INSERT INTO app.estados_reconciliacion VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000011',convert_to('INSTANCIA_FICTICIA','UTF8'),4,'transicion_requerida',2,2,1,repeat('0',64),false,now())$q$),
        ('revision_desconocida','23514',$q$UPDATE app.estados_reconciliacion SET state_revision=3 WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND id='4b110000-0000-4000-8000-000000000001'$q$),
        ('schema_desconocido','23514',$q$UPDATE app.estados_reconciliacion SET schema_version=3 WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND id='4b110000-0000-4000-8000-000000000001'$q$),
        ('fingerprint_desconocido','23514',$q$UPDATE app.estados_reconciliacion SET fingerprint_version=2 WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND id='4b110000-0000-4000-8000-000000000001'$q$),
        ('instancia_demasiado_grande','23514',$q$UPDATE app.estados_reconciliacion SET instancia_utf8=convert_to(repeat('X',513),'UTF8') WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND id='4b110000-0000-4000-8000-000000000001'$q$),
        ('expediente_ajeno','23503',$q$INSERT INTO app.expedientes (estudiante_id,estado_id,id,clave_caso_utf8) VALUES ('4b100000-0000-4000-8000-000000000002','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000099',convert_to('CASO_FICTICIO_AJENO','UTF8'))$q$),
        ('actuacion_ajena','23503',$q$UPDATE app.actuaciones SET estudiante_id='4b100000-0000-4000-8000-000000000002' WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000001'$q$),
        ('alcance_instancia_distinto','23503',$q$UPDATE app.actuaciones SET alcance_instancia_utf8=convert_to('OTRA_INSTANCIA_FICTICIA','UTF8') WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003'$q$),
        ('alcance_caso_distinto','23503',$q$UPDATE app.actuaciones SET alcance_caso_utf8=convert_to('OTRO_CASO_FICTICIO','UTF8') WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003'$q$),
        ('uuid_repetido_entre_casos','23505',$q$INSERT INTO app.actuaciones (estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status) VALUES ('4b100000-0000-4000-8000-000000000001','4b110000-0000-4000-8000-000000000001','4b120000-0000-4000-8000-000000000003','4b130000-0000-4000-8000-000000000001',0,repeat('a',64),'linea_base')$q$),
        ('identidad_estable_repetida_otro_hash','23505',$q$INSERT INTO app.actuaciones SELECT estudiante_id,estado_id,expediente_id,'4b130000-0000-4000-8000-000000000010'::uuid,4,repeat('d',64),status,source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,alcance_caso_utf8 FROM app.actuaciones WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003'$q$),
        ('identidad_parcial','23514',$q$UPDATE app.actuaciones SET source_id='ID_FICTICIO_INCOMPLETO' WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000001'$q$),
        ('anonima_modificada','23514',$q$UPDATE app.actuaciones SET status='modificada' WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000001'$q$),
        ('estado_actuacion_desconocido','23514',$q$UPDATE app.actuaciones SET status='ESTADO_FICTICIO_INVALIDO' WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000001'$q$),
        ('hash_invalido','23514',$q$UPDATE app.actuaciones SET version_hash=repeat('g',64) WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000001'$q$),
        ('hash_nulo','23502',$q$UPDATE app.actuaciones SET version_hash=NULL WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000001'$q$),
        ('orden_negativo','23514',$q$UPDATE app.actuaciones SET orden_registro=-1 WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000001'$q$),
        ('orden_duplicado','23505',$q$UPDATE app.actuaciones SET orden_registro=0 WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000002'$q$),
        ('version_no_canonica','23514',$q$UPDATE app.actuaciones SET contrato_version_decimal='01' WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003'$q$),
        ('version_excesiva','23514',$q$UPDATE app.actuaciones SET contrato_version_decimal=repeat('1',129) WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003'$q$),
        ('clave_contrato_excesiva','23514',$q$UPDATE app.actuaciones SET contrato_clave_utf8=convert_to(repeat('X',513),'UTF8') WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003'$q$),
        ('source_no_ascii','23514',$q$UPDATE app.actuaciones SET source_id='ID_FICTICIO_'||chr(233) WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003'$q$),
        ('grupo_origen_incompleto','23514',$q$UPDATE app.actuaciones SET source_id=NULL WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000003'$q$),
        ('acceso_no_demostrado','23514',$q$UPDATE app_private.accesos_sigac SET estado='verificado' WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001'$q$),
        ('job_terminal_sin_resultado','23514',$q$UPDATE app_private.sincronizaciones SET estado='confirmada' WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND id='4b140000-0000-4000-8000-000000000002'$q$),
        ('dos_jobs_activos','23505',$q$INSERT INTO app_private.sincronizaciones SELECT estudiante_id,estado_id,expediente_id,'4b140000-0000-4000-8000-000000000003'::uuid,'4b150000-0000-4000-8000-000000000003'::uuid,modo,estado,generacion_base,generacion_confirmada,access_epoch,session_epoch,3,worker_id,lease_token,lease_hasta,creado_en,terminado_en FROM app_private.sincronizaciones WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND id='4b140000-0000-4000-8000-000000000002'$q$),
        ('evento_ajeno','23503',$q$UPDATE app.eventos SET estudiante_id='4b100000-0000-4000-8000-000000000002' WHERE estudiante_id='4b100000-0000-4000-8000-000000000001'$q$),
        ('evento_duplicado','23505',$q$INSERT INTO app.eventos SELECT estudiante_id,estado_id,expediente_id,'4b160000-0000-4000-8000-000000000002'::uuid,sincronizacion_id,ordinal,local_id,generacion_resultado,tipo,prioridad,disposicion,creado_en FROM app.eventos WHERE estudiante_id='4b100000-0000-4000-8000-000000000001'$q$),
        ('importacion_incompleta','23514',$q$INSERT INTO app_private.importaciones (estudiante_id,id,idempotency_key,source_sha256,source_bytes,estado) VALUES ('4b100000-0000-4000-8000-000000000001','4b170000-0000-4000-8000-000000000002','4b180000-0000-4000-8000-000000000002',repeat('d',64),10,'confirmada')$q$),
        ('importacion_excesiva','23514',$q$UPDATE app_private.importaciones SET source_bytes=67108865 WHERE estudiante_id='4b100000-0000-4000-8000-000000000001'$q$),
        ('auth_sin_usuario_real','23503',$q$UPDATE app.estudiantes SET auth_subject='4b190000-0000-4000-8000-000000000099' WHERE id='4b100000-0000-4000-8000-000000000001'$q$)
    ) AS pruebas(nombre,esperado,sentencia)
    LOOP
        BEGIN
            EXECUTE prueba.sentencia;
            RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='Se acepto un caso invalido.';
        EXCEPTION WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS obtenido = RETURNED_SQLSTATE;
            GET STACKED DIAGNOSTICS restriccion = CONSTRAINT_NAME;
            IF obtenido <> prueba.esperado THEN
                RAISE EXCEPTION 'Caso %: SQLSTATE esperado %, obtenido %',
                    prueba.nombre,prueba.esperado,obtenido;
            END IF;
            IF prueba.nombre='identidad_estable_repetida_otro_hash'
               AND restriccion<>'una_identidad_estable_por_alcance' THEN
                RAISE EXCEPTION 'Colision de identidad por restriccion distinta de la esperada.';
            END IF;
            IF prueba.nombre IN ('cabecera_activa_duplicada','transicion_ocupa_cabecera')
               AND restriccion<>'una_cabecera_viva' THEN
                RAISE EXCEPTION 'Colision de cabecera por restriccion distinta de la esperada.';
            END IF;
        END;
    END LOOP;
    IF (SELECT count(*) FROM app.actuaciones WHERE estudiante_id='4b100000-0000-4000-8000-000000000001'
        AND version_hash=repeat('a',64)) <> 2 THEN
        RAISE EXCEPTION 'Se perdio multiplicidad anonima.';
    END IF;
END;
$casos$;

-- Reordenar temporalmente es valido, el orden final sigue siendo unico.
SET CONSTRAINTS app.actuaciones_orden_uq DEFERRED;
UPDATE app.actuaciones SET orden_registro=1 WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000001';
UPDATE app.actuaciones SET orden_registro=0 WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000002';
SET CONSTRAINTS app.actuaciones_orden_uq IMMEDIATE;
-- Limite deliberado: SQL permite huecos; 4B.2 debe rechazar estado final no contiguo.
UPDATE app.actuaciones SET orden_registro=100 WHERE estudiante_id='4b100000-0000-4000-8000-000000000001' AND estado_id='4b110000-0000-4000-8000-000000000001' AND expediente_id='4b120000-0000-4000-8000-000000000001' AND local_id='4b130000-0000-4000-8000-000000000001';
-- Datos/proveniencia/contrato de prueba no conceden autorizacion real.
ROLLBACK;
