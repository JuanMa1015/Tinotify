-- Reversion de 20261115000000_crear_almacen_sintetico. NO es una migracion de la CLI (vive en supabase/propuestas).
-- Requiere autorizacion explicita. Borra solo el esquema tinotify_sintetico (sus 5 tablas y 2 funciones) y el rol de grupo
-- tinotify_sintetico_app. Funciona con un administrador NOSUPERUSER con CREATEROLE (el de Supabase): no depende de
-- superusuario, de BYPASSRLS ni de DROP OWNED.
-- Antes: eliminar el login operativo (DROP ROLE <login>); si sigue habiendo un miembro real, se niega sin borrar nada.
-- Todo es una sola transaccion: cualquier fallo (precondicion, dependencia externa, permisos) la revierte entera.
-- Un codigo de salida distinto de cero NO prueba por si solo que se revirtio (p. ej. la conexion pudo caer despues del
-- COMMIT): verifica siempre el estado remoto con la consulta de solo lectura de docs/despliegue-sintetico-render.md.
-- Despues (solo si la migracion se registro en el historial): supabase migration repair --status reverted 20261115000000
BEGIN;
DO $precondiciones$
DECLARE
    esquema oid := to_regnamespace('tinotify_sintetico');
BEGIN
    IF current_setting('server_version_num')::integer < 160000 THEN
        RAISE EXCEPTION 'Reversion revisada para PostgreSQL 16 o superior (membresias con ADMIN automatico); revisar a mano.';
    END IF;
    -- Identidad del esquema por CATALOGOS (las filas de entorno estan bajo RLS forzado y un administrador sin
    -- BYPASSRLS no las ve): comentario exacto de la migracion, propietario alcanzable y contenido exactamente el esperado.
    IF esquema IS NULL
       OR obj_description(esquema, 'pg_namespace')
          IS DISTINCT FROM 'Tinotify: datos FICTICIOS del backend sintetico. Nunca expuesto por la Data API.' THEN
        RAISE EXCEPTION 'El esquema sintetico no existe o no es el de esta migracion; no se borra nada.';
    END IF;
    IF NOT pg_has_role(current_user, (SELECT nspowner FROM pg_namespace WHERE oid = esquema), 'MEMBER') THEN
        RAISE EXCEPTION 'La identidad actual no es la propietaria del esquema sintetico; no se borra nada.';
    END IF;
    IF (SELECT array_agg(c.relname::text ORDER BY c.relname) FROM pg_class c WHERE c.relnamespace = esquema
            AND c.relkind NOT IN ('i', 'I', 'c', 't'))   -- indices, tipos compuestos y TOAST son parte de las tablas
       IS DISTINCT FROM ARRAY['actuaciones', 'casos', 'entorno', 'monitor_estado', 'novedades']
       OR (SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p WHERE p.pronamespace = esquema)
       IS DISTINCT FROM ARRAY['limitar_casos', 'limitar_novedades']
       OR EXISTS (SELECT 1 FROM pg_type t WHERE t.typnamespace = esquema AND t.typtype NOT IN ('c', 'b')) THEN
        RAISE EXCEPTION 'El esquema sintetico contiene objetos distintos de los de la migracion; no se borra nada.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tinotify_sintetico_app') THEN
        RAISE EXCEPTION 'No existe el rol tinotify_sintetico_app; no se borra nada.';
    END IF;
    -- PostgreSQL 16+ concede al CREATEROLE que creo un rol la membresia ADMIN *sin* SET ni INHERIT: no es un miembro real.
    -- Cualquier otra concesion (SET, INHERIT o sin ADMIN) es un login o servicio asociado y bloquea la reversion.
    IF EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.roleid = 'tinotify_sintetico_app'::regrole
               AND (m.inherit_option OR m.set_option OR NOT m.admin_option)) THEN
        RAISE EXCEPTION 'Aun hay roles miembros de tinotify_sintetico_app; eliminarlos antes.';
    END IF;
END;
$precondiciones$;
-- Operaciones explicitas y SIN CASCADE: si algo ajeno depende de estos objetos (una vista, un permiso en otro esquema),
-- el DROP falla y la transaccion entera se revierte en vez de arrastrar objetos desconocidos.
DROP TABLE tinotify_sintetico.novedades, tinotify_sintetico.actuaciones, tinotify_sintetico.casos,
           tinotify_sintetico.monitor_estado, tinotify_sintetico.entorno;
DROP FUNCTION tinotify_sintetico.limitar_novedades(), tinotify_sintetico.limitar_casos();
DROP SCHEMA tinotify_sintetico;
DROP ROLE tinotify_sintetico_app;
DO $verificacion$
BEGIN
    IF to_regnamespace('tinotify_sintetico') IS NOT NULL
       OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tinotify_sintetico_app') THEN
        RAISE EXCEPTION 'La reversion no dejo el estado esperado; se revierte todo.';
    END IF;
END;
$verificacion$;
COMMIT;
