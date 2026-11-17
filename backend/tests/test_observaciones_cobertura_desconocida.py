"""Política de consulta real; solo HTTP simulado y archivos temporales."""
import socket
from uuid import uuid4

import pytest

from backend.tests.test_auditoria_completitud_sigac import A, B, C, D, documento, leer, servicio
from backend.tests.test_sqlite_local_v2 import snapshot
from tinotify.demo.novedades import ServicioNovedadesLocal, CASO_OBSERVADO, html_historial_sintetico
from tinotify.integrations.sigac.sigac_client import SigacClientError
from tinotify.persistence.sqlite_local import AlmacenSqliteLocal, BINDING_LOCAL, CREDENCIAL_LOCAL
from tinotify.services.avisos_persistentes import ServicioAvisos
from tinotify.services.observacion_local import ObservacionRechazada


@pytest.fixture(autouse=True)
def sin_entregas(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('No se permite red ni conversion a notificacion real')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)
    # No basta comprobar que no hay red: tampoco debe construirse Notificacion.
    monkeypatch.setattr('tinotify.services.avisos_persistentes.crear_notificacion', prohibido)


def observar(s, *bloques, gen=0, clave=None):
    return s.observar_validada(leer(documento(*bloques)), clave=clave or uuid4(), generacion_esperada=gen)


def test_referencia_observada_y_cobertura_no_depende_de_estabilidad(tmp_path):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    r = observar(s, A, B)
    assert r['baseline'] and r['novedades_nuevas'] == 0
    assert s.observaciones() == {'contrato_version': 1, 'cobertura': 'desconocida',
        'referencia': 'ocurrencias_observadas', 'entrega_externa': 'no_autorizada', 'observaciones': []}
    caso = s.listar_casos()[0]
    assert caso['ocurrencias_observadas'] == 2 and caso['referencia_establecida']
    assert observar(s, B, A, gen=1)['novedades_nuevas'] == 0
    assert observar(s, A, B, gen=2)['novedades_nuevas'] == 0
    assert s.observaciones()['cobertura'] == 'desconocida'
    detalle = s.detalle(caso['id'])
    assert len(detalle['ocurrencias']) == 2
    assert all(set(a) == {'local_id', 'generacion'} for a in detalle['ocurrencias'])
    assert 'novedades_pendientes' not in detalle and 'total_actuaciones' not in detalle


@pytest.mark.parametrize('posterior,cantidad', [(C, 1), (A, 1), (B+C, 2)])
def test_ocurrencias_adicionales_duplicadas_o_antiguas_solo_son_observaciones(tmp_path, posterior, cantidad):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    observar(s, A)
    assert observar(s, A, posterior, gen=1)['novedades_nuevas'] == cantidad
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    for _ in range(2):
        datos = s.observaciones()
        assert datos['entrega_externa'] == 'no_autorizada' and len(datos['observaciones']) == cantidad
        for e in datos['observaciones']:
            assert e['tipo'] == 'primera_observacion' and e['creacion_reciente_acreditada'] is False
            assert set(e) == {'id', 'caso', 'local_id', 'generacion', 'tipo', 'creacion_reciente_acreditada'}
        s.listar_casos(), s.detalle(datos['observaciones'][0]['caso'])
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


@pytest.mark.parametrize('posterior', [(A,), (A, D), (A, B.replace('CONTENIDO_B_SINTETICO', 'EDICION_SINTETICA'))])
def test_ausencias_y_cambio_sin_identidad_no_modifican_ninguna_tabla(tmp_path, posterior):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    observar(s, A, B)
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    with pytest.raises(ObservacionRechazada):
        observar(s, *posterior, gen=1)
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


@pytest.mark.parametrize('tipo', ['identidad', 'parser'])
def test_rechazo_de_lectura_no_emite_acreditacion_ni_modifica_base(tmp_path, tipo):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    observar(s, A)
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    cuerpo = documento(A, C)
    if tipo == 'identidad':
        cuerpo = cuerpo.replace('value="101"', 'value="202"')
        assert cuerpo != documento(A, C)
    else:
        cuerpo = documento(A, C.replace('2020-01-01 10:00:00', 'fecha malformada'))
    with pytest.raises(SigacClientError):
        s.observar_validada(leer(cuerpo), clave=uuid4(), generacion_esperada=1)
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


def test_reinicio_y_reenvio_preservan_eventos_sin_convertirlos_en_avisos(tmp_path):
    ruta = tmp_path/'solo-sintetico.sqlite3'
    s = servicio(ruta)
    observar(s, A)
    clave = uuid4()
    observar(s, A, B, gen=1, clave=clave)
    antes, raw = snapshot(s), ruta.read_bytes()
    s = servicio(ruta)
    assert observar(s, A, B, gen=1, clave=clave)['novedades_nuevas'] == 0
    assert len(s.observaciones()['observaciones']) == 1
    assert snapshot(s) == antes and ruta.read_bytes() == raw
    # Una propiedad del consumidor no autoriza convertir el perfil persistido.
    s.sintetico = True
    with pytest.raises(PermissionError):
        s.novedades()
    with pytest.raises(PermissionError):
        ServicioAvisos(s.almacen).pendientes(CREDENCIAL_LOCAL, binding=BINDING_LOCAL)
    assert snapshot(s) == antes and ruta.read_bytes() == raw


def test_error_de_consulta_no_es_lista_vacia(tmp_path, monkeypatch):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    def fallar(*args, **kwargs):
        raise RuntimeError('fallo local sintetico')
    monkeypatch.setattr(s.almacen, 'transaccion', fallar)
    with pytest.raises(RuntimeError):
        s.observaciones()


def test_demo_sintetica_conserva_avisos_sin_acceso_al_perfil_real(tmp_path, monkeypatch):
    # Restaurar únicamente el formateador de avisos para este almacén sintético.
    from tinotify.domain.notificaciones import crear_notificacion
    monkeypatch.setattr('tinotify.services.avisos_persistentes.crear_notificacion', crear_notificacion)
    s = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path/'solo-demo.sqlite3'))
    s.observar_html(CASO_OBSERVADO, html_historial_sintetico(1))
    s.observar_html(CASO_OBSERVADO, html_historial_sintetico(2))
    assert len(s.novedades()) == 1 and s.detalle(CASO_OBSERVADO)['actuaciones'][1]['nueva']
    with pytest.raises(PermissionError):
        s.observaciones()
