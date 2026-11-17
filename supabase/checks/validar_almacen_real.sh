#!/bin/bash
# Valida alta, auditoria, permisos y baja del esquema tinotify_real en un PostgreSQL DESECHABLE (Docker local, sin puertos). No toca Supabase.
export MSYS_NO_PATHCONV=1
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
SC="$(cd "$(dirname "$0")" && pwd)"
IMG="${IMG:-postgres:17}"
C="tinotify-pg-real-validacion"
docker rm -f "$C" >/dev/null 2>&1
docker run -d --name "$C" -e POSTGRES_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')" "$IMG" >/dev/null || { echo "NO_SE_PUDO_INICIAR_CONTENEDOR"; exit 1; }
trap 'docker rm -f "$C" >/dev/null 2>&1' EXIT
for i in $(seq 1 60); do docker exec "$C" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 2; done
sleep 3
sa() { docker exec -i "$C" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q "$@"; }       # superusuario (solo para preparar)
adm() { docker exec -i "$C" psql -U supa_admin -d postgres -v ON_ERROR_STOP=1 -q "$@"; }    # administrador tipo Supabase: NOSUPERUSER + CREATEROLE
echo "version: $(sa -tA -c 'show server_version')"
# Roles de Supabase y un administrador NOSUPERUSER con CREATEROLE (como el usuario `postgres` de Supabase)
sa -c "CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS;
       CREATE ROLE supa_admin LOGIN CREATEROLE CREATEDB BYPASSRLS NOSUPERUSER; GRANT CREATE ON DATABASE postgres TO supa_admin;
       CREATE SCHEMA tinotify_sintetico; CREATE TABLE tinotify_sintetico.casos(id int); REVOKE ALL ON SCHEMA public FROM PUBLIC;" || exit 1
echo "== ALTA (como administrador NOSUPERUSER)"
adm < "$RAIZ/supabase/propuestas/20261117000000_crear_almacen_real.sql" && echo "ALTA_OK" || { echo "ALTA_FALLO"; exit 1; }
echo "== BAJA con el login aun existiendo (debe negarse)"
adm -c "CREATE ROLE tinotify_real_login LOGIN INHERIT; GRANT tinotify_real_app TO tinotify_real_login;" || exit 1
adm < "$RAIZ/supabase/propuestas/20261117000000_crear_almacen_real_down.sql" >/dev/null 2>&1 && { echo "BAJA_NO_DEBIA_PASAR"; exit 1; } || echo "BAJA_RECHAZADA_CON_MIEMBROS_OK"
echo "== PRUEBAS COMO tinotify_real_login"
docker exec -i "$C" psql -U tinotify_real_login -d postgres -v ON_ERROR_STOP=1 -q < "$SC/almacen_real_pruebas.sql" 2>&1 | sed 's/^psql:[^ ]* //' | grep -E "OK_POSITIVO|OK_NEGATIVO|FALLO|DEBIA_FALLAR|ERROR" | awk '{c[$1]++; if ($1 !~ /^OK_/) print} END {for (k in c) print k": "c[k]}'
echo "== CLIENTES DE SUPABASE (anon / authenticated / service_role) sin acceso"
for r in anon authenticated service_role; do
  adm -tA -c "SET ROLE $r; SELECT count(*) FROM tinotify_real.huellas;" >/dev/null 2>&1 && echo "ACCESO_INDEBIDO_$r" || echo "sin_acceso_$r: ok"
done
echo "== AUDITORIA DE CATALOGO"
adm -tA -c "SELECT 'tablas_con_rls_forzado=' || count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='tinotify_real' AND c.relkind='r' AND c.relforcerowsecurity;
            SELECT 'politicas=' || count(*) FROM pg_policies WHERE schemaname='tinotify_real';
            SELECT 'rol_app_sin_privilegios_peligrosos=' || NOT (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb) FROM pg_roles WHERE rolname='tinotify_real_app';
            SELECT 'login_puede_login=' || rolcanlogin FROM pg_roles WHERE rolname='tinotify_real_login';"
echo "== BAJA (tras eliminar el login)"
adm -c "DROP ROLE tinotify_real_login;" || exit 1
adm < "$RAIZ/supabase/propuestas/20261117000000_crear_almacen_real_down.sql" && echo "BAJA_OK" || { echo "BAJA_FALLO"; exit 1; }
adm -tA -c "SELECT 'esquema_existe=' || (to_regnamespace('tinotify_real') IS NOT NULL); SELECT 'rol_existe=' || EXISTS(SELECT 1 FROM pg_roles WHERE rolname='tinotify_real_app'); SELECT 'sintetico_intacto=' || (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='tinotify_sintetico' AND c.relkind='r');"
echo "== SEGUNDA ALTA (el ciclo es repetible)"
adm < "$RAIZ/supabase/propuestas/20261117000000_crear_almacen_real.sql" && echo "SEGUNDA_ALTA_OK" || echo "SEGUNDA_ALTA_FALLO"
