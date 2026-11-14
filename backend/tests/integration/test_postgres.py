"""Integracion contra un contenedor desechable con TLS, nunca Supabase remoto."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
import time
from uuid import UUID,uuid4

import psycopg
import pytest

from tinotify.persistence.monitor import _validar_v2
from tinotify.persistence.postgres import ConexionInterrumpida, ConfiguracionPostgres, UnidadPostgres
from tinotify.services.avisos_persistentes import ServicioAvisos


def sincronizar(entorno, observaciones, *, credencial="a", clave=None):
    return entorno["servicio"].sincronizar(credencial,"CASO_FICTICIO",observaciones,
        clave=clave or uuid4(),worker=uuid4(),binding=entorno["binding"])


def avisos(entorno,credencial="a"):
    with entorno["almacenes"]["notifications"].transaccion(credencial,lectura=True) as unidad:
        return unidad.pendientes(entorno["binding"])


def test_linea_base_versiones_ausentes_y_aviso_idempotente(entorno_pg,actuacion_ficticia):
    a = actuacion_ficticia()
    sincronizar(entorno_pg,[a,a])
    assert avisos(entorno_pg)==[]
    sincronizar(entorno_pg,[a])
    estado = entorno_pg["servicio"].estado("a",binding=entorno_pg["binding"])
    _validar_v2(estado)
    assert len(estado["cases"]["CASO_FICTICIO"]["records"])==2
    clave=uuid4()
    recibo=sincronizar(entorno_pg,[a,a,a],clave=clave)
    repetido=sincronizar(entorno_pg,[a,a,a],clave=clave)
    assert recibo.trabajo_id==repetido.trabajo_id and repetido.repetido
    assert len(avisos(entorno_pg))==1
    sincronizar(entorno_pg,[a,a,a])
    assert len(avisos(entorno_pg))==1


def test_edicion_estable_y_retorno_a_version_anterior(entorno_pg,actuacion_ficticia):
    a=actuacion_ficticia("ID_FICTICIO")
    b=replace(a,descripcion="OTRO CONTENIDO FICTICIO")
    for observacion in (a,b,a): sincronizar(entorno_pg,[observacion])
    assert [n["tipo"] for n in avisos(entorno_pg)]==["modificacion_confirmada"]*2
    estado=entorno_pg["servicio"].estado("a",binding=entorno_pg["binding"])
    assert len(estado["cases"]["CASO_FICTICIO"]["records"])==1


def test_cambio_ambiguo_no_es_nuevo_confirmado(entorno_pg,actuacion_ficticia):
    a=actuacion_ficticia()
    sincronizar(entorno_pg,[a])
    sincronizar(entorno_pg,[replace(a,descripcion="DIFERENCIA FICTICIA")])
    assert avisos(entorno_pg)[0]["tipo"]=="cambio_ambiguo"


def test_aislamiento_tenant_caso_y_conexion_reutilizada(entorno_pg,actuacion_ficticia):
    sincronizar(entorno_pg,[actuacion_ficticia()])
    sincronizar(entorno_pg,[actuacion_ficticia(),actuacion_ficticia()])
    assert avisos(entorno_pg,"b")==[]
    assert len(avisos(entorno_pg,"a"))==1
    assert entorno_pg["servicio"].estado("b",binding=entorno_pg["binding"])["cases"]=={}
    with pytest.raises(RuntimeError,match="ROLLBACK FICTICIO"):
        with entorno_pg["almacenes"]["api"].transaccion("b") as unidad:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                unidad._conexion.execute("SELECT * FROM app.actuaciones")
            # La transaccion SQL queda abortada y debe salir por rollback.
            raise RuntimeError("ROLLBACK FICTICIO")


def test_rollback_despues_de_crear_eventos_es_atomico(entorno_pg,actuacion_ficticia,monkeypatch):
    a=actuacion_ficticia()
    sincronizar(entorno_pg,[a])
    anterior=entorno_pg["servicio"].estado("a",binding=entorno_pg["binding"])
    original=UnidadPostgres.confirmar
    def fallar(self,*args):
        original(self,*args)
        raise RuntimeError("FALLO FICTICIO ANTES DE COMMIT")
    with monkeypatch.context() as cambio:
        cambio.setattr(UnidadPostgres,"confirmar",fallar)
        with pytest.raises(RuntimeError): sincronizar(entorno_pg,[a,a])
    assert avisos(entorno_pg)==[]
    assert entorno_pg["servicio"].estado("a",binding=entorno_pg["binding"])==anterior


def test_concurrencia_misma_operacion_no_duplica_avisos(entorno_pg,actuacion_ficticia):
    a=actuacion_ficticia()
    sincronizar(entorno_pg,[a])
    clave=uuid4()
    with ThreadPoolExecutor(max_workers=2) as workers:
        resultados=list(workers.map(lambda _:sincronizar(entorno_pg,[a,a],clave=clave),range(2)))
    assert sum(r.repetido for r in resultados)==1
    assert len(avisos(entorno_pg))==1


def test_revocacion_y_fuente_institucional_no_habilitada(entorno_pg,actuacion_ficticia):
    entorno_pg["admin"].execute("UPDATE app_private.accesos_sigac SET fuente='sigac' WHERE estudiante_id=%s",(entorno_pg["perfiles"]["a"],))
    with pytest.raises(PermissionError): sincronizar(entorno_pg,[actuacion_ficticia()])
    assert avisos(entorno_pg)==[]


def test_aviso_procesado_no_reaparece_y_no_se_puede_marcar_ajeno(entorno_pg,actuacion_ficticia):
    a=actuacion_ficticia()
    sincronizar(entorno_pg,[a])
    sincronizar(entorno_pg,[a,a])
    evento=UUID(avisos(entorno_pg)[0]["id"])
    with pytest.raises(PermissionError):
        with entorno_pg["almacenes"]["notifications"].transaccion("b") as unidad:
            unidad.procesar_aviso(evento,entorno_pg["binding"])
    for _ in range(2):
        with entorno_pg["almacenes"]["notifications"].transaccion("a") as unidad:
            unidad.procesar_aviso(evento,entorno_pg["binding"])
    assert avisos(entorno_pg)==[]


def test_tls_rechaza_nombre_de_servidor_incorrecto(entorno_pg):
    cfg=ConfiguracionPostgres(entorno_pg["roles"]["sync"],entorno_pg["ca"])
    opciones=cfg.opciones()
    opciones["host"]="nombre-no-verificado.invalid"
    with pytest.raises(psycopg.OperationalError): psycopg.connect(**opciones)


def test_conexion_interrumpida_revierte_y_pool_se_recupera(entorno_pg,actuacion_ficticia):
    a=actuacion_ficticia()
    sincronizar(entorno_pg,[a])
    almacen=entorno_pg["almacenes"]["sync"]
    clave=uuid4()
    with pytest.raises(ConexionInterrumpida):
        with almacen.transaccion("a") as unidad:
            seguimiento=unidad.seguir("local","CASO_FICTICIO",entorno_pg["servicio"].politica.firma("local"))
            unidad.reservar(seguimiento,clave,uuid4(),entorno_pg["binding"])
            pid=unidad._conexion.execute("SELECT pg_backend_pid()").fetchone()[0]
            entorno_pg["admin"].execute("SELECT pg_terminate_backend(%s)",(pid,))
            unidad.leer_caso(seguimiento,entorno_pg["binding"])
    assert not sincronizar(entorno_pg,[a,a],clave=clave).repetido
    assert len(avisos(entorno_pg))==1


def test_avisos_genericos_conservan_prioridad_sin_informacion_del_caso(entorno_pg,actuacion_ficticia):
    a=actuacion_ficticia()
    sincronizar(entorno_pg,[a])
    sincronizar(entorno_pg,[a,a])
    servicio=ServicioAvisos(entorno_pg["almacenes"]["notifications"])
    aviso=servicio.pendientes("a",binding=entorno_pg["binding"])[0]
    assert aviso.notificacion.prioridad.value=="alta"
    assert "CASO_FICTICIO" not in aviso.notificacion.mensaje
    servicio.procesar("a",aviso.id,binding=entorno_pg["binding"])
    assert servicio.pendientes("a",binding=entorno_pg["binding"])==()


def test_contexto_se_borra_en_pool_y_guc_no_es_autenticacion(entorno_pg):
    almacen=entorno_pg["almacenes"]["api"]
    with almacen.transaccion("a",lectura=True): pass
    with almacen._pool.connection() as conexion:
        assert conexion.execute("SELECT nullif(current_setting('tinotify.subject',true),'')").fetchone()[0] is None
    with pytest.raises(PermissionError):
        with almacen.transaccion("user_id_del_cliente"): pass


def test_caso_sin_atestacion_no_puede_sincronizar(entorno_pg,actuacion_ficticia):
    with pytest.raises(PermissionError):
        entorno_pg["servicio"].sincronizar("a","OTRO_CASO_FICTICIO",[actuacion_ficticia()],
            clave=uuid4(),worker=uuid4(),binding=entorno_pg["binding"])
    estado=entorno_pg["servicio"].estado("a",binding=entorno_pg["binding"])
    assert estado["cases"]=={}


def test_politica_cambiada_no_se_actualiza_ni_emite_historicos(entorno_pg,actuacion_ficticia):
    sincronizar(entorno_pg,[actuacion_ficticia()])
    entorno_pg["admin"].execute("UPDATE app.estados_reconciliacion SET trust_policy=repeat('f',64) WHERE estudiante_id=%s",(entorno_pg["perfiles"]["a"],))
    from tinotify.persistence.postgres import ConflictoPersistencia
    with pytest.raises(ConflictoPersistencia): sincronizar(entorno_pg,[actuacion_ficticia()])
    assert avisos(entorno_pg)==[]


def test_bloqueo_real_y_rollback_desbloquean_segunda_sesion(entorno_pg,actuacion_ficticia):
    a=actuacion_ficticia()
    sincronizar(entorno_pg,[a])
    preparado,liberar=Event(),Event()
    pids=[]
    def mantener_bloqueo():
        with pytest.raises(RuntimeError,match="ROLLBACK CONTROLADO"):
            with entorno_pg["almacenes"]["sync"].transaccion("a") as unidad:
                unidad.seguir("local","CASO_FICTICIO",entorno_pg["servicio"].politica.firma("local"))
                pids.append(unidad._conexion.execute("SELECT pg_backend_pid()").fetchone()[0])
                preparado.set()
                assert liberar.wait(5)
                raise RuntimeError("ROLLBACK CONTROLADO")
    with ThreadPoolExecutor(max_workers=2) as workers:
        primero=workers.submit(mantener_bloqueo)
        assert preparado.wait(5)
        segundo=workers.submit(sincronizar,entorno_pg,[a,a])
        try:
            deadline=time.monotonic()+2
            while True:
                observado=entorno_pg["admin"].execute("""SELECT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_stat_activity WHERE application_name='tinotify-persistencia'
                    AND wait_event_type='Lock' AND %s=ANY(pg_catalog.pg_blocking_pids(pid)))""",(pids[0],)).fetchone()[0]
                if observado: break
                assert time.monotonic()<deadline
                time.sleep(.02)
        finally:
            liberar.set()
        primero.result()
        assert segundo.result().generacion==2
    assert len(avisos(entorno_pg))==1


@pytest.mark.parametrize("grant,revoke", [
    ("GRANT tinotify_state_writer TO fixture_sync", "REVOKE tinotify_state_writer FROM fixture_sync"),
    ("GRANT SELECT(local_id) ON app.actuaciones TO fixture_sync", "REVOKE SELECT(local_id) ON app.actuaciones FROM fixture_sync"),
])
def test_privilegio_directo_o_membresia_accidental_se_rechaza(entorno_pg,actuacion_ficticia,grant,revoke):
    # Solo rol ficticio del contenedor desechable; nunca provisiones remotas.
    entorno_pg["admin"].execute(grant)
    try:
        with pytest.raises(PermissionError): sincronizar(entorno_pg,[actuacion_ficticia()])
    finally:
        entorno_pg["admin"].execute(revoke)


@pytest.mark.parametrize("grant", [
    "GRANT EXECUTE ON FUNCTION app_private.actor() TO PUBLIC",
    "GRANT SELECT(local_id) ON app.actuaciones TO tinotify_api",
])
def test_auditoria_detecta_grants_residuales_incluso_public_y_columna(entorno_pg,grant):
    ruta=Path(__file__).resolve().parents[3]/"supabase/migrations/20261114010000_habilitar_persistencia_sintetica.sql"
    bloque=ruta.read_text(encoding="utf-8").split("DO $auditoria$",1)[1].split("$auditoria$;",1)[0]
    with pytest.raises(psycopg.errors.RaiseException):
        with entorno_pg["admin"].transaction():
            entorno_pg["admin"].execute(grant)
            entorno_pg["admin"].execute("DO $auditoria$"+bloque+"$auditoria$;")
