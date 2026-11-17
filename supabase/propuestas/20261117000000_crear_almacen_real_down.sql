-- Reversion de 20261117000000_crear_almacen_real. NO es una migracion de la CLI (vive en supabase/propuestas).
-- Requiere autorizacion explicita. Borra solo el esquema tinotify_real (sus 7 tablas) y el rol de grupo tinotify_real_app.
-- ATENCION: elimina las credenciales cifradas, el estado del monitor y los dispositivos; el monitor volveria a empezar
-- con una linea base nueva. No toca ningun otro esquema (app, app_private, app_fixture, tinotify_sintetico, auth...).
-- Funciona con un administrador NOSUPERUSER con CREATEROLE (el de Supabase): no depende de superusuario, de BYPASSRLS ni de DROP OWNED.
-- Antes: eliminar el login operativo (DROP ROLE <login>); si sigue habiendo un miembro real, se niega sin borrar nada.
-- Todo es una sola transaccion: cualquier fallo (precondicion, dependencia externa, permisos) la revierte entera.
-- Un codigo de salida distinto de cero NO prueba por si solo que se revirtio: verifica siempre el estado remoto.
-- Despues (solo si la migracion se registro en el historial): supabase migration repair --status reverted 20261117000000
BEGIN;
DO $precondiciones$
DECLARE
    esquema oid := to_regnamespace('tinotify_real');
BEGIN
    IF current_setting('server_version_num')::integer < 160000 THEN
        RAISE EXCEPTION 'Reversion revisada para PostgreSQL 16 o superior (membresias con ADMIN automatico); revisar a mano.';
    END IF;
    -- Identidad del esquema por CATALOGOS (las filas de entorno estan bajo RLS forzado): comentario exacto de la migracion,
    -- propietario alcanzable y contenido exactamente el esperado.
    IF esquema IS NULL
       OR obj_description(esquema, 'pg_namespace')
          IS DISTINCT FROM 'Tinotify: estado del monitor REAL (huellas con clave, credenciales cifradas). Nunca expuesto por la Data API.' THEN
        RAISE EXCEPTION 'El esquema real no existe o no es el de esta migracion; no se borra nada.';
    END IF;
    IF NOT pg_has_role(current_user, (SELECT nspowner FROM pg_namespace WHERE oid = esquema), 'MEMBER') THEN
        RAISE EXCEPTION 'La identidad actual no es la propietaria del esquema real; no se borra nada.';
    END IF;
    IF (SELECT array_agg(c.relname::text ORDER BY c.relname) FROM pg_class c WHERE c.relnamespace = esquema
            AND c.relkind NOT IN ('i', 'I', 'c', 't'))   -- indices, tipos compuestos y TOAST son parte de las tablas
       IS DISTINCT FROM ARRAY['avisos', 'credenciales', 'dispositivos', 'ejecuciones', 'entorno', 'estado_expediente', 'huellas']
       OR EXISTS (SELECT 1 FROM pg_proc p WHERE p.pronamespace = esquema)
       OR EXISTS (SELECT 1 FROM pg_type t WHERE t.typnamespace = esquema AND t.typtype NOT IN ('c', 'b')) THEN
        RAISE EXCEPTION 'El esquema real contiene objetos distintos de los de la migracion; no se borra nada.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tinotify_real_app') THEN
        RAISE EXCEPTION 'No existe el rol tinotify_real_app; no se borra nada.';
    END IF;
    -- PostgreSQL 16+ concede al CREATEROLE que creo un rol la membresia ADMIN *sin* SET ni INHERIT: no es un miembro real.
    -- Cualquier otra concesion (SET, INHERIT o sin ADMIN) es un login o servicio asociado y bloquea la reversion.
    IF EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.roleid = 'tinotify_real_app'::regrole
               AND (m.inherit_option OR m.set_option OR NOT m.admin_option)) THEN
        RAISE EXCEPTION 'Aun hay roles miembros de tinotify_real_app; eliminarlos antes.';
    END IF;
END;
$precondiciones$;
-- Operaciones explicitas y SIN CASCADE: si algo ajeno depende de estos objetos, el DROP falla y la transaccion entera se
-- revierte en vez de arrastrar objetos desconocidos.
DROP TABLE tinotify_real.huellas, tinotify_real.estado_expediente, tinotify_real.avisos, tinotify_real.ejecuciones,
           tinotify_real.dispositivos, tinotify_real.credenciales, tinotify_real.entorno;
DROP SCHEMA tinotify_real;
DROP ROLE tinotify_real_app;
DO $verificacion$
BEGIN
    IF to_regnamespace('tinotify_real') IS NOT NULL
       OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tinotify_real_app') THEN
        RAISE EXCEPTION 'La reversion no dejo el estado esperado; se revierte todo.';
    END IF;
END;
$verificacion$;
COMMIT;
