\set ON_ERROR_STOP on
-- FUTURO: solo tras autorizacion. Prueba real de insercion, no estimacion ejecutada.
-- Perfil PostgreSQL 17 / BLCKSZ 8192 / UTF8; no extensiones ni permisos nuevos.
BEGIN;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '3s';
SELECT current_setting('server_version') AS version,
       current_setting('block_size') AS block_size,
       current_setting('server_encoding') AS encoding;
DO $limites$
DECLARE
    maximo text; decimal_maximo text; caso bytea;
BEGIN
    IF current_setting('server_version_num')::integer / 10000 <> 17
       OR current_setting('block_size')::integer <> 8192
       OR current_setting('server_encoding') <> 'UTF8' THEN
        RAISE EXCEPTION 'Perfil distinto del calculado: revisar antes de probar limites.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=CURRENT_USER AND (rolsuper OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Usar administrador ya autorizado, sin cambiar privilegios.';
    END IF;
    SELECT string_agg(md5('FICTICIO_BTREE:'||g::text),'' ORDER BY g)
    INTO maximo FROM generate_series(1,16) g;
    decimal_maximo := '1'||substr(translate(maximo,'abcdef','123456'),1,127);
    SELECT convert_to(string_agg(chr(128512 + g % 80),'' ORDER BY g),'UTF8')
    INTO caso FROM generate_series(1,128) g;
    IF octet_length(maximo)<>512 OR octet_length(caso)<>512
       OR length(decimal_maximo)<>128 THEN
        RAISE EXCEPTION 'Generador ficticio no alcanzo maximos.';
    END IF;
    -- PK preexistente aborta: no adoptar filas ni limpiar datos ajenos.
    INSERT INTO app.estudiantes(id) VALUES ('4b2f0000-0000-4000-8000-000000000001');
    INSERT INTO app.estados_reconciliacion
    (estudiante_id,id,instancia_utf8,epoca,situacion,schema_version,state_revision,fingerprint_version,trust_policy,migrated_from_v1)
    VALUES ('4b2f0000-0000-4000-8000-000000000001','4b2f0000-0000-4000-8000-000000000002',
            convert_to(maximo,'UTF8'),1,'activo',2,2,1,repeat('0',64),false);
    INSERT INTO app.expedientes(estudiante_id,estado_id,id,clave_caso_utf8,incluido_en_estado)
    VALUES ('4b2f0000-0000-4000-8000-000000000001','4b2f0000-0000-4000-8000-000000000002',
            '4b2f0000-0000-4000-8000-000000000003',caso,true);
    INSERT INTO app.actuaciones
    (estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status,
     source_id,contrato_clave_utf8,contrato_version_decimal,contrato_revision,alcance_instancia_utf8,alcance_caso_utf8)
    VALUES ('4b2f0000-0000-4000-8000-000000000001','4b2f0000-0000-4000-8000-000000000002',
            '4b2f0000-0000-4000-8000-000000000003','4b2f0000-0000-4000-8000-000000000004',0,repeat('a',64),'linea_base',
            substr(maximo,1,128),convert_to(maximo,'UTF8'),decimal_maximo,
            substr(maximo,1,64),convert_to(maximo,'UTF8'),caso);
END;
$limites$;
SET CONSTRAINTS ALL IMMEDIATE;
-- pg_column_size de una fila NO mide la tupla B-tree: no usarlo como prueba del indice.
SELECT octet_length(contrato_clave_utf8) AS contrato_bytes,
       octet_length(source_id) AS source_bytes,
       length(contrato_version_decimal) AS version_digitos,
       octet_length(alcance_caso_utf8) AS caso_bytes
FROM app.actuaciones WHERE estudiante_id='4b2f0000-0000-4000-8000-000000000001';
ROLLBACK;
