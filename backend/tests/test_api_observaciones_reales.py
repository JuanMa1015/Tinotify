"""API real local con datos sintéticos; requiere las dependencias declaradas."""
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient

from backend.tests.test_frontera_persistencia_sigac import servicio, leer
from tinotify.api.demo import crear_app
from tinotify.api.real_local import AccesoLocal
from tinotify.demo.servicio import ServicioDemo
from tinotify.persistence.sqlite_local import AlmacenLocalNoDisponible

CODIGO = 'CODIGO-LOCAL-SINTETICO-' + 'z' * 32


class SinPush:
    async def cerrar(self):
        pass

    async def enviar(self, *args, **kwargs):
        pytest.fail('Una observacion real nunca debe alcanzar el emisor push')

    async def recibos(self, *args, **kwargs):
        pytest.fail('Las observaciones no son recibos de entrega')


def test_api_autorizada_separa_observaciones_de_avisos_y_no_inicia_monitor(tmp_path, monkeypatch):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    s.observar_validada(leer(2), clave=uuid4(), generacion_esperada=0)
    s.observar_validada(leer(3), clave=uuid4(), generacion_esperada=1)
    monkeypatch.delenv('TINOTIFY_REAL_SESSION', raising=False)
    app = crear_app(ServicioDemo(('a'*32, 'b'*32)), SinPush(), real=s, acceso_real=AccesoLocal(CODIGO))
    with TestClient(app) as c:
        assert c.get('/real/observaciones').status_code == 401
        h = {'Authorization': 'Bearer ' + CODIGO}
        r = c.get('/real/observaciones', headers=h)
        assert r.status_code == 200 and r.headers['cache-control'] == 'no-store'
        datos = r.json()
        assert datos['cobertura'] == 'desconocida' and len(datos['observaciones']) == 1
        assert datos['entrega_externa'] == 'no_autorizada'
        assert datos['observaciones'][0]['creacion_reciente_acreditada'] is False
        assert c.get('/real/novedades').status_code == 401
        assert c.get('/real/novedades', headers=h).status_code == 410
        casos = c.get('/real/cases', headers=h).json()
        detalle = c.get('/real/cases/' + casos[0]['id'], headers=h).json()
        assert detalle['cobertura'] == 'desconocida' and 'actuaciones' not in detalle
        assert len(detalle['ocurrencias']) == 3
        assert c.get('/real/monitor', headers=h).status_code == 404
        def fallar():
            raise AlmacenLocalNoDisponible('Fallo sintetico de lectura')
        monkeypatch.setattr(s, 'observaciones', fallar)
        error = c.get('/real/observaciones', headers=h)
        assert error.status_code == 503 and 'observaciones' not in error.json()
