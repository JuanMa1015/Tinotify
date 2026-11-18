#!/bin/bash
# Variante con las CUENTAS multiusuario: aplica la migracion de cuentas (alta, baja y alta de nuevo) y prueba AlmacenCuentasPg.
# Prueba el adaptador AlmacenPg (y las pruebas del monitor) contra un PostgreSQL DESECHABLE con el esquema tinotify_real aplicado,
# dentro de contenedores Linux (python:3.11.9): instala las dependencias con los HASHES de requirements.txt (como el build de
# Render) y no abre puertos en el equipo. No toca Supabase. Requiere Docker en ejecución y red para descargar imagenes y ruedas.
export MSYS_NO_PATHCONV=1
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
RED="tinotify-red-pruebas-real"
PG="tinotify-pg-real-py"
IMG_PG="${IMG_PG:-postgres:17}"
IMG_PY="${IMG_PY:-python:3.11.9-slim}"
limpiar() { docker rm -f "$PG" >/dev/null 2>&1; docker network rm "$RED" >/dev/null 2>&1; }
limpiar
trap limpiar EXIT
docker network create "$RED" >/dev/null || exit 1
CLAVE_LOGIN="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
docker run -d --name "$PG" --network "$RED" -e POSTGRES_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')" "$IMG_PG" >/dev/null || exit 1
for i in $(seq 1 60); do docker exec "$PG" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 2; done
sleep 3
sa() { docker exec -i "$PG" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q "$@"; }
adm() { docker exec -i "$PG" psql -U supa_admin -d postgres -v ON_ERROR_STOP=1 -q "$@"; }
sa -c "CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS;
       CREATE ROLE supa_admin LOGIN CREATEROLE CREATEDB BYPASSRLS NOSUPERUSER; GRANT CREATE ON DATABASE postgres TO supa_admin;
       REVOKE ALL ON SCHEMA public FROM PUBLIC;" || exit 1
adm < "$RAIZ/supabase/propuestas/20261117000000_crear_almacen_real.sql" || { echo "ALTA_FALLO"; exit 1; }
adm < "$RAIZ/supabase/propuestas/20261118000000_crear_cuentas_real.sql" || { echo "ALTA_CUENTAS_FALLO"; exit 1; }
echo "ALTA_CUENTAS_OK"
adm < "$RAIZ/supabase/propuestas/20261118000000_crear_cuentas_real_down.sql" || { echo "BAJA_CUENTAS_FALLO"; exit 1; }
echo "BAJA_CUENTAS_OK"
adm < "$RAIZ/supabase/propuestas/20261118000000_crear_cuentas_real.sql" || { echo "SEGUNDA_ALTA_CUENTAS_FALLO"; exit 1; }
echo "SEGUNDA_ALTA_CUENTAS_OK"
adm < "$RAIZ/supabase/propuestas/20261118010000_crear_expedientes_real.sql" || { echo "ALTA_EXPEDIENTES_FALLO"; exit 1; }
echo "ALTA_EXPEDIENTES_OK"
adm < "$RAIZ/supabase/propuestas/20261118010000_crear_expedientes_real_down.sql" || { echo "BAJA_EXPEDIENTES_FALLO"; exit 1; }
echo "BAJA_EXPEDIENTES_OK"
adm < "$RAIZ/supabase/propuestas/20261118010000_crear_expedientes_real.sql" || { echo "SEGUNDA_ALTA_EXPEDIENTES_FALLO"; exit 1; }
echo "SEGUNDA_ALTA_EXPEDIENTES_OK"
adm < "$RAIZ/supabase/propuestas/20261118020000_estado_canales_avisos.sql" || { echo "ALTA_CANALES_FALLO"; exit 1; }
echo "ALTA_CANALES_OK"
adm < "$RAIZ/supabase/propuestas/20261118020000_estado_canales_avisos_down.sql" || { echo "BAJA_CANALES_FALLO"; exit 1; }
echo "BAJA_CANALES_OK"
adm < "$RAIZ/supabase/propuestas/20261118020000_estado_canales_avisos.sql" || { echo "SEGUNDA_ALTA_CANALES_FALLO"; exit 1; }
echo "SEGUNDA_ALTA_CANALES_OK"
adm < "$RAIZ/supabase/propuestas/20261118030000_datos_por_usuario.sql" || { echo "ALTA_DATOS_USUARIO_FALLO"; exit 1; }
echo "ALTA_DATOS_USUARIO_OK"
adm < "$RAIZ/supabase/propuestas/20261118030000_datos_por_usuario_down.sql" || { echo "BAJA_DATOS_USUARIO_FALLO"; exit 1; }
echo "BAJA_DATOS_USUARIO_OK"
adm < "$RAIZ/supabase/propuestas/20261118030000_datos_por_usuario.sql" || { echo "SEGUNDA_ALTA_DATOS_USUARIO_FALLO"; exit 1; }
echo "SEGUNDA_ALTA_DATOS_USUARIO_OK"
adm < "$RAIZ/supabase/propuestas/20261118040000_correo_de_aviso.sql" || { echo "ALTA_CORREO_FALLO"; exit 1; }
echo "ALTA_CORREO_OK"
adm < "$RAIZ/supabase/propuestas/20261118040000_correo_de_aviso_down.sql" || { echo "BAJA_CORREO_FALLO"; exit 1; }
echo "BAJA_CORREO_OK"
adm < "$RAIZ/supabase/propuestas/20261118040000_correo_de_aviso.sql" || { echo "SEGUNDA_ALTA_CORREO_FALLO"; exit 1; }
echo "SEGUNDA_ALTA_CORREO_OK"
adm -c "CREATE ROLE tinotify_real_login LOGIN INHERIT PASSWORD '$CLAVE_LOGIN'; GRANT tinotify_real_app TO tinotify_real_login;" || exit 1
# Administrador de pruebas con contrasena (solo en este contenedor desechable): limpia las tablas entre pruebas (el login de la aplicacion no tiene TRUNCATE).
CLAVE_ADMIN="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
sa -c "ALTER ROLE supa_admin SUPERUSER PASSWORD '$CLAVE_ADMIN';" || exit 1
echo "== Dependencias con hashes (Linux, Python 3.11.9) + pruebas del monitor y del almacen contra PostgreSQL real"
docker run --rm --network "$RED" -v "$RAIZ:/repo:ro" -e PYTHONDONTWRITEBYTECODE=1 \
    -e TINOTIFY_TEST_PG_HOST="$PG" -e TINOTIFY_TEST_PG_USER=tinotify_real_login -e TINOTIFY_TEST_PG_PASSWORD="$CLAVE_LOGIN" \
    -e PRUEBAS="${PRUEBAS:-backend/tests/test_almacen_cuentas_pg.py backend/tests/test_almacen_expedientes_pg.py backend/tests/test_almacen_canales_pg.py backend/tests/test_almacen_usuarios_pg.py backend/tests/test_servicio_cuentas.py backend/tests/test_cuentas.py backend/tests/test_almacen_real_contrato.py}" -e TINOTIFY_TEST_PG_ADMIN_USER=supa_admin -e TINOTIFY_TEST_PG_ADMIN_PASSWORD="$CLAVE_ADMIN" -e PIP_DISABLE_PIP_VERSION_CHECK=1 "$IMG_PY" bash -c '
      set -e
      python -V
      pip install -q --require-hashes --only-binary=:all: -r /repo/backend/requirements-dev.txt -r /repo/backend/requirements-build.txt 2>&1 | tail -2
      cp -r /repo/backend /tmp/backend && python /tmp/backend/scripts/install_local.py > /dev/null   # como el build de Render
      python -m pip check
      python -c "import cryptography, psycopg; print(\"cryptography\", cryptography.__version__, \"| psycopg\", psycopg.__version__, \"| libpq\", psycopg.pq.version())"
      cd /repo && python -m pytest -q -p no:cacheprovider $PRUEBAS 2>&1 | tail -15
    '
