-- Etapa 4A. Pendiente de aprobacion y de validacion contra PostgreSQL.
-- Un solo bloque transaccional: una colision o error revierte todo el bloque.
-- No usar IF NOT EXISTS: un objeto previo exige revision, no su reutilizacion.
-- La CLI mantiene supabase_migrations.schema_migrations; no duplicar su control.
-- No modifica default privileges globales ni la configuracion de la Data API.
-- Usa exclusivamente la identidad efectiva de la conexion; no cambia de rol.
DO $tinotify_4a$
BEGIN
    CREATE SCHEMA app AUTHORIZATION postgres;
    CREATE SCHEMA app_private AUTHORIZATION postgres;

    CREATE ROLE tinotify_api NOLOGIN NOINHERIT NOSUPERUSER
        NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    CREATE ROLE tinotify_sync NOLOGIN NOINHERIT NOSUPERUSER
        NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    CREATE ROLE tinotify_notifications NOLOGIN NOINHERIT NOSUPERUSER
        NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

    REVOKE ALL PRIVILEGES ON SCHEMA app, app_private
        FROM PUBLIC, anon, authenticated, service_role;
    REVOKE ALL PRIVILEGES ON SCHEMA app, app_private
        FROM tinotify_api, tinotify_sync, tinotify_notifications;

    COMMENT ON SCHEMA app IS
        'Tinotify: datos privados; acceso futuro mediante roles restringidos y RLS.';
    COMMENT ON SCHEMA app_private IS
        'Tinotify: control interno privado; sin acceso directo de clientes.';
END;
$tinotify_4a$;
