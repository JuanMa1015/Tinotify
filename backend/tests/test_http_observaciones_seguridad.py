"""Regresiones ASGI: datos sintéticos, dependencias obligatorias, ninguna entrega."""

import socket
import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.tests.test_alcance_unidad_sigac import lecturas
from backend.tests.test_frontera_persistencia_sigac import servicio
from backend.tests.test_sqlite_local_v2 import snapshot
from tinotify.api.demo import crear_app
from tinotify.api.real_local import AccesoLocal, NoStoreReal
from tinotify.demo.servicio import ServicioDemo
from tinotify.integrations.sigac.lectura_validada import _referencia_local
from tinotify.persistence.sqlite_local import AlmacenLocalNoDisponible, BINDING_LOCAL, CREDENCIAL_LOCAL
from tinotify.services.avisos_persistentes import ServicioAvisos

CODIGO_A = 'CODIGO-LOCAL-SINTETICO-A-' + 'a' * 32
CODIGO_B = 'CODIGO-LOCAL-SINTETICO-B-' + 'b' * 32


class SinEntregas:
    async def cerrar(self):
        pass

    async def enviar(self, *args, **kwargs):
        pytest.fail('Una observacion interna no autoriza entregas')

    async def recibos(self, *args, **kwargs):
        pytest.fail('No se deben consultar proveedores externos')


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('No se permite red externa en esta prueba')
    # TestClient usa ASGI en memoria; Windows necesita su socketpair loopback.
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket, 'getaddrinfo', prohibido)
    monkeypatch.delenv('TINOTIFY_REAL_SESSION', raising=False)
    a, b = lecturas(1)
    a2, b2 = lecturas(2)
    sa = servicio(tmp_path/'solo-sintetico-a.sqlite3')
    sb = servicio(tmp_path/'solo-sintetico-b.sqlite3')
    for s, inicial, posterior in ((sa, a, a2), (sb, b, b2)):
        s.observar_validada(inicial, clave=uuid4(), generacion_esperada=0)
        s.observar_validada(posterior, clave=uuid4(), generacion_esperada=1)

    def app(s, codigo):
        return crear_app(ServicioDemo(('d'*32, 'e'*32)), SinEntregas(), real=s,
                         acceso_real=AccesoLocal(codigo, max_fallos=2))
    with TestClient(app(sa, CODIGO_A), raise_server_exceptions=False) as ca, TestClient(app(sb, CODIGO_B)) as cb:
        yield sa, sb, ca, cb, _referencia_local(a), _referencia_local(b), b, b2


@pytest.mark.parametrize('estado', [200, 401, 404, 405, 410, 422, 429, 500, 503])
def test_respuestas_reales_sensibles_no_se_almacenan_incluidos_errores(entorno, monkeypatch, estado):
    sa, _, cliente, _, _, _, _, _ = entorno
    antes, raw = snapshot(sa), sa.almacen.ruta.read_bytes()
    headers = {'Authorization': 'Bearer ' + CODIGO_A}
    ruta = '/real/observaciones'
    metodo = 'GET'
    if estado == 401:
        headers = {}
    elif estado == 404:
        ruta = '/real/cases/' + str(uuid4())
    elif estado == 410:
        ruta = '/real/novedades'
    elif estado == 405:
        metodo = 'POST'
    elif estado == 422:
        ruta = '/real/cases/no-es-uuid'
    elif estado == 429:
        assert cliente.get(ruta).status_code == 401
        assert cliente.get(ruta).status_code == 401
    elif estado in (500, 503):
        def indisponible():
            if estado == 503:
                raise AlmacenLocalNoDisponible('Fallo sintetico de lectura')
            raise RuntimeError('CANARIO_INTERNO_SINTETICO')
        monkeypatch.setattr(sa, 'observaciones', indisponible)
    respuesta = cliente.request(metodo, ruta, headers=headers)
    assert respuesta.status_code == estado
    if estado == 500:
        assert respuesta.text == 'Internal Server Error'
    elif estado != 200:
        esperado = {401: 'Acceso local requerido', 404: 'Proceso no disponible',
            405: 'Method Not Allowed', 410: 'Avisos reales deshabilitados; consultar /real/observaciones',
            422: 'Entrada demo no valida', 429: 'Demasiados intentos; espera un minuto',
            503: 'Almacen local no disponible; estado anterior conservado'}
        assert respuesta.json() == {'detail': esperado[estado]}
    if estado == 401:
        assert respuesta.headers['www-authenticate'] == 'Bearer'
    if estado == 405:
        assert 'GET' in respuesta.headers['allow']
    assert snapshot(sa) == antes and sa.almacen.ruta.read_bytes() == raw
    assert respuesta.headers.get('cache-control') == 'no-store'


def test_aplicaciones_con_archivos_y_codigos_distintos_no_comparten_observaciones(entorno):
    sa, sb, ca, cb, caso_a, caso_b, _, _ = entorno
    antes_a, antes_b = snapshot(sa), snapshot(sb)
    ha, hb = ({'Authorization': 'Bearer ' + codigo} for codigo in (CODIGO_A, CODIGO_B))
    assert ca.get('/real/observaciones', headers=hb).status_code == 401
    assert cb.get('/real/observaciones', headers=ha).status_code == 401
    da = ca.get('/real/observaciones', headers=ha).json()
    db = cb.get('/real/observaciones', headers=hb).json()
    assert {o['caso'] for o in da['observaciones']} == {caso_a}
    assert {o['caso'] for o in db['observaciones']} == {caso_b}
    assert ca.get('/real/cases/' + caso_b, headers=ha).status_code == 404
    assert cb.get('/real/cases/' + caso_a, headers=hb).status_code == 404
    assert snapshot(sa) == antes_a and snapshot(sb) == antes_b


def test_codigo_monousuario_autoriza_archivo_completo_pero_nunca_entrega(entorno, monkeypatch):
    sa, _, cliente, _, caso_a, caso_b, b, b2 = entorno
    sa.observar_validada(b, clave=uuid4(), generacion_esperada=0)
    sa.observar_validada(b2, clave=uuid4(), generacion_esperada=1)
    antes, raw = snapshot(sa), sa.almacen.ruta.read_bytes()
    def prohibido(*args, **kwargs):
        pytest.fail('No construir Notificacion para eventos reales')
    monkeypatch.setattr('tinotify.services.avisos_persistentes.crear_notificacion', prohibido)
    h = {'Authorization': 'Bearer ' + CODIGO_A}
    r = cliente.get('/real/observaciones?entrega_externa=autorizada', headers=h)
    assert r.status_code == 200
    d = r.json()
    assert {o['caso'] for o in d['observaciones']} == {caso_a, caso_b}
    assert d['cobertura'] == 'desconocida' and d['entrega_externa'] == 'no_autorizada'
    assert all(o['creacion_reciente_acreditada'] is False for o in d['observaciones'])
    assert all(set(o) == {'id', 'caso', 'local_id', 'generacion', 'tipo', 'creacion_reciente_acreditada'}
               for o in d['observaciones'])
    with pytest.raises(PermissionError):
        ServicioAvisos(sa.almacen).pendientes(CREDENCIAL_LOCAL, binding=BINDING_LOCAL)
    assert snapshot(sa) == antes and sa.almacen.ruta.read_bytes() == raw


def test_ruta_real_inexistente_y_metodo_no_admitido_conservan_cuerpos(entorno):
    _, _, c, _, _, _, _, _ = entorno
    r = c.get('/real/ruta-inexistente-sintetica')
    assert r.status_code == 404 and r.json() == {'detail': 'Not Found'}
    assert r.headers['cache-control'] == 'no-store'
    r = c.post('/real/observaciones')
    assert r.status_code == 405 and r.headers['cache-control'] == 'no-store'
    assert r.json() == {'detail': 'Method Not Allowed'}
    # El middleware no altera otras rutas de la app ni sus cabeceras de caché.
    for ruta, estado in (('/health', 200), ('/demo/inexistente', 404), ('/reality', 404)):
        r = c.get(ruta)
        assert r.status_code == estado and 'cache-control' not in r.headers


def test_fallo_de_transporte_no_se_convierte_en_respuesta_exitosa():
    async def origen(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'x-prueba', b'preservada')]})
        await send({'type': 'http.response.body', 'body': b'contenido sintetico'})
    intentos = []
    async def cortado(message):
        intentos.append(message)
        raise OSError('Transporte sintetico cerrado')
    async def recibir():
        return {'type': 'http.disconnect'}
    with pytest.raises(OSError, match='Transporte sintetico cerrado'):
        asyncio.run(NoStoreReal(origen)({'type': 'http', 'path': '/real/observaciones',
                                       'method': 'GET', 'headers': []}, recibir, cortado))
    assert len(intentos) == 1  # no se inventa otra respuesta tras fallar send
    assert (b'cache-control', b'no-store') in intentos[0]['headers']
    assert (b'x-prueba', b'preservada') in intentos[0]['headers']
