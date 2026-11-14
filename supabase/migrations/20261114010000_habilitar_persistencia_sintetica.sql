-- 4B.2-B. Preparada, NO aplicada a Supabase remoto. Conserva las ocho tablas.
-- Solo acceso sintetico atestado por operador; no habilita integracion SIGAC.
BEGIN;
CREATE ROLE tinotify_guard_reader NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tinotify_state_writer NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
-- Bootstrap explicito del operador: transferir propiedad y cerrar ACL requiere
-- SET e INHERIT, no solo el ADMIN automatico de CREATEROLE en PostgreSQL 17.
-- Nunca se concede esta membresia a conexiones operativas. Se retira abajo.
GRANT tinotify_guard_reader,tinotify_state_writer TO CURRENT_USER WITH INHERIT TRUE, SET TRUE;
GRANT USAGE ON SCHEMA app,app_private TO tinotify_guard_reader,tinotify_state_writer;
-- Necesario para transferir propiedad incluso con administrador NOSUPERUSER.
-- Se revoca antes de COMMIT; no hay miembros operativos ni LOGIN.
GRANT CREATE ON SCHEMA app_private TO tinotify_guard_reader,tinotify_state_writer;
GRANT SELECT ON app.estudiantes,app.estados_reconciliacion,app.expedientes,
    app.actuaciones,app.eventos,app_private.accesos_sigac TO tinotify_guard_reader;
GRANT SELECT ON app.estudiantes,app.estados_reconciliacion,app.expedientes,
    app.actuaciones,app.eventos,app_private.accesos_sigac,app_private.sincronizaciones TO tinotify_state_writer;
GRANT INSERT,UPDATE ON app.estados_reconciliacion,app.expedientes,app.actuaciones,
    app.eventos,app_private.sincronizaciones TO tinotify_state_writer;
-- UPDATE de estas claves solo permite SELECT FOR UPDATE en funciones cerradas.
-- Servicios sin DML ni membresia de estos propietarios; no hay funciones que
-- modifiquen perfiles/evidencias. El writer no obtiene UPDATE de sus contenidos.
GRANT UPDATE(id) ON app.estudiantes TO tinotify_state_writer;
GRANT UPDATE(estudiante_id) ON app_private.accesos_sigac TO tinotify_state_writer;

CREATE POLICY perfil_reader ON app.estudiantes FOR SELECT TO tinotify_guard_reader
USING (auth_subject::text=nullif(current_setting('tinotify.subject',true),'') AND estado='activo');
CREATE POLICY perfil_writer_lectura ON app.estudiantes FOR SELECT TO tinotify_state_writer
USING (auth_subject::text=nullif(current_setting('tinotify.subject',true),'') AND estado='activo');
CREATE POLICY perfil_writer_bloqueo ON app.estudiantes FOR UPDATE TO tinotify_state_writer
USING (auth_subject::text=nullif(current_setting('tinotify.subject',true),'') AND estado='activo')
WITH CHECK (auth_subject::text=nullif(current_setting('tinotify.subject',true),'') AND estado='activo');

CREATE FUNCTION app_private.actor() RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE actor_id uuid;
BEGIN
    SELECT id INTO STRICT actor_id FROM app.estudiantes;
    RETURN actor_id;
EXCEPTION WHEN no_data_found THEN
    RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Contexto no autorizado';
END;
$fn$;
ALTER FUNCTION app_private.actor() OWNER TO tinotify_guard_reader;
REVOKE ALL ON FUNCTION app_private.actor() FROM PUBLIC;
REVOKE ALL ON FUNCTION app_private.actor() FROM anon,authenticated,service_role,tinotify_api,tinotify_sync,tinotify_notifications;
GRANT EXECUTE ON FUNCTION app_private.actor() TO tinotify_state_writer;

-- Listas constantes de la migracion, nunca identificadores/SQL del cliente.
DO $policies$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['app.estados_reconciliacion','app.expedientes','app.actuaciones','app.eventos','app_private.accesos_sigac'] LOOP
        EXECUTE format('CREATE POLICY lectura_contexto ON %s FOR SELECT TO tinotify_guard_reader USING (estudiante_id=app_private.actor())',t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['app.estados_reconciliacion','app.expedientes','app.actuaciones','app.eventos','app_private.sincronizaciones'] LOOP
        EXECUTE format('CREATE POLICY writer_lectura ON %s FOR SELECT TO tinotify_state_writer USING (estudiante_id=app_private.actor())',t);
        EXECUTE format('CREATE POLICY writer_insert ON %s FOR INSERT TO tinotify_state_writer WITH CHECK (estudiante_id=app_private.actor())',t);
        EXECUTE format('CREATE POLICY writer_update ON %s FOR UPDATE TO tinotify_state_writer USING (estudiante_id=app_private.actor()) WITH CHECK (estudiante_id=app_private.actor())',t);
    END LOOP;
END;
$policies$;
CREATE POLICY acceso_writer_lectura ON app_private.accesos_sigac FOR SELECT TO tinotify_state_writer
USING (estudiante_id=app_private.actor());
CREATE POLICY acceso_writer_bloqueo ON app_private.accesos_sigac FOR UPDATE TO tinotify_state_writer
USING (estudiante_id=app_private.actor()) WITH CHECK (estudiante_id=app_private.actor());

CREATE FUNCTION app_private.capacidad(cap text) RETURNS void LANGUAGE plpgsql
SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
    IF cap NOT IN ('tinotify_api','tinotify_sync','tinotify_notifications')
       OR NOT pg_has_role(session_user,cap,'USAGE')
       OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname=session_user
           AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication))
       OR EXISTS (SELECT 1 FROM pg_roles p
           WHERE (p.rolsuper OR p.rolbypassrls OR p.rolcreatedb OR p.rolcreaterole
             OR p.rolname IN ('tinotify_guard_reader','tinotify_state_writer')
             OR p.oid IN (SELECT c.relowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname IN ('app','app_private')))
             AND pg_has_role(session_user,p.oid,'MEMBER'))
       OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname IN ('app','app_private') AND c.relkind IN ('r','p','v','m','f')
           AND (has_table_privilege(session_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
             OR has_any_column_privilege(session_user,c.oid,'SELECT,INSERT,UPDATE,REFERENCES'))) THEN
        RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Capacidad de servicio no autorizada';
    END IF;
END;
$fn$;
ALTER FUNCTION app_private.capacidad(text) OWNER TO tinotify_guard_reader;
REVOKE ALL ON FUNCTION app_private.capacidad(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_private.capacidad(text) FROM anon,authenticated,service_role,tinotify_api,tinotify_sync,tinotify_notifications;
GRANT EXECUTE ON FUNCTION app_private.capacidad(text) TO tinotify_state_writer;

CREATE FUNCTION app_private.acceso(h uuid,c uuid,binding uuid) RETURNS void LANGUAGE plpgsql
SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_private.accesos_sigac
        WHERE estudiante_id=app_private.actor() AND estado_id=h AND expediente_id=c
          AND estado='verificado' AND fuente='simulador' AND session_binding_id=binding
          AND session_epoch>0 AND access_epoch>0 AND valido_hasta>clock_timestamp()) THEN
        RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Acceso sintetico no verificado o caducado';
    END IF;
END;
$fn$;
ALTER FUNCTION app_private.acceso(uuid,uuid,uuid) OWNER TO tinotify_guard_reader;
REVOKE ALL ON FUNCTION app_private.acceso(uuid,uuid,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_private.acceso(uuid,uuid,uuid) FROM anon,authenticated,service_role,tinotify_api,tinotify_sync,tinotify_notifications;
GRANT EXECUTE ON FUNCTION app_private.acceso(uuid,uuid,uuid) TO tinotify_state_writer;

CREATE FUNCTION app_private.seguir(inst bytea,caso bytea,politica text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE a uuid; h app.estados_reconciliacion; c app.expedientes;
BEGIN
    IF pg_has_role(session_user,'tinotify_sync','USAGE') THEN
        PERFORM app_private.capacidad('tinotify_sync');
    ELSE PERFORM app_private.capacidad('tinotify_api'); END IF;
    a:=app_private.actor();
    PERFORM 1 FROM app.estudiantes WHERE id=a FOR UPDATE;
    INSERT INTO app.estados_reconciliacion
        (estudiante_id,id,instancia_utf8,epoca,situacion,schema_version,state_revision,fingerprint_version,trust_policy,migrated_from_v1)
    VALUES(a,gen_random_uuid(),inst,1,'activo',2,2,1,politica,false)
    ON CONFLICT (estudiante_id,instancia_utf8) WHERE situacion IN ('activo','transicion_requerida') DO NOTHING;
    SELECT * INTO STRICT h FROM app.estados_reconciliacion
    WHERE estudiante_id=a AND instancia_utf8=inst AND situacion IN ('activo','transicion_requerida') FOR UPDATE;
    IF h.situacion<>'activo' OR h.trust_policy<>politica THEN
        RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Transicion explicita de politica requerida';
    END IF;
    INSERT INTO app.expedientes(estudiante_id,estado_id,id,clave_caso_utf8)
    VALUES(a,h.id,gen_random_uuid(),caso) ON CONFLICT (estudiante_id,estado_id,clave_caso_utf8) DO NOTHING;
    SELECT * INTO STRICT c FROM app.expedientes
    WHERE estudiante_id=a AND estado_id=h.id AND clave_caso_utf8=caso FOR UPDATE;
    RETURN jsonb_build_object('estado_id',h.id,'expediente_id',c.id);
END;
$fn$;

CREATE FUNCTION app_private.reservar(h uuid,c uuid,clave uuid,worker uuid,binding uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE a uuid; e app.expedientes; acceso app_private.accesos_sigac; j app_private.sincronizaciones;
BEGIN
    PERFORM app_private.capacidad('tinotify_sync');
    a:=app_private.actor();
    PERFORM 1 FROM app.estudiantes WHERE id=a FOR UPDATE;
    PERFORM 1 FROM app.estados_reconciliacion WHERE estudiante_id=a AND id=h AND situacion='activo' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Seguimiento no autorizado'; END IF;
    SELECT * INTO STRICT e FROM app.expedientes WHERE estudiante_id=a AND estado_id=h AND id=c FOR UPDATE;
    SELECT * INTO acceso FROM app_private.accesos_sigac
    WHERE estudiante_id=a AND estado_id=h AND expediente_id=c FOR UPDATE;
    PERFORM app_private.acceso(h,c,binding);
    SELECT * INTO j FROM app_private.sincronizaciones
    WHERE estudiante_id=a AND estado_id=h AND expediente_id=c AND idempotency_key=clave FOR UPDATE;
    IF FOUND THEN
        IF j.estado='confirmada' THEN
            RETURN jsonb_build_object('id',j.id,'estado',j.estado,'token',NULL,'generacion',j.generacion_confirmada);
        END IF;
        RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Clave de operacion ya reservada; revisar recibo';
    END IF;
    UPDATE app_private.sincronizaciones SET estado='expirada',terminado_en=clock_timestamp()
    WHERE estudiante_id=a AND estado_id=h AND expediente_id=c AND estado IN ('reservada','ejecutando')
      AND lease_hasta<=clock_timestamp();
    UPDATE app.expedientes SET fencing=fencing+1 WHERE estudiante_id=a AND estado_id=h AND id=c RETURNING * INTO e;
    INSERT INTO app_private.sincronizaciones
    (estudiante_id,estado_id,expediente_id,id,idempotency_key,modo,estado,generacion_base,access_epoch,session_epoch,fencing,worker_id,lease_token,lease_hasta)
    VALUES(a,h,c,gen_random_uuid(),clave,'sintetico','ejecutando',e.generacion,acceso.access_epoch,acceso.session_epoch,
           e.fencing,worker,gen_random_uuid(),clock_timestamp()+interval '60 seconds') RETURNING * INTO j;
    RETURN jsonb_build_object('id',j.id,'estado',j.estado,'token',j.lease_token,'generacion',j.generacion_base);
END;
$fn$;

CREATE FUNCTION app_private.leer_caso(h uuid,c uuid,binding uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e app.expedientes; filas jsonb;
BEGIN
    PERFORM app_private.capacidad('tinotify_sync');
    PERFORM app_private.acceso(h,c,binding);
    SELECT * INTO STRICT e FROM app.expedientes WHERE estudiante_id=app_private.actor() AND estado_id=h AND id=c;
    IF NOT e.incluido_en_estado THEN RETURN NULL; END IF;
    SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY orden_registro),'[]') INTO filas
    FROM app.actuaciones r WHERE estudiante_id=e.estudiante_id AND estado_id=h AND expediente_id=c;
    RETURN filas;
END;
$fn$;

CREATE FUNCTION app_private.confirmar(h uuid,c uuid,job uuid,token uuid,base bigint,registros jsonb,eventos jsonb,politica text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE a uuid; cab app.estados_reconciliacion; e app.expedientes; acceso app_private.accesos_sigac;
        j app_private.sincronizaciones; r app.actuaciones; item jsonb; n bigint:=0;
BEGIN
    PERFORM app_private.capacidad('tinotify_sync');
    a:=app_private.actor();
    PERFORM 1 FROM app.estudiantes WHERE id=a FOR UPDATE;
    SELECT * INTO STRICT cab FROM app.estados_reconciliacion WHERE estudiante_id=a AND id=h FOR UPDATE;
    SELECT * INTO STRICT e FROM app.expedientes WHERE estudiante_id=a AND estado_id=h AND id=c FOR UPDATE;
    SELECT * INTO STRICT acceso FROM app_private.accesos_sigac WHERE estudiante_id=a AND estado_id=h AND expediente_id=c FOR UPDATE;
    SELECT * INTO STRICT j FROM app_private.sincronizaciones WHERE estudiante_id=a AND estado_id=h AND expediente_id=c AND id=job FOR UPDATE;
    PERFORM app_private.acceso(h,c,acceso.session_binding_id);
    IF cab.situacion<>'activo' OR cab.trust_policy IS DISTINCT FROM politica OR j.estado<>'ejecutando'
       OR j.modo<>'sintetico' OR j.lease_token IS DISTINCT FROM token OR j.lease_hasta<=clock_timestamp()
       OR j.generacion_base<>base OR e.generacion<>base OR j.fencing<>e.fencing
       OR j.access_epoch<>acceso.access_epoch OR j.session_epoch<>acceso.session_epoch THEN
        RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='Reserva o generacion no vigente';
    END IF;
    IF jsonb_typeof(registros) IS DISTINCT FROM 'array' OR jsonb_typeof(eventos) IS DISTINCT FROM 'array'
       OR jsonb_array_length(registros)>100000 OR jsonb_array_length(eventos)>100000 THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Cuota o formato de lote no valido';
    END IF;
    IF (SELECT count(DISTINCT x->>'local_id') FROM jsonb_array_elements(registros) x)<>jsonb_array_length(registros) THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Identidades locales repetidas';
    END IF;
    IF EXISTS (SELECT 1 FROM app.actuaciones anterior WHERE estudiante_id=a AND estado_id=h AND expediente_id=c
        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(registros) x WHERE (x->>'local_id')::uuid=anterior.local_id)) THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='No se permite eliminar actuaciones por ausencia';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(registros) LOOP
        r:=jsonb_populate_record(NULL::app.actuaciones,item);
        IF r.orden_registro<>n THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Orden de registros no contiguo'; END IF;
        IF EXISTS (SELECT 1 FROM app.actuaciones viejo WHERE estudiante_id=a AND estado_id=h AND expediente_id=c AND local_id=r.local_id
            AND ROW(viejo.source_id,viejo.contrato_clave_utf8,viejo.contrato_version_decimal,viejo.contrato_revision,viejo.alcance_instancia_utf8,viejo.alcance_caso_utf8)
            IS DISTINCT FROM ROW(r.source_id,r.contrato_clave_utf8,r.contrato_version_decimal,r.contrato_revision,r.alcance_instancia_utf8,r.alcance_caso_utf8)) THEN
            RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Identidad persistente inmutable';
        END IF;
        INSERT INTO app.actuaciones VALUES(a,h,c,r.local_id,r.orden_registro,r.version_hash,r.status,r.source_id,
            r.contrato_clave_utf8,r.contrato_version_decimal,r.contrato_revision,r.alcance_instancia_utf8,r.alcance_caso_utf8)
        ON CONFLICT (estudiante_id,estado_id,expediente_id,local_id) DO UPDATE
        SET orden_registro=EXCLUDED.orden_registro,version_hash=EXCLUDED.version_hash,status=EXCLUDED.status;
        n:=n+1;
    END LOOP;
    SET CONSTRAINTS app.actuaciones_orden_uq IMMEDIATE;
    n:=0;
    FOR item IN SELECT value FROM jsonb_array_elements(eventos) LOOP
        INSERT INTO app.eventos(estudiante_id,estado_id,expediente_id,id,sincronizacion_id,ordinal,local_id,generacion_resultado,tipo,prioridad)
        VALUES(a,h,c,gen_random_uuid(),job,n,(item->>'local_id')::uuid,base+1,item->>'tipo',item->>'prioridad');
        n:=n+1;
    END LOOP;
    UPDATE app.expedientes SET generacion=base+1,incluido_en_estado=true WHERE estudiante_id=a AND estado_id=h AND id=c;
    UPDATE app_private.sincronizaciones SET estado='confirmada',generacion_confirmada=base+1,terminado_en=clock_timestamp(),
        worker_id=NULL,lease_token=NULL,lease_hasta=NULL WHERE estudiante_id=a AND estado_id=h AND expediente_id=c AND id=job;
    RETURN base+1;
END;
$fn$;

CREATE FUNCTION app_private.exportar(inst bytea,binding uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE cab app.estados_reconciliacion; e app.expedientes; casos jsonb:='[]'; filas jsonb;
BEGIN
    IF pg_has_role(session_user,'tinotify_sync','USAGE') THEN PERFORM app_private.capacidad('tinotify_sync');
    ELSE PERFORM app_private.capacidad('tinotify_api'); END IF;
    SELECT * INTO cab FROM app.estados_reconciliacion WHERE estudiante_id=app_private.actor()
    AND instancia_utf8=inst AND situacion IN ('activo','transicion_requerida');
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF cab.situacion<>'activo' THEN RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Transicion requerida'; END IF;
    FOR e IN SELECT * FROM app.expedientes WHERE estudiante_id=cab.estudiante_id AND estado_id=cab.id AND incluido_en_estado LOOP
        PERFORM app_private.acceso(cab.id,e.id,binding);
        SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY orden_registro),'[]') INTO filas
        FROM app.actuaciones r WHERE estudiante_id=cab.estudiante_id AND estado_id=cab.id AND expediente_id=e.id;
        casos:=casos||jsonb_build_array(jsonb_build_object('clave',e.clave_caso_utf8,'records',filas));
    END LOOP;
    RETURN jsonb_build_object('cabecera',to_jsonb(cab),'casos',casos);
END;
$fn$;

CREATE FUNCTION app_private.pendientes(binding uuid,limite integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e app.eventos; avisos jsonb:='[]';
BEGIN
    IF pg_has_role(session_user,'tinotify_notifications','USAGE') THEN PERFORM app_private.capacidad('tinotify_notifications');
    ELSE PERFORM app_private.capacidad('tinotify_api'); END IF;
    IF limite NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Limite de consulta no valido'; END IF;
    FOR e IN SELECT * FROM app.eventos WHERE estudiante_id=app_private.actor() AND disposicion='pendiente'
        ORDER BY CASE prioridad WHEN 'alta' THEN 0 ELSE 1 END,creado_en,id LIMIT limite LOOP
        PERFORM app_private.acceso(e.estado_id,e.expediente_id,binding);
        avisos:=avisos||jsonb_build_array(jsonb_build_object('id',e.id,'tipo',e.tipo,'prioridad',e.prioridad));
    END LOOP;
    RETURN avisos;
END;
$fn$;

CREATE FUNCTION app_private.procesar_aviso(evento uuid,binding uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e app.eventos;
BEGIN
    PERFORM app_private.capacidad('tinotify_notifications');
    SELECT * INTO STRICT e FROM app.eventos WHERE estudiante_id=app_private.actor() AND id=evento;
    PERFORM 1 FROM app.estudiantes WHERE id=e.estudiante_id FOR UPDATE;
    PERFORM 1 FROM app.estados_reconciliacion WHERE estudiante_id=e.estudiante_id AND id=e.estado_id FOR UPDATE;
    PERFORM 1 FROM app.expedientes WHERE estudiante_id=e.estudiante_id AND estado_id=e.estado_id AND id=e.expediente_id FOR UPDATE;
    PERFORM 1 FROM app_private.accesos_sigac WHERE estudiante_id=e.estudiante_id AND estado_id=e.estado_id AND expediente_id=e.expediente_id FOR UPDATE;
    PERFORM app_private.acceso(e.estado_id,e.expediente_id,binding);
    UPDATE app.eventos SET disposicion='procesado' WHERE estudiante_id=e.estudiante_id AND id=evento AND disposicion='pendiente';
END;
$fn$;

-- Todas las funciones de servicio tienen propietario interno sin BYPASSRLS,
-- search_path fijo y EXECUTE por firma. Nunca son propietarios de las tablas.
DO $cierre$
DECLARE firma text;
BEGIN
    FOREACH firma IN ARRAY ARRAY[
        'seguir(bytea,bytea,text)','reservar(uuid,uuid,uuid,uuid,uuid)','leer_caso(uuid,uuid,uuid)',
        'confirmar(uuid,uuid,uuid,uuid,bigint,jsonb,jsonb,text)','exportar(bytea,uuid)',
        'pendientes(uuid,integer)','procesar_aviso(uuid,uuid)'] LOOP
        EXECUTE 'ALTER FUNCTION app_private.'||firma||' OWNER TO tinotify_state_writer';
        EXECUTE 'REVOKE ALL ON FUNCTION app_private.'||firma||' FROM PUBLIC,anon,authenticated,service_role,tinotify_api,tinotify_sync,tinotify_notifications';
    END LOOP;
END;
$cierre$;
GRANT USAGE ON SCHEMA app_private TO tinotify_api,tinotify_sync,tinotify_notifications;
GRANT EXECUTE ON FUNCTION app_private.seguir(bytea,bytea,text),app_private.exportar(bytea,uuid) TO tinotify_api,tinotify_sync;
GRANT EXECUTE ON FUNCTION app_private.reservar(uuid,uuid,uuid,uuid,uuid),app_private.leer_caso(uuid,uuid,uuid),
    app_private.confirmar(uuid,uuid,uuid,uuid,bigint,jsonb,jsonb,text) TO tinotify_sync;
GRANT EXECUTE ON FUNCTION app_private.pendientes(uuid,integer) TO tinotify_api,tinotify_notifications;
GRANT EXECUTE ON FUNCTION app_private.procesar_aviso(uuid,uuid) TO tinotify_notifications;
-- importaciones permanece cerrada: no se habilita importacion ni se infiere
-- pertenencia/confianza desde JSON. No funciones ni permisos para modo real.
REVOKE CREATE ON SCHEMA app_private FROM tinotify_guard_reader,tinotify_state_writer;
REVOKE tinotify_guard_reader,tinotify_state_writer FROM CURRENT_USER;
-- Fallar ante grants residuales/defaults o membresias inesperadas, no repararlos
-- concediendo privilegios ni aceptando acceso directo de servicios.
DO $auditoria$
DECLARE rol text; tabla regclass;
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) acl
        LEFT JOIN pg_roles grantee ON grantee.oid=acl.grantee
        WHERE n.nspname='app_private' AND acl.grantee<>p.proowner
          AND NOT coalesce(acl.privilege_type='EXECUTE' AND NOT acl.is_grantable AND (
              (p.proname IN ('actor','capacidad','acceso') AND grantee.rolname='tinotify_state_writer')
              OR (p.proname IN ('seguir','exportar') AND grantee.rolname IN ('tinotify_api','tinotify_sync'))
              OR (p.proname IN ('reservar','leer_caso','confirmar') AND grantee.rolname='tinotify_sync')
              OR (p.proname='pendientes' AND grantee.rolname IN ('tinotify_api','tinotify_notifications'))
              OR (p.proname='procesar_aviso' AND grantee.rolname='tinotify_notifications')
          ),false)
    ) THEN RAISE EXCEPTION 'ACL inesperada en funciones; revisar defaults'; END IF;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role','tinotify_api','tinotify_sync','tinotify_notifications'] LOOP
        IF pg_has_role(rol,'tinotify_guard_reader','MEMBER') OR pg_has_role(rol,'tinotify_state_writer','MEMBER') THEN
            RAISE EXCEPTION 'Un servicio puede asumir propietario interno';
        END IF;
        FOREACH tabla IN ARRAY ARRAY['app.estudiantes'::regclass,'app.estados_reconciliacion'::regclass,
            'app.expedientes'::regclass,'app.actuaciones'::regclass,'app.eventos'::regclass,
            'app_private.accesos_sigac'::regclass,'app_private.sincronizaciones'::regclass,'app_private.importaciones'::regclass] LOOP
            IF has_table_privilege(rol,tabla,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
               OR has_any_column_privilege(rol,tabla,'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'Permiso directo residual de servicio';
            END IF;
        END LOOP;
    END LOOP;
END;
$auditoria$;
COMMIT;
