"""Aislamiento interno por expediente; solo HTTP simulado y SQLite temporal."""

from dataclasses import replace
import socket
from types import SimpleNamespace
from urllib.parse import parse_qs
from uuid import UUID, uuid4

import pytest

from backend.tests.helpers.sigac_detalle import detalle
from backend.tests.test_frontera_persistencia_sigac import servicio
from backend.tests.test_sigac_flujo import cliente_servidor, autenticar, historial_generico, html
from backend.tests.test_sqlite_local_v2 import snapshot
from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.integrations.sigac.lectura_validada import leer_historial_validado, _referencia_local
from tinotify.persistence.sqlite_local import CREDENCIAL_LOCAL, WORKER_LOCAL, BINDING_LOCAL


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('La prueba solo admite HTTP simulado')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)


def lecturas(n):
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        def responder(peticion):
            numero = parse_qs(peticion.content.decode())['hidCaso'][0]
            bloques = []
            for i in range(n):
                texto = historial_generico(f'CONTENIDO_SINTETICO_{i}')
                texto = texto.removeprefix('<html><body>').removesuffix('</body></html>')
                bloques.append(texto.replace('historial_ficticio', f'historial_sintetico_{i}'))
            return html(detalle(''.join(bloques), numero=numero))
        servidor.cambios['casos.formCaso.con'] = responder
        return tuple(leer_historial_validado(cliente, numero) for numero in (101, 202))


@pytest.fixture
def contexto(tmp_path):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    for lectura in lecturas(1):
        s.observar_validada(lectura, clave=uuid4(), generacion_esperada=0)
    a, b = lecturas(2)
    for lectura in (a, b):
        s.observar_validada(lectura, clave=uuid4(), generacion_esperada=1)
    ca, cb = _referencia_local(a), _referencia_local(b)
    with s.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as u:
        sa, sb = (u.buscar_seguimiento(INSTANCIA_REAL, c) for c in (ca, cb))
        registros_b = u.leer_caso(sb, BINDING_LOCAL)['records']
    # Reserva legítima para B: probar digest y confirmación de un trabajo vigente,
    # no esconder el fallo detrás de un token inexistente o una reserva vencida.
    with s.almacen._transaccion_sigac(b, cb) as u:
        reserva_b = u.reservar(sb, uuid4(), WORKER_LOCAL, BINDING_LOCAL)
    eventos = {v['caso']: UUID(v['id']) for v in s.observaciones()['observaciones']}
    return SimpleNamespace(s=s, a=a, b=b, ca=ca, cb=cb, sa=sa, sb=sb,
        reserva_b=reserva_b, registros_b=registros_b, eventos=eventos,
        politica=s.almacen._politica.firma(INSTANCIA_REAL))


def operar_b(u, c, operacion):
    if operacion == 'seguir':
        u.seguir(INSTANCIA_REAL, c.cb, c.politica)
    elif operacion == 'otra_instancia':
        u.seguir('instancia-sintetica-ajena', c.ca, c.politica)
    elif operacion == 'reservar':
        u.reservar(c.sb, uuid4(), WORKER_LOCAL, BINDING_LOCAL)
    elif operacion == 'digest':
        u.asociar_digest(c.reserva_b, 'a'*64)
    elif operacion == 'digest_reserva_disfrazada':
        u.asociar_digest(replace(c.reserva_b, seguimiento=c.sa), 'a'*64)
    elif operacion == 'confirmar':
        u.confirmar(c.reserva_b, c.registros_b, [], c.politica)
    elif operacion == 'confirmar_reserva_disfrazada':
        u.confirmar(replace(c.reserva_b, seguimiento=c.sa), c.registros_b, [], c.politica)
    elif operacion == 'vista':
        u.guardar_vista(c.cb, 'Expediente local', [(r['local_id'], r['version_hash'], {}) for r in c.registros_b])
    elif operacion == 'evento':
        u.procesar_aviso(c.eventos[c.cb], BINDING_LOCAL)
    else:
        raise AssertionError('Operacion de prueba desconocida')


@pytest.mark.parametrize('operacion', [
    'seguir', 'otra_instancia', 'reservar', 'digest', 'digest_reserva_disfrazada',
    'confirmar', 'confirmar_reserva_disfrazada', 'vista', 'evento',
])
def test_ninguna_escritura_puede_salir_del_expediente_acreditado(contexto, operacion):
    c = contexto
    antes, raw = snapshot(c.s), c.s.almacen.ruta.read_bytes()
    with pytest.raises(PermissionError):
        with c.s.almacen._transaccion_sigac(c.a, c.ca) as u:
            operar_b(u, c, operacion)
    assert snapshot(c.s) == antes and c.s.almacen.ruta.read_bytes() == raw


def test_contexto_base_interno_conserva_mismo_alcance(contexto):
    c = contexto
    antes, raw = snapshot(c.s), c.s.almacen.ruta.read_bytes()
    with pytest.raises(PermissionError):
        with c.s.almacen._transaccion(CREDENCIAL_LOCAL, lectura_sigac=c.a, caso_sigac=c.ca) as u:
            u.reservar(c.sb, uuid4(), WORKER_LOCAL, BINDING_LOCAL)
    assert snapshot(c.s) == antes and c.s.almacen.ruta.read_bytes() == raw


def test_rechazo_capturado_no_confirma_cambios_previos_de_la_unidad(contexto):
    c = contexto
    antes, raw = snapshot(c.s), c.s.almacen.ruta.read_bytes()
    with pytest.raises(PermissionError):
        with c.s.almacen._transaccion_sigac(c.a, c.ca) as u:
            u.reservar(c.sa, uuid4(), WORKER_LOCAL, BINDING_LOCAL)
            try:
                u.procesar_aviso(c.eventos[c.cb], BINDING_LOCAL)
            except PermissionError:
                pass
            with pytest.raises(PermissionError):
                u.reservar(c.sa, uuid4(), WORKER_LOCAL, BINDING_LOCAL)
    assert snapshot(c.s) == antes and c.s.almacen.ruta.read_bytes() == raw


def test_escritura_a_reutilizacion_y_acuse_local_legitimos(contexto):
    c = contexto
    b_antes = c.s.detalle(c.cb)
    clave = uuid4()
    r = c.s.observar_validada(c.a, clave=clave, generacion_esperada=2)
    assert r['generacion'] == 3 and r['novedades_nuevas'] == 0
    antes = snapshot(c.s)
    assert c.s.observar_validada(c.a, clave=clave, generacion_esperada=2)['generacion'] == 3
    assert snapshot(c.s) == antes
    with c.s.almacen._transaccion_sigac(c.a, c.ca) as u:
        u.procesar_aviso(c.eventos[c.ca], BINDING_LOCAL)
    assert c.s.detalle(c.cb) == b_antes
    # El acuse interno no elimina una observación de la consulta histórica.
    assert {n['caso'] for n in c.s.observaciones()['observaciones']} == {c.ca, c.cb}
