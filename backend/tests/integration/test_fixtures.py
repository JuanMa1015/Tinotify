"""Lifecycle local e inerte. Nunca lee credenciales o servidores del desarrollador."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import secrets
from threading import Event
import time
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from .conftest import DsnFicticio


def ejecutar(conexion, nombre, *parametros):
    assert nombre in {"registrar","provisionar","cerrar","limpiar","consultar","recuperar_expirado"}
    return conexion.execute(sql.SQL("SELECT app_fixture.{}({})").format(
        sql.Identifier(nombre),sql.SQL(",").join(sql.Placeholder() for _ in parametros)),parametros).fetchone()[0]


@dataclass(repr=False)
class Control:
    dsn: str = field(repr=False)
    ensayos: list = field(default_factory=list,repr=False)

    def llamar(self,nombre,*parametros):
        with psycopg.connect(self.dsn,autocommit=True) as conexion:
            return ejecutar(conexion,nombre,*parametros)

    def registrar(self,clave=None,credencial=None,segundos=60):
        clave=clave or uuid4()
        credencial=credencial or secrets.token_hex(32)
        datos=self.llamar("registrar",clave,credencial,segundos)
        self.ensayos.append((UUID(datos["id"]),credencial))
        return UUID(datos["id"]),credencial,clave

    def limpiar_propios(self):
        for identidad,credencial in self.ensayos:
            self.llamar("cerrar",identidad,credencial)
            self.llamar("limpiar",identidad,credencial)


@pytest.fixture(scope="session")
def roles_control(postgres_aislado):
    admin,operativos,_=postgres_aislado
    opciones=conninfo_to_dict(operativos["api"])
    resultado={}
    for nombre,capacidad in (("a","control"),("b","control"),("recuperador","recovery")):
        rol="fixture_control_"+nombre
        password=secrets.token_urlsafe(32)
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT PASSWORD {}").format(sql.Identifier(rol),sql.Literal(password)))
        admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier("tinotify_fixture_"+capacidad),sql.Identifier(rol)))
        resultado[nombre]=DsnFicticio(make_conninfo(**{**opciones,"user":rol,"password":password,"application_name":"tinotify-fixture-test"}))
    return resultado


@pytest.fixture
def controles(postgres_aislado,roles_control):
    admin,_,_=postgres_aislado
    admin.execute("UPDATE app_fixture.entorno SET habilitado=true WHERE id")
    controles={n:Control(dsn) for n,dsn in roles_control.items()}
    try:
        yield controles
    finally:
        for n in ("a","b"): controles[n].limpiar_propios()
        admin.execute("UPDATE app_fixture.entorno SET habilitado=false WHERE id")


def provisionar(control,identidad,credencial):
    return control.llamar("provisionar",identidad,credencial,2,2,"0"*64)


def esperar_bloqueo(admin,pid,minimo=1):
    limite=time.monotonic()+5
    while True:
        admin.execute("SELECT pg_stat_clear_snapshot()")
        cantidad=admin.execute("""WITH RECURSIVE bloqueados(pid) AS (
            SELECT pid FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid))
            UNION
            SELECT a.pid FROM pg_stat_activity a JOIN bloqueados b
                ON b.pid=ANY(pg_blocking_pids(a.pid)))
            SELECT count(*) FROM pg_stat_activity a JOIN bloqueados b USING(pid)
            WHERE a.application_name='tinotify-fixture-test' AND a.wait_event_type='Lock'""",(pid,)).fetchone()[0]
        if cantidad>=minimo:
            return
        assert time.monotonic()<limite, "No se observo la espera de bloqueo requerida"
        time.sleep(.02)


def expirar(admin,identidad):
    # Exclusivamente en el contenedor desechable, nunca en Supabase.
    admin.execute("""UPDATE app_fixture.ensayos
        SET creado_en=clock_timestamp()-interval '2 minutes',vence_en=clock_timestamp()-interval '1 minute'
        WHERE id=%s""",(identidad,))


def test_cerrado_por_defecto_y_control_sin_dml(postgres_aislado,roles_control):
    admin,_,_=postgres_aislado
    assert not admin.execute("SELECT habilitado FROM app_fixture.entorno WHERE id").fetchone()[0]
    control=Control(roles_control["a"])
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState): control.registrar()
    with psycopg.connect(control.dsn,autocommit=True) as conexion:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conexion.execute("UPDATE app_fixture.entorno SET habilitado=true WHERE id")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conexion.execute("SELECT * FROM app_fixture.ensayos")


def test_ciclo_inerte_idempotencia_y_recibos(controles,postgres_aislado):
    c=controles["a"]
    identidad,credencial,clave=c.registrar()
    assert UUID(c.llamar("registrar",clave,credencial,60)["id"])==identidad
    primera=provisionar(c,identidad,credencial)
    repetida=provisionar(c,identidad,credencial)
    assert primera==repetida
    admin,_,_=postgres_aislado
    perfiles=admin.execute("""SELECT e.auth_subject,e.estado FROM app.estudiantes e
        JOIN app_fixture.perfiles f ON f.estudiante_id=e.id WHERE f.ensayo_id=%s""",(identidad,)).fetchall()
    assert perfiles==[(None,"pendiente")]*2
    c.llamar("cerrar",identidad,credencial)
    primero=c.llamar("limpiar",identidad,credencial)
    assert primero==c.llamar("limpiar",identidad,credencial)
    assert primero["estado"]=="limpio" and primero["perfiles_restantes"]==0
    assert UUID(c.llamar("registrar",clave,credencial,60)["id"])==identidad
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState): provisionar(c,identidad,credencial)


def test_rls_rechaza_estudiante_sin_pertenencia(postgres_aislado):
    admin,_,_=postgres_aislado
    estudiante=uuid4()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with admin.transaction():
            # Sonda del propietario interno, sin conceder membresias a clientes.
            admin.execute("SET LOCAL ROLE tinotify_fixture_owner")
            admin.execute("INSERT INTO app.estudiantes(id,auth_subject,estado) VALUES(%s,NULL,'pendiente')",(estudiante,))
    assert admin.execute("SELECT count(*) FROM app.estudiantes WHERE id=%s",(estudiante,)).fetchone()[0]==0


@pytest.mark.parametrize("crear_estudiante",[False,True])
def test_fk_diferidas_rechazan_pertenencia_incompleta_al_commit(controles,postgres_aislado,crear_estudiante):
    identidad,_,_=controles["a"].registrar()
    estudiante,cabecera=uuid4(),uuid4()
    admin,_,_=postgres_aislado
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with admin.transaction():
            admin.execute("SET LOCAL ROLE tinotify_fixture_owner")
            admin.execute("INSERT INTO app_fixture.perfiles VALUES(%s,%s,%s,%s)",
                          (identidad,estudiante,cabecera,[uuid4()]))
            if crear_estudiante:
                admin.execute("INSERT INTO app.estudiantes(id,auth_subject,estado) VALUES(%s,NULL,'pendiente')",(estudiante,))
            # Las sentencias anteriores pasan; la falta de padres falla al COMMIT.
            assert admin.execute("SELECT count(*) FROM app_fixture.perfiles WHERE estudiante_id=%s",(estudiante,)).fetchone()[0]==1
    assert admin.execute("SELECT count(*) FROM app_fixture.perfiles WHERE estudiante_id=%s",(estudiante,)).fetchone()[0]==0
    assert admin.execute("SELECT count(*) FROM app.estudiantes WHERE id=%s",(estudiante,)).fetchone()[0]==0


def test_pertenencia_no_admite_update_del_propietario_interno(controles,postgres_aislado):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    provisionar(c,identidad,credencial)
    admin,_,_=postgres_aislado
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with admin.transaction():
            admin.execute("SET LOCAL ROLE tinotify_fixture_owner")
            admin.execute("UPDATE app_fixture.perfiles SET estado_id=%s WHERE ensayo_id=%s",(uuid4(),identidad))
    assert c.llamar("consultar",identidad,credencial)["perfiles_restantes"]==2


def test_pertenencia_previa_confirma_con_ambas_fk_satisfechas(controles,postgres_aislado):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    admin,_,_=postgres_aislado
    diferidas=admin.execute("""SELECT condeferrable,condeferred FROM pg_constraint
        WHERE conrelid='app_fixture.perfiles'::regclass AND contype='f'
        AND confrelid IN ('app.estudiantes'::regclass,'app.estados_reconciliacion'::regclass)""").fetchall()
    assert diferidas==[(True,True)]*2
    with psycopg.connect(c.dsn,autocommit=True) as conexion:
        with conexion.transaction():
            ejecutar(conexion,"provisionar",identidad,credencial,2,2,"0"*64)
            conexion.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert c.llamar("consultar",identidad,credencial)["perfiles_restantes"]==2


def test_no_adopta_ids_ajenos_y_no_borra_otro_ensayo(controles,entorno_pg):
    a,b=controles["a"],controles["b"]
    identidad,credencial,_=a.registrar(clave=entorno_pg["perfiles"]["a"])
    provisionar(a,identidad,credencial)
    otra,otro_token,_=b.registrar()
    provisionar(b,otra,otro_token)
    with pytest.raises(psycopg.errors.InsufficientPrivilege): b.llamar("cerrar",identidad,credencial)
    with pytest.raises(psycopg.errors.InsufficientPrivilege): a.llamar("limpiar",otra,otro_token)
    with pytest.raises(psycopg.errors.InsufficientPrivilege): a.llamar("cerrar",identidad,secrets.token_hex(32))
    admin=entorno_pg["admin"]
    assert admin.execute("SELECT count(*) FROM app.estudiantes WHERE id=%s",(entorno_pg["perfiles"]["a"],)).fetchone()[0]==1
    assert admin.execute("SELECT count(*) FROM app_fixture.perfiles WHERE ensayo_id=%s AND estudiante_id=%s",(identidad,entorno_pg["perfiles"]["a"])).fetchone()[0]==0


@pytest.mark.parametrize("campo,valor",[("estado","activo"),("auth_subject",uuid4()),("id",uuid4())])
def test_vinculo_auth_e_identidad_del_fixture_bloqueados(controles,postgres_aislado,campo,valor):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    provisionar(c,identidad,credencial)
    admin,_,_=postgres_aislado
    perfil=admin.execute("SELECT estudiante_id FROM app_fixture.perfiles WHERE ensayo_id=%s LIMIT 1",(identidad,)).fetchone()[0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin.execute(sql.SQL("UPDATE app.estudiantes SET {}=%s WHERE id=%s").format(sql.Identifier(campo)),(valor,perfil))


def test_roles_operativos_y_helpers_no_tienen_control(controles,postgres_aislado):
    _,operativos,_=postgres_aislado
    identidad,credencial,_=controles["a"].registrar()
    for dsn in operativos.values():
        with psycopg.connect(dsn,autocommit=True) as conexion:
            with pytest.raises(psycopg.errors.InsufficientPrivilege): ejecutar(conexion,"cerrar",identidad,credencial)
    with psycopg.connect(controles["a"].dsn,autocommit=True) as conexion:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conexion.execute("SELECT app_fixture.depurar(%s)",(identidad,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        controles["recuperador"].llamar("cerrar",identidad,credencial)


def test_cuota_concurrente_no_se_sobrepasa(controles):
    c=controles["a"]
    c.registrar()
    def crear():
        try: c.registrar(); return True
        except psycopg.errors.ProgramLimitExceeded: return False
    with ThreadPoolExecutor(max_workers=2) as workers:
        resultados=list(workers.map(lambda _:crear(),range(2)))
    assert sum(resultados)==1


def test_registro_concurrente_misma_clave_es_un_solo_recibo(controles,postgres_aislado):
    c=controles["a"]
    clave,credencial=uuid4(),secrets.token_hex(32)
    admin,_,_=postgres_aislado
    with ThreadPoolExecutor(max_workers=2) as workers:
        with admin.transaction():
            admin.execute("SELECT id FROM app_fixture.entorno WHERE id FOR UPDATE")
            pid=admin.execute("SELECT pg_backend_pid()").fetchone()[0]
            trabajos=[workers.submit(c.registrar,clave,credencial) for _ in range(2)]
            esperar_bloqueo(admin,pid,minimo=2)
        resultados=[trabajo.result(timeout=10) for trabajo in trabajos]
    assert resultados[0]==resultados[1]
    assert admin.execute("SELECT count(*) FROM app_fixture.ensayos WHERE clave=%s",(clave,)).fetchone()[0]==1


def test_expiracion_durante_espera_impide_provision(controles,postgres_aislado):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    admin,_,_=postgres_aislado
    with ThreadPoolExecutor(max_workers=1) as workers:
        with admin.transaction():
            admin.execute("SELECT id FROM app_fixture.ensayos WHERE id=%s FOR UPDATE",(identidad,))
            pid=admin.execute("SELECT pg_backend_pid()").fetchone()[0]
            trabajo=workers.submit(provisionar,c,identidad,credencial)
            esperar_bloqueo(admin,pid)
            expirar(admin,identidad)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState): trabajo.result(timeout=10)
    estado=c.llamar("consultar",identidad,credencial)
    assert estado["estado"]=="registrado" and estado["perfiles_restantes"]==0


@pytest.mark.parametrize("operacion",["cerrar","limpiar"])
def test_recuperacion_serializa_con_cierre_y_limpieza(controles,postgres_aislado,operacion):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    provisionar(c,identidad,credencial)
    if operacion=="limpiar": c.llamar("cerrar",identidad,credencial)
    admin,_,_=postgres_aislado
    expirar(admin,identidad)
    with ThreadPoolExecutor(max_workers=1) as workers:
        with psycopg.connect(c.dsn,autocommit=True) as conexion:
            with conexion.transaction():
                ejecutar(conexion,operacion,identidad,credencial)
                pid=conexion.execute("SELECT pg_backend_pid()").fetchone()[0]
                trabajo=workers.submit(controles["recuperador"].llamar,"recuperar_expirado",identidad)
                esperar_bloqueo(admin,pid)
        assert trabajo.result(timeout=10)["estado"]=="limpio"
    assert c.llamar("consultar",identidad,credencial)["perfiles_restantes"]==0


def test_agotamiento_conserva_reintentos_y_limpieza_sin_purgar(controles,postgres_aislado):
    c=controles["a"]
    identidad,credencial,clave=c.registrar()
    admin,_,_=postgres_aislado

    class RevertirRecibos(Exception): pass

    with pytest.raises(RevertirRecibos):
        with admin.transaction():
            # Saturacion solo local y reversible: ninguna fila artificial se confirma.
            admin.execute("""INSERT INTO app_fixture.ensayos
                (id,operador_oid,operador_nombre,clave,token_hash,ttl,vence_en,estado,limpiado_en)
                SELECT gen_random_uuid(),'fixture_control_a'::regrole::oid,'fixture_control_a',
                    gen_random_uuid(),sha256(convert_to(%s,'UTF8')),60,clock_timestamp()+interval '1 minute',
                    'limpio',clock_timestamp()
                FROM generate_series(1,1000-(SELECT count(*)::integer FROM app_fixture.ensayos))""",(credencial,))
            assert admin.execute("SELECT count(*) FROM app_fixture.ensayos").fetchone()[0]==1000
            # Cambiar a una identidad MENOS privilegiada solo en esta transaccion local.
            admin.execute("SET LOCAL SESSION AUTHORIZATION fixture_control_a")
            assert UUID(ejecutar(admin,"registrar",clave,credencial,60)["id"])==identidad
            with pytest.raises(psycopg.errors.ProgramLimitExceeded):
                with admin.transaction(): ejecutar(admin,"registrar",uuid4(),secrets.token_hex(32),60)
            ejecutar(admin,"provisionar",identidad,credencial,1,1,"0"*64)
            ejecutar(admin,"cerrar",identidad,credencial)
            assert ejecutar(admin,"limpiar",identidad,credencial)["estado"]=="limpio"
            assert UUID(ejecutar(admin,"registrar",clave,credencial,60)["id"])==identidad
            raise RevertirRecibos
    assert c.llamar("consultar",identidad,credencial)["estado"]=="registrado"


def test_rollback_de_provision_y_limpieza_completas(controles):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    with pytest.raises(RuntimeError,match="FALLO FICTICIO"):
        with psycopg.connect(c.dsn,autocommit=True) as conexion:
            with conexion.transaction():
                ejecutar(conexion,"provisionar",identidad,credencial,2,2,"0"*64)
                raise RuntimeError("FALLO FICTICIO")
    assert c.llamar("consultar",identidad,credencial)["perfiles_restantes"]==0
    provisionar(c,identidad,credencial)
    c.llamar("cerrar",identidad,credencial)
    with pytest.raises(RuntimeError,match="FALLO FICTICIO"):
        with psycopg.connect(c.dsn,autocommit=True) as conexion:
            with conexion.transaction():
                ejecutar(conexion,"limpiar",identidad,credencial)
                raise RuntimeError("FALLO FICTICIO")
    assert c.llamar("consultar",identidad,credencial)["perfiles_restantes"]==2
    c.llamar("limpiar",identidad,credencial)  # respuesta confirmada descartada
    assert c.llamar("limpiar",identidad,credencial)["estado"]=="limpio"


def test_recuperacion_abandonado_solo_expirado(controles,postgres_aislado):
    c,r=controles["a"],controles["recuperador"]
    identidad,credencial,_=c.registrar()
    provisionar(c,identidad,credencial)
    with pytest.raises(psycopg.errors.InsufficientPrivilege): r.llamar("recuperar_expirado",identidad)
    admin,_,_=postgres_aislado
    admin.execute("UPDATE app_fixture.ensayos SET creado_en=clock_timestamp()-interval '2 minutes',vence_en=clock_timestamp()-interval '1 minute' WHERE id=%s",(identidad,))
    admin.execute("UPDATE app_fixture.entorno SET habilitado=false WHERE id")
    assert r.llamar("recuperar_expirado",identidad)["estado"]=="limpio"
    assert r.llamar("recuperar_expirado",identidad)["perfiles_restantes"]==0
    assert c.llamar("consultar",identidad,credencial)["estado"]=="limpio"


def test_limpiezas_concurrentes_y_cierre_con_provision(controles):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    def intentar_provision():
        try: provisionar(c,identidad,credencial)
        except psycopg.errors.ObjectNotInPrerequisiteState: pass
    with ThreadPoolExecutor(max_workers=2) as workers:
        uno=workers.submit(intentar_provision)
        dos=workers.submit(c.llamar,"cerrar",identidad,credencial)
        uno.result(); dos.result()
    with ThreadPoolExecutor(max_workers=2) as workers:
        resultados=list(workers.map(lambda _:c.llamar("limpiar",identidad,credencial),range(2)))
    assert resultados[0]==resultados[1] and resultados[0]["perfiles_restantes"]==0


def test_limpieza_no_interfiere_sincronizacion_ajena(controles,entorno_pg,actuacion_ficticia):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    provisionar(c,identidad,credencial)
    c.llamar("cerrar",identidad,credencial)
    with ThreadPoolExecutor(max_workers=2) as workers:
        limpieza=workers.submit(c.llamar,"limpiar",identidad,credencial)
        sync=workers.submit(entorno_pg["servicio"].sincronizar,"a","CASO_FICTICIO",[actuacion_ficticia()],
                            clave=uuid4(),worker=uuid4(),binding=entorno_pg["binding"])
        assert limpieza.result()["estado"]=="limpio"
        assert not sync.result().repetido
    estado=entorno_pg["servicio"].estado("a",binding=entorno_pg["binding"])
    assert len(estado["cases"]["CASO_FICTICIO"]["records"])==1


def test_datos_no_permitidos_detienen_limpieza_sin_borrarlos(controles,postgres_aislado):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    provisionar(c,identidad,credencial)
    c.llamar("cerrar",identidad,credencial)
    admin,_,_=postgres_aislado
    estudiante,cabecera,casos=admin.execute("SELECT estudiante_id,estado_id,casos FROM app_fixture.perfiles WHERE ensayo_id=%s LIMIT 1",(identidad,)).fetchone()
    local=uuid4()
    admin.execute("INSERT INTO app.actuaciones(estudiante_id,estado_id,expediente_id,local_id,orden_registro,version_hash,status) VALUES(%s,%s,%s,%s,0,%s,'linea_base')",(estudiante,cabecera,casos[0],local,"0"*64))
    try:
        with pytest.raises(psycopg.errors.CheckViolation): c.llamar("limpiar",identidad,credencial)
        assert c.llamar("consultar",identidad,credencial)["perfiles_restantes"]==2
    finally:
        # Solo la fila ficticia introducida por ESTE caso en el contenedor nuevo.
        admin.execute("DELETE FROM app.actuaciones WHERE estudiante_id=%s AND local_id=%s",(estudiante,local))


@pytest.mark.parametrize("operacion",["provisionar","limpiar"])
def test_espera_real_serializa_cierre_y_limpieza(controles,postgres_aislado,operacion):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    if operacion=="limpiar":
        provisionar(c,identidad,credencial)
        c.llamar("cerrar",identidad,credencial)
    listo,liberar=Event(),Event()
    pids=[]
    def mantener_transaccion():
        with psycopg.connect(c.dsn,autocommit=True) as conexion:
            with conexion.transaction():
                ejecutar(conexion,"cerrar" if operacion=="provisionar" else "limpiar",identidad,credencial)
                pids.append(conexion.execute("SELECT pg_backend_pid()").fetchone()[0])
                listo.set()
                assert liberar.wait(8)
    def esperar():
        if operacion=="provisionar":
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState): provisionar(c,identidad,credencial)
        else:
            assert c.llamar("limpiar",identidad,credencial)["estado"]=="limpio"
    admin,_,_=postgres_aislado
    with ThreadPoolExecutor(max_workers=2) as workers:
        primero=workers.submit(mantener_transaccion)
        assert listo.wait(5)
        segundo=workers.submit(esperar)
        try:
            esperar_bloqueo(admin,pids[0])
        finally:
            liberar.set()
        primero.result(); segundo.result()


@pytest.mark.parametrize("concesion",[
    "GRANT EXECUTE ON FUNCTION app_fixture.obtener(uuid,text,boolean) TO PUBLIC",
    "GRANT SELECT(clave) ON app_fixture.ensayos TO tinotify_fixture_control",
    "GRANT USAGE ON SCHEMA app_fixture TO PUBLIC",
])
def test_auditoria_falla_ante_permisos_residuales(postgres_aislado,concesion):
    from pathlib import Path
    admin,_,_=postgres_aislado
    ruta=Path(__file__).resolve().parents[3]/"supabase/migrations/20261114020000_controlar_fixtures_inertes.sql"
    cuerpo=ruta.read_text(encoding="utf-8").split("DO $auditoria$",1)[1].split("$auditoria$;",1)[0]
    with pytest.raises(psycopg.errors.RaiseException):
        with admin.transaction():
            admin.execute(concesion)
            admin.execute("DO $auditoria$"+cuerpo+"$auditoria$;")


def test_vigencia_y_parametros_no_pueden_reescribir_un_ensayo(controles,postgres_aislado):
    c=controles["a"]
    identidad,credencial,clave=c.registrar()
    with pytest.raises(psycopg.errors.InvalidParameterValue): c.llamar("registrar",clave,credencial,900)
    with pytest.raises(psycopg.errors.InvalidParameterValue): c.llamar("provisionar",identidad,credencial,3,1,"0"*64)
    with pytest.raises(psycopg.errors.InvalidParameterValue): c.llamar("provisionar",identidad,credencial,1,1,None)
    admin,_,_=postgres_aislado
    admin.execute("UPDATE app_fixture.ensayos SET creado_en=clock_timestamp()-interval '2 minutes',vence_en=clock_timestamp()-interval '1 minute' WHERE id=%s",(identidad,))
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState): provisionar(c,identidad,credencial)
    assert c.llamar("consultar",identidad,credencial)["perfiles_restantes"]==0


def test_aislamiento_no_admitido_rechazado_antes_de_cambiar_estado(controles):
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    with pytest.raises(psycopg.errors.ActiveSqlTransaction):
        with psycopg.connect(c.dsn,autocommit=True) as conexion:
            with conexion.transaction():
                conexion.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                ejecutar(conexion,"provisionar",identidad,credencial,1,1,"0"*64)
    assert c.llamar("consultar",identidad,credencial)["perfiles_restantes"]==0


@pytest.mark.parametrize("rol",["tinotify_api","tinotify_fixture_owner","pg_read_server_files"])
def test_membresias_accidentales_hacen_fallar_control(controles,postgres_aislado,rol):
    admin,_,_=postgres_aislado
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    admin.execute(sql.SQL("GRANT {} TO fixture_control_a").format(sql.Identifier(rol)))
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege): c.llamar("cerrar",identidad,credencial)
    finally:
        admin.execute(sql.SQL("REVOKE {} FROM fixture_control_a").format(sql.Identifier(rol)))


@pytest.mark.parametrize("concesion,restituir",[
    ("GRANT tinotify_fixture_control TO fixture_control_a WITH ADMIN TRUE",
     "GRANT tinotify_fixture_control TO fixture_control_a WITH ADMIN FALSE"),
    ("GRANT CREATE ON SCHEMA app_fixture TO fixture_control_a",
     "REVOKE CREATE ON SCHEMA app_fixture FROM fixture_control_a"),
    ("GRANT CREATE ON DATABASE postgres TO fixture_control_a",
     "REVOKE CREATE ON DATABASE postgres FROM fixture_control_a"),
])
def test_delegacion_y_create_accidental_se_rechazan(controles,postgres_aislado,concesion,restituir):
    admin,_,_=postgres_aislado
    c=controles["a"]
    identidad,credencial,_=c.registrar()
    admin.execute(concesion)
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege): c.llamar("cerrar",identidad,credencial)
    finally:
        admin.execute(restituir)
