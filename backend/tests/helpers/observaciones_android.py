"""Puente de pruebas ASGI -> consumidor TypeScript. Solo datos sintéticos.

Ejecutar desde la raíz con .venv: python -B -m backend.tests.helpers.observaciones_android
No escucha puertos HTTP, no consulta SIGAC y no escribe fuera de TemporaryDirectory.
El perfil SQLite real se usa para probar su contrato, no identifica el origen de los datos.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.tests.test_auditoria_completitud_sigac import A, B, C, documento, leer
from backend.tests.test_alcance_unidad_sigac import lecturas
from backend.tests.test_frontera_persistencia_sigac import servicio
from backend.tests.test_sqlite_local_v2 import snapshot
from tinotify.api.demo import crear_app
from tinotify.api.real_local import AccesoLocal
from tinotify.demo.novedades import ServicioNovedadesLocal
from tinotify.demo.servicio import ServicioDemo
from tinotify.persistence.sqlite_local import AlmacenLocalNoDisponible, AlmacenSqliteLocal

CODIGO = 'ACCESO-SINTETICO-LOCAL-' + 'p' * 32  # Público, solo para esta fixture.


class SinEntregas:
    async def cerrar(self):
        pass

    async def enviar(self, *args, **kwargs):
        raise AssertionError('Entrega externa prohibida en fixture Android')

    async def recibos(self, *args, **kwargs):
        raise AssertionError('Consulta a proveedores prohibida en fixture Android')


@contextmanager
def escenario(nombre):
    """Aplicación de prueba reutilizable, sin modificar producción ni abrir archivos existentes."""
    if nombre not in {'vacio', 'referencia', 'posterior', 'historica', 'dos_expedientes'}:
        raise ValueError('Escenario sintetico desconocido')
    with TemporaryDirectory(prefix='tinotify-android-sintetico-') as temporal:
        raiz = Path(temporal)
        s = servicio(raiz/'solo-sintetico-perfil-real.sqlite3')
        if nombre != 'vacio':
            s.observar_validada(leer(documento(A)), clave=uuid4(), generacion_esperada=0)
        if nombre in {'posterior', 'historica'}:
            s.observar_validada(leer(documento(A, B if nombre == 'historica' else C)),
                               clave=uuid4(), generacion_esperada=1)
        elif nombre == 'dos_expedientes':
            # Solo el segundo expediente todavía no tiene una referencia en este archivo.
            _, segundo = lecturas(1)
            s.observar_validada(segundo, clave=uuid4(), generacion_esperada=0)
        demo = ServicioNovedadesLocal(AlmacenSqliteLocal(raiz/'solo-demo.sqlite3'))
        with patch.dict(os.environ, {'TINOTIFY_REAL_SESSION': '0'}):
            app = crear_app(ServicioDemo(('a'*32, 'b'*32)), SinEntregas(), novedades=demo,
                            real=s, acceso_real=AccesoLocal(CODIGO, max_fallos=2))
            yield app, s


def capturar(respuesta):
    return {'status': respuesta.status_code, 'raw': respuesta.text,
            'headers': {k: v for k, v in respuesta.headers.items()
                        if k in {'content-type', 'cache-control', 'www-authenticate', 'allow'}}}


def capturar_escenarios():
    salida = {'codigo_ficticio': CODIGO, 'lecturas': {}, 'errores': {}}
    h = {'Authorization': 'Bearer ' + CODIGO}
    for nombre in ('vacio', 'referencia', 'posterior', 'historica', 'dos_expedientes'):
        with escenario(nombre) as (app, s), TestClient(app) as c:
            antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
            casos = c.get('/real/cases', headers=h)
            observaciones = c.get('/real/observaciones', headers=h)
            assert casos.status_code == observaciones.status_code == 200
            detalles = {caso['id']: capturar(c.get('/real/cases/'+caso['id'], headers=h)) for caso in casos.json()}
            salida['lecturas'][nombre] = {'casos': capturar(casos), 'observaciones': capturar(observaciones),
                                         'detalles': detalles}
            assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw
    with escenario('referencia') as (app, s), TestClient(app) as c:
        antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
        salida['errores']['401'] = capturar(c.get('/real/observaciones'))
        salida['errores']['404'] = capturar(c.get('/real/cases/'+str(uuid4()), headers=h))
        salida['errores']['410'] = capturar(c.get('/real/novedades', headers=h))
        with patch.object(s, 'observaciones', side_effect=AlmacenLocalNoDisponible('Fallo sintetico')):
            salida['errores']['503'] = capturar(c.get('/real/observaciones', headers=h))
        # El intento sin credencial anterior ya consumió uno de los dos fallos.
        assert c.get('/real/observaciones').status_code == 401
        salida['errores']['429'] = capturar(c.get('/real/observaciones', headers=h))
        for codigo, respuesta in salida['errores'].items():
            assert respuesta['status'] == int(codigo) and respuesta['headers']['cache-control'] == 'no-store'
        assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw
    return salida


if __name__ == '__main__':
    def prohibido(*args, **kwargs):
        raise AssertionError('Red externa prohibida en puente sintetico')
    conectar = socket.socket.connect
    def solo_loopback(s, destino):
        if isinstance(destino, tuple) and destino[0] in {'127.0.0.1', '::1', 'localhost'}:
            return conectar(s, destino)
        raise AssertionError('Destino externo prohibido en puente sintetico')
    socket.create_connection = socket.getaddrinfo = prohibido
    socket.socket.connect = solo_loopback  # Windows usa socketpair TCP para su event loop.
    print(json.dumps(capturar_escenarios(), ensure_ascii=False))
