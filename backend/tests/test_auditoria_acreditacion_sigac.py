"""Huecos de auditoría: ninguna modificación de contratos o código funcional."""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import json
import socket
import subprocess
import sys
from uuid import uuid4

import pytest

from backend.tests.test_frontera_persistencia_sigac import leer, servicio
from backend.tests.test_sigac_flujo import cliente_servidor, autenticar
from backend.tests.test_sqlite_local_v2 import snapshot
from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.integrations.sigac.lectura_validada import (
    leer_historial_validado, _resolver_lectura, _referencia_local,
)
from tinotify.persistence.sqlite_local import UnidadSqliteLocal, ConflictoPersistenciaLocal


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('No se permite red real')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)


def test_api_publica_no_admite_caso_alternativo_ni_reutiliza_clave_entre_expedientes(tmp_path):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    with cliente_servidor() as (cliente, _):
        autenticar(cliente)
        a, b = (leer_historial_validado(cliente, n) for n in (101, 202))
    caso_a, caso_b = _referencia_local(a), _referencia_local(b)
    assert caso_a != caso_b
    clave = uuid4()
    assert s.observar_validada(a, clave=clave, generacion_esperada=0)['caso'] == caso_a
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    with pytest.raises(TypeError):
        s.observar_validada(a, caso=caso_b, clave=uuid4(), generacion_esperada=0)
    with pytest.raises(ConflictoPersistenciaLocal):
        s.observar_validada(b, clave=clave, generacion_esperada=0)
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw
    assert s.observar_validada(b, clave=uuid4(), generacion_esperada=0)['caso'] == caso_b
    assert len(s.listar_casos()) == 2


def test_actuaciones_no_son_editables_ni_sustituibles_en_la_entrada_publica(tmp_path):
    s, lectura = servicio(tmp_path/'solo-sintetico.sqlite3'), leer()
    # El resolver es inspección del test; la API pública opaca no expone actos.
    _, actos = _resolver_lectura(lectura)
    antes = snapshot(s)
    with pytest.raises(AttributeError):
        lectura.actuaciones = ()
    with pytest.raises(FrozenInstanceError):
        actos[0].descripcion = 'CONTENIDO_SINTETICO_SUSTITUIDO'
    editadas = [replace(actos[0], descripcion='CONTENIDO_SINTETICO_SUSTITUIDO'), *actos[1:]]
    with pytest.raises(TypeError):
        s.observar_validada(lectura, actuaciones=editadas, clave=uuid4(), generacion_esperada=0)
    with pytest.raises(PermissionError):
        s.observador._observar(_referencia_local(lectura), editadas, lectura=lectura,
            clave=uuid4(), generacion_esperada=0, titulo='Expediente local', contenido_vista=lambda _: {})
    assert snapshot(s) == antes
    s.observar_validada(lectura, clave=uuid4(), generacion_esperada=0)
    assert sorted(f[3] for f in snapshot(s)['actuaciones']) == sorted(a.huella_version for a in actos)


def test_acreditacion_reutilizable_no_equivale_a_operacion_de_un_solo_uso(tmp_path):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    s.observar_validada(leer(2), clave=uuid4(), generacion_esperada=0)
    lectura, clave = leer(3), uuid4()
    primera = s.observar_validada(lectura, clave=clave, generacion_esperada=1)
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    repetida = s.observar_validada(lectura, clave=clave, generacion_esperada=1)
    assert primera['novedades_nuevas'] == 1 and repetida['novedades_nuevas'] == 0
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw
    # Una clave nueva es otra operación explícita: nueva generación/recibo,
    # mismo conjunto conocido, ningún evento lógico nuevo. No hay TTL/consumo.
    nueva = s.observar_validada(lectura, clave=uuid4(), generacion_esperada=2)
    assert nueva['generacion'] == 3 and nueva['novedades_nuevas'] == 0
    assert len(s.observaciones()['observaciones']) == 1 and len(snapshot(s)['sincronizaciones']) == 3


def test_excepcion_con_rollback_no_consume_lectura_y_reenvio_es_explicito(tmp_path, monkeypatch):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    s.observar_validada(leer(2), clave=uuid4(), generacion_esperada=0)
    lectura, clave = leer(3), uuid4()
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    guardar = UnidadSqliteLocal.guardar_vista
    def fallo(*args, **kwargs):
        raise RuntimeError('Fallo sintetico anterior a COMMIT')
    monkeypatch.setattr(UnidadSqliteLocal, 'guardar_vista', fallo)
    with pytest.raises(RuntimeError, match='Fallo sintetico'):
        s.observar_validada(lectura, clave=clave, generacion_esperada=1)
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw
    monkeypatch.setattr(UnidadSqliteLocal, 'guardar_vista', guardar)
    assert s.observar_validada(lectura, clave=clave, generacion_esperada=1)['novedades_nuevas'] == 1
    assert s.observar_validada(lectura, clave=clave, generacion_esperada=1)['novedades_nuevas'] == 0
    assert len(s.observaciones()['observaciones']) == 1


def test_reinicio_real_de_proceso_reacredita_y_recupera_recibo(tmp_path):
    ruta, clave = tmp_path/'solo-sintetico.sqlite3', str(uuid4())
    worker = Path(__file__).parent/'helpers'/'auditoria_acreditacion_worker.py'
    resultados = []
    for modo in ('crear', 'reabrir'):
        r = subprocess.run([sys.executable, '-B', str(worker), str(ruta), modo, clave],
                           capture_output=True, text=True, timeout=40)
        assert r.returncode == 0, r.stderr
        resultados.append(json.loads(r.stdout))
    assert resultados[0]['resultado']['novedades_nuevas'] == 1
    assert resultados[1]['resultado']['novedades_nuevas'] == 0
    for campo in ('eventos', 'recibos', 'identidades'):
        assert resultados[0][campo] == resultados[1][campo]
    assert resultados[1]['eventos'] == 1 and resultados[1]['recibos'] == 2


def test_recibo_real_sin_digest_rechaza_reintentos_repetidos_sin_reparar(tmp_path):
    s, lectura, clave = servicio(tmp_path/'solo-sintetico.sqlite3'), leer(), uuid4()
    caso = s.observar_validada(lectura, clave=clave, generacion_esperada=0)['caso']
    # Fixture histórica: SQL privado explícito, nunca una vía del consumidor.
    with s.almacen._transaccion_sigac(lectura, caso) as u:
        u._c.execute('UPDATE sincronizaciones SET contenido_hash=NULL,digest_version=NULL WHERE clave=?', (str(clave),))
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    for _ in range(3):
        with pytest.raises(ConflictoPersistenciaLocal):
            s.observar_validada(lectura, clave=clave, generacion_esperada=0)
        assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


def test_unidad_interna_rechaza_otro_expediente_con_lectura_valida(tmp_path):
    s, lectura = servicio(tmp_path/'solo-sintetico.sqlite3'), leer()
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    otro = str(uuid4())
    with pytest.raises(PermissionError):
        with s.almacen._transaccion_sigac(lectura, _referencia_local(lectura)) as unidad:
            unidad.seguir(INSTANCIA_REAL, otro, s.almacen._politica.firma(INSTANCIA_REAL))
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw
