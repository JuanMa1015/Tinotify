"""PostgreSQL desechable: TLS propio, red dedicada y puerto solo loopback.

Opt-in TINOTIFY_TEST_POSTGRES=1. Nunca lee DATABASE_URL ni usa un servidor existente.
"""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import secrets
import shutil
import subprocess
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from tinotify.persistence.interfaces import Principal
from tinotify.persistence.postgres import AlmacenPostgres, ConfiguracionPostgres, crear_pool
from tinotify.services.seguimiento import ServicioSeguimiento


def ejecutar(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=120).stdout.strip()


class DsnFicticio(str):
    def __repr__(self):
        return "<DSN de fixture oculto>"


@pytest.fixture(scope="session")
def postgres_aislado(tmp_path_factory):
    if os.environ.get("TINOTIFY_TEST_POSTGRES") != "1":
        pytest.skip("Integracion opt-in: PostgreSQL Docker aislado, sin servidor externo")
    version = os.environ.get("TINOTIFY_TEST_POSTGRES_VERSION", "17.12")
    if version not in ("17.11", "17.12"):
        raise ValueError("Solo se admiten las versiones PostgreSQL 17 aisladas revisadas")
    endpoint = ejecutar("docker","context","inspect","--format","{{.Endpoints.docker.Host}}")
    if not endpoint.startswith(("unix://","npipe://")):
        raise RuntimeError("Las pruebas solo admiten Docker local")
    temporal = tmp_path_factory.mktemp("postgres-sintetico")
    tls = temporal/"tls"
    tls.mkdir()
    openssl = shutil.which("openssl") or "C:/Program Files/Git/usr/bin/openssl.exe"
    ejecutar(openssl,"req","-x509","-newkey","rsa:2048","-nodes","-days","1",
             "-subj","/CN=localhost","-addext","subjectAltName=DNS:localhost,IP:127.0.0.1",
             "-keyout",str(tls/"server.key"),"-out",str(tls/"server.crt"))
    password = secrets.token_urlsafe(32)
    entorno = temporal/"postgres.env"
    entorno.write_text("POSTGRES_USER=fixture_harness\nPOSTGRES_PASSWORD="+password+"\n",encoding="utf-8")
    nombre = "tinotify-test-"+uuid4().hex
    red = nombre+"-red"
    creado,red_creada = False,False
    try:
        ejecutar("docker","network","create",red)
        red_creada = True
        ejecutar("docker","create","--name",nombre,"--network",red,
            "--publish","127.0.0.1::5432","--env-file",str(entorno),
            "--mount",f"type=bind,source={tls},target=/fixture,readonly",
            "--entrypoint","sh","postgres:"+version,"-c",
            "cp /fixture/server.crt /tmp/server.crt; cp /fixture/server.key /tmp/server.key; "
            "chown postgres:postgres /tmp/server.crt /tmp/server.key; chmod 600 /tmp/server.key; "
            "exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key")
        creado = True
        ejecutar("docker","start",nombre)
        try:
            puerto = ejecutar("docker","port",nombre,"5432/tcp").rsplit(":",1)[1]
        except subprocess.CalledProcessError:
            detalle = ejecutar("docker","logs",nombre).replace(password,"[fixture]")
            raise RuntimeError("El contenedor de pruebas no publico puerto: "+detalle) from None
        opciones = dict(host="localhost",hostaddr="127.0.0.1",port=puerto,dbname="postgres",user="postgres",
                        password=password,sslmode="verify-full",sslrootcert=str(tls/"server.crt"),connect_timeout=2)
        deadline = time.monotonic()+60
        while True:
            try:
                bootstrap = psycopg.connect(**{**opciones,"user":"fixture_harness"},autocommit=True)
                break
            except psycopg.OperationalError:
                if time.monotonic()>=deadline:
                    raise RuntimeError("PostgreSQL ficticio no arranco; no se consulto otro servidor") from None
                time.sleep(.25)
        with bootstrap:
            # OID bootstrap debe conservar SUPERUSER. postgres es aqui un rol
            # secundario desechable, que SI puede probarse sin ese atributo.
            bootstrap.execute(sql.SQL("CREATE ROLE postgres LOGIN SUPERUSER CREATEDB CREATEROLE BYPASSRLS REPLICATION PASSWORD {}").format(sql.Literal(password)))
            # El bootstrap es dueno de esta base desechable. Emular el CREATE
            # de postgres observado en Supabase; no concederlo a los servicios.
            bootstrap.execute("GRANT CREATE ON DATABASE postgres TO postgres")
        admin = psycopg.connect(**opciones,autocommit=True)
        with admin:
            admin.execute("CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY); CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS")
            root = Path(__file__).resolve().parents[3]
            # Todas las migraciones con el mismo contexto NOSUPERUSER: tambien
            # 4A necesita reproducir sus membresias ADMIN sin SET/INHERIT.
            with psycopg.connect(**{**opciones,"user":"fixture_harness"},autocommit=True) as harness:
                harness.execute("ALTER ROLE postgres NOSUPERUSER")
                try:
                    assert not admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0]
                    for migracion in sorted((root/"supabase/migrations").glob("*.sql")):
                        admin.execute(migracion.read_text(encoding="utf-8"))
                    assert not admin.execute("""SELECT EXISTS (
                        SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid
                        WHERE r.rolname IN ('tinotify_guard_reader','tinotify_state_writer','tinotify_fixture_owner')
                        AND (m.inherit_option OR m.set_option))""").fetchone()[0]
                finally:
                    admin.rollback()
                    harness.execute("ALTER ROLE postgres SUPERUSER")
            roles = {}
            for capacidad in ("api","sync","notifications"):
                rol = "fixture_"+capacidad
                admin.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT PASSWORD {}").format(sql.Identifier(rol),sql.Literal(password)))
                admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier("tinotify_"+capacidad),sql.Identifier(rol)))
                roles[capacidad] = DsnFicticio(make_conninfo(**{**opciones,"user":rol}))
            yield admin,roles,tls/"server.crt"
    finally:
        try:
            if creado:
                ejecutar("docker","rm","--force","--volumes",nombre)
            if red_creada:
                ejecutar("docker","network","rm",red)
        finally:
            for archivo in (entorno,tls/"server.key",tls/"server.crt"):
                archivo.unlink(missing_ok=True)


@pytest.fixture
def entorno_pg(postgres_aislado, politica_sintetica):
    admin, roles, ca = postgres_aislado
    sujetos = {clave: uuid4() for clave in ("a","b")}
    perfiles = {}
    for clave,sujeto in sujetos.items():
        perfil = uuid4()
        admin.execute("INSERT INTO auth.users(id) VALUES(%s)",(sujeto,))
        admin.execute("INSERT INTO app.estudiantes(id,auth_subject,estado) VALUES(%s,%s,'activo')",(perfil,sujeto))
        perfiles[clave] = perfil

    class AutenticadorFicticio:
        def verificar(self, credencial):
            if credencial not in sujetos:
                raise PermissionError("Credencial ficticia no autorizada")
            return Principal(sujetos[credencial],datetime.now(timezone.utc)+timedelta(minutes=5))

    with ExitStack() as recursos:
        almacenes = {}
        for capacidad,dsn in roles.items():
            pool = crear_pool(ConfiguracionPostgres(dsn,ca,max_conexiones=2 if capacidad=="sync" else 1))
            pool.open()
            recursos.callback(pool.close)
            almacenes[capacidad] = AlmacenPostgres(pool,AutenticadorFicticio(),politica=politica_sintetica)
        binding = uuid4()
        servicio = ServicioSeguimiento(almacenes["sync"],politica=politica_sintetica)
        for credencial in sujetos:
            with almacenes["sync"].transaccion(credencial) as unidad:
                seguimiento = unidad.seguir("local","CASO_FICTICIO",politica_sintetica.firma("local"))
            admin.execute("""INSERT INTO app_private.accesos_sigac
                (estudiante_id,estado_id,expediente_id,estado,fuente,session_binding_id,session_epoch,access_epoch,comprobado_en,valido_hasta,comprobante_ref)
                VALUES(%s,%s,%s,'verificado','simulador',%s,1,1,clock_timestamp(),clock_timestamp()+interval '1 hour',%s)""",
                (perfiles[credencial],seguimiento.estado_id,seguimiento.expediente_id,binding,uuid4()))
        yield dict(admin=admin,almacenes=almacenes,servicio=servicio,binding=binding,perfiles=perfiles,ca=ca,roles=roles)
