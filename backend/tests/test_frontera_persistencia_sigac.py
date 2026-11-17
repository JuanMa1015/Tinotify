"""Frontera de aplicación: transportes MockTransport son instrumentación privilegiada de test."""

from copy import deepcopy
from pathlib import Path
import pickle
import socket
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.tests.helpers.sigac_detalle import detalle
from backend.tests.test_integridad_historial_sigac import bloque, pagina, cliente_sintetico, USUARIO, CLAVE
from backend.tests.test_sqlite_local_v2 import snapshot, lote
from backend.tests.test_sigac_flujo import historial_generico
from tinotify.demo.novedades import ServicioNovedadesLocal, INSTANCIA_REAL, CASO_OBSERVADO
from tinotify.integrations.sigac.lectura_validada import (
    LecturaSigacValidada, leer_historial_validado, _referencia_local,
)
from tinotify.integrations.sigac.sigac_client import SigacIdentityError
from tinotify.persistence.sqlite_local import (
    AlmacenSqliteLocal, CREDENCIAL_LOCAL, BINDING_LOCAL, WORKER_LOCAL, ConflictoPersistenciaLocal,
)
from tinotify.services.observacion_local import ObservadorLocal, ObservacionRechazada
from tinotify.services.seguimiento import ServicioSeguimiento


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('No se permite red real')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)


def servicio(ruta):
    return ServicioNovedadesLocal(AlmacenSqliteLocal(ruta, perfil='real'), instancia=INSTANCIA_REAL)


def leer(n=2):
    contenido = pagina(*(bloque(f'CONTENIDO_SINTETICO_{i}') for i in range(n)))
    with cliente_sintetico([contenido]) as (cliente, llamadas):
        cliente.autenticar(USUARIO, CLAVE, tipo='2', total_casos_esperado=1)
        lectura = leer_historial_validado(cliente, 101)
        assert len(llamadas) == 7
    return lectura


def test_respuesta_validada_es_unica_entrada_real_y_sobrevive_reapertura(tmp_path):
    ruta = tmp_path/'solo-sintetico-perfil-real.sqlite3'
    s, lectura, clave = servicio(ruta), leer(), uuid4()
    inicial = s.observar_validada(lectura, clave=clave, generacion_esperada=0)
    assert inicial['baseline'] is True and inicial['novedades_nuevas'] == 0
    caso = inicial['caso']
    antes, raw = snapshot(s), ruta.read_bytes()
    # Nueva lectura validada y conexión nueva: el recibo, no la instancia RAM,
    # determina idempotencia. Las pruebas existentes cubren reinicio de procesos.
    s = servicio(ruta)
    repetida = s.observar_validada(leer(), clave=clave, generacion_esperada=0)
    assert repetida == inicial and snapshot(s) == antes and ruta.read_bytes() == raw
    nueva = s.observar_validada(leer(3), clave=uuid4(), generacion_esperada=1)
    assert nueva['caso'] == caso and nueva['novedades_nuevas'] == 1
    assert len(s.observaciones()['observaciones']) == 1
    assert s.observar_validada(leer(3), clave=uuid4(), generacion_esperada=2)['novedades_nuevas'] == 0
    assert len(s.observaciones()['observaciones']) == 1


@pytest.mark.parametrize('falsa', [SimpleNamespace(validado=True, perfil='real'),
                                 {'validado': True}, object.__new__(LecturaSigacValidada)])
def test_acreditacion_fabricada_no_abre_transaccion(tmp_path, falsa):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    with pytest.raises(PermissionError):
        s.observar_validada(falsa, clave=uuid4(), generacion_esperada=0)
    with pytest.raises(PermissionError):
        with s.almacen._transaccion_sigac(falsa, CASO_OBSERVADO):
            pytest.fail('No debe abrirse')
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


def test_lectura_no_tiene_constructor_desde_datos_ni_serializacion():
    with pytest.raises(TypeError):
        LecturaSigacValidada(validado=True, actuaciones=lote())
    lectura = leer()
    assert repr(lectura) == 'LecturaSigacValidada()'
    with pytest.raises(TypeError):
        pickle.dumps(lectura)
    with pytest.raises(TypeError):
        deepcopy(lectura)
    with pytest.raises(AttributeError):
        lectura.validado = True


@pytest.mark.parametrize('perfil', ['real', 'sintetico'])
@pytest.mark.parametrize('marcadores', ['completos', 'solo_cabecera'])
def test_rechazada_no_se_convierte_en_persistible_cambiando_perfil(tmp_path, perfil, marcadores):
    s = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path/'solo-sintetico.sqlite3', perfil=perfil))
    html = detalle(historial_generico(), cabecera='202')
    if marcadores == 'solo_cabecera':
        html = historial_generico().replace('<body>', '<body><div>Información del caso Nro.202 - FICTICIO</div>')
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    with cliente_sintetico([html], envolver_detalle=False) as (cliente, _):
        cliente.autenticar(USUARIO, CLAVE, tipo='2', total_casos_esperado=1)
        with pytest.raises(SigacIdentityError):
            leer_historial_validado(cliente, 101)
    with pytest.raises(PermissionError):
        s.observar_html(CASO_OBSERVADO, html, clave=uuid4(), generacion_esperada=0)
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


@pytest.mark.parametrize('perfil', ['real', 'sintetico'])
def test_respuesta_sigac_no_entra_por_servicios_genericos(tmp_path, perfil):
    almacen = AlmacenSqliteLocal(tmp_path/'solo-sintetico.sqlite3', perfil=perfil)
    s = ServicioNovedadesLocal(almacen)
    with cliente_sintetico([pagina(bloque())]) as (cliente, _):
        cliente.autenticar(USUARIO, CLAVE, tipo='2', total_casos_esperado=1)
        raw = cliente.consultar_historial(101)
    antes = snapshot(s)
    with pytest.raises(PermissionError):
        s.observar(CASO_OBSERVADO, raw, clave=uuid4(), generacion_esperada=0)
    with pytest.raises(PermissionError):
        ServicioSeguimiento(almacen).sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, raw,
            clave=uuid4(), worker=WORKER_LOCAL, binding=BINDING_LOCAL)
    if perfil == 'sintetico':
        with pytest.raises(PermissionError):
            s.observar_validada(leer(), clave=uuid4(), generacion_esperada=0)
    assert snapshot(s) == antes


def test_transaccion_real_directa_y_cambio_de_perfil_rechazados(tmp_path):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    with pytest.raises(AttributeError):
        s.almacen.perfil = 'sintetico'
    with pytest.raises(PermissionError):
        with s.almacen.transaccion(CREDENCIAL_LOCAL):
            pytest.fail('La transaccion real publica no admite escrituras')
    with pytest.raises(PermissionError):
        ObservadorLocal(s.almacen, INSTANCIA_REAL).observar(CASO_OBSERVADO, lote(), clave=uuid4(),
            generacion_esperada=0, titulo='FICTICIO', contenido_vista=lambda _: {})
    # El origen SIGAC tampoco puede cambiarse cambiando solamente el perfil.
    sintetico = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path/'demo.sqlite3'), instancia=INSTANCIA_REAL)
    with pytest.raises(PermissionError):
        sintetico.observar(CASO_OBSERVADO, lote(), clave=uuid4(), generacion_esperada=0)
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


def test_monitor_real_se_rechaza_incluso_con_un_doble(tmp_path):
    from tinotify.services.monitor_local import monitorear
    from tinotify.services.consulta_real_local import IdentidadExpedienteNoVerificada
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    antes = snapshot(s)
    def no_autenticar():
        pytest.fail('El monitor real debe detenerse antes de autenticar')
    with pytest.raises(IdentidadExpedienteNoVerificada):
        monitorear(SimpleNamespace(), no_autenticar, total_casos=1, indice_caso=1, servicio=s, max_ciclos=1)
    assert snapshot(s) == antes


def test_contexto_interno_y_unidad_real_tampoco_aceptan_datos_sin_lectura(tmp_path):
    from tinotify.persistence.sqlite_local import UnidadSqliteLocal
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    with pytest.raises(PermissionError):
        with s.almacen._transaccion(CREDENCIAL_LOCAL):
            pytest.fail('No debe abrirse sin lectura')
    with s.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
        with pytest.raises(sqlite3.OperationalError):
            unidad._c.execute("UPDATE meta SET valor=valor")
    # Disponer de una conexión SQL es privilegio fuera de la frontera; incluso
    # así la unidad real conserva la guarda de sus métodos de escritura.
    with sqlite3.connect(s.almacen.ruta) as conexion:
        unidad = UnidadSqliteLocal(conexion, s.almacen._politica, lambda: 0, False, 'real')
        with pytest.raises(PermissionError):
            unidad.seguir(INSTANCIA_REAL, CASO_OBSERVADO, 'FICTICIO')
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


def test_conflictos_de_digest_y_generacion_no_modifican_real(tmp_path):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    clave = uuid4()
    s.observar_validada(leer(), clave=clave, generacion_esperada=0)
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    with pytest.raises(ConflictoPersistenciaLocal):
        s.observar_validada(leer(3), clave=clave, generacion_esperada=0)
    with pytest.raises(ConflictoPersistenciaLocal):
        s.observar_validada(leer(3), clave=uuid4(), generacion_esperada=0)
    with pytest.raises(ObservacionRechazada):
        s.observar_validada(leer(1), clave=uuid4(), generacion_esperada=1)
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


def test_seguimiento_sintetico_digest_repeticion_y_conflicto_estrictos(tmp_path):
    almacen = AlmacenSqliteLocal(tmp_path/'solo-sintetico.sqlite3')
    s = ServicioNovedadesLocal(almacen)
    seguimiento, clave = ServicioSeguimiento(almacen), uuid4()
    kwargs = dict(clave=clave, worker=WORKER_LOCAL, binding=BINDING_LOCAL)
    primero = seguimiento.sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, lote(), **kwargs)
    antes, raw = snapshot(s), almacen.ruta.read_bytes()
    assert seguimiento.sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, lote(), **kwargs).repetido
    with pytest.raises(ConflictoPersistenciaLocal):
        seguimiento.sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, lote(3), **kwargs)
    assert snapshot(s) == antes and almacen.ruta.read_bytes() == raw
    assert primero.generacion == 1
    with pytest.raises(ConflictoPersistenciaLocal):
        seguimiento.sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, lote(3), clave=uuid4(),
                                worker=WORKER_LOCAL, binding=BINDING_LOCAL)
    assert snapshot(s) == antes
    siguiente = seguimiento.sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, lote(3), clave=uuid4(),
        worker=WORKER_LOCAL, binding=BINDING_LOCAL, generacion_esperada=1)
    assert siguiente.generacion == 2 and len(s.novedades()) == 1  # perfil sintético


def test_lectura_no_permite_elegir_otro_expediente_en_transaccion(tmp_path):
    s, lectura = servicio(tmp_path/'solo-sintetico.sqlite3'), leer()
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    with pytest.raises(PermissionError):
        with s.almacen._transaccion_sigac(lectura, str(uuid4())):
            pytest.fail('No se permite cambiar el expediente acreditado')
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


def test_recibo_anterior_sin_digest_no_se_completa_ni_se_migra(tmp_path):
    almacen = AlmacenSqliteLocal(tmp_path/'solo-sintetico.sqlite3')
    s, clave = ServicioNovedadesLocal(almacen), uuid4()
    s.observar(CASO_OBSERVADO, lote(), clave=clave, generacion_esperada=0)
    # Simular un recibo que dejó la antigua interfaz. Solo fixture temporal.
    with almacen.transaccion(CREDENCIAL_LOCAL) as u:
        u._c.execute('UPDATE sincronizaciones SET contenido_hash=NULL,digest_version=NULL')
    antes, raw = snapshot(s), almacen.ruta.read_bytes()
    with pytest.raises(ConflictoPersistenciaLocal):
        ServicioSeguimiento(almacen).sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, lote(),
            clave=clave, worker=WORKER_LOCAL, binding=BINDING_LOCAL)
    assert snapshot(s) == antes and almacen.ruta.read_bytes() == raw


def test_commit_incierto_real_recupera_recibo_sin_duplicar(tmp_path, monkeypatch):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    s.observar_validada(leer(), clave=uuid4(), generacion_esperada=0)
    commit, perdido = s.almacen._commit, []
    def perder(conexion):
        commit(conexion)
        if not perdido:
            perdido.append(True)
            raise sqlite3.OperationalError('FALLO SINTETICO POST COMMIT')
    monkeypatch.setattr(s.almacen, '_commit', perder)
    clave = uuid4()
    s.observar_validada(leer(3), clave=clave, generacion_esperada=1)
    assert len(s.observaciones()['observaciones']) == 1
    antes = snapshot(s)
    assert s.observar_validada(leer(3), clave=clave, generacion_esperada=1)['novedades_nuevas'] == 0
    assert snapshot(s) == antes
