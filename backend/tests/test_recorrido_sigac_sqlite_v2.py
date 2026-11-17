"""Recorrido integrado sintético; no acredita habilitación institucional real."""

from pathlib import Path
import json
import socket
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from backend.tests.test_integridad_historial_sigac import (
    bloque, pagina, anexos, cliente_sintetico, USUARIO, CLAVE,
)
from backend.tests.helpers.sigac_detalle import detalle
from backend.tests.test_sqlite_local_v2 import snapshot
from tinotify.demo.novedades import CASO_OBSERVADO, ServicioNovedadesLocal
from tinotify.integrations.sigac.sigac_client import SigacIdentityError
from tinotify.domain.actuaciones import TipoCambio
from tinotify.persistence.sqlite_local import AlmacenSqliteLocal
from tinotify.services.observacion_local import ObservacionRechazada


WORKER = Path(__file__).parent / 'helpers' / 'recorrido_sigac_sqlite_worker.py'


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('Estas pruebas solo admiten HTTP simulado')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)


def comando(ruta, n, gen, clave, modo='normal', *extras):
    return [sys.executable, '-B', str(WORKER), str(ruta), str(n), str(gen), str(clave), modo, *map(str, extras)]


def proceso(*args):
    salida = subprocess.run(comando(*args), capture_output=True, text=True, timeout=45)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout)


def test_a_hasta_f_cinco_procesos_y_recibo_persistente(tmp_path):
    ruta = tmp_path / 'recorrido-sintetico.sqlite3'
    claves = [uuid4() for _ in range(5)]
    lecturas = [proceso(ruta, n, gen, clave) for n, gen, clave in
                zip((3, 3, 4, 4, 4), range(5), claves)]
    assert [r['resultado']['novedades_nuevas'] for r in lecturas] == [0, 0, 1, 0, 0]
    assert [len(r['eventos']) for r in lecturas] == [0, 0, 1, 1, 1]
    assert lecturas[0]['identidades'] == lecturas[1]['identidades']
    assert set(lecturas[0]['identidades']) < set(lecturas[2]['identidades'])
    assert lecturas[2]['identidades'] == lecturas[3]['identidades'] == lecturas[4]['identidades']
    assert lecturas[2]['eventos'] == lecturas[4]['eventos']
    assert all(r['solicitudes'] == 7 for r in lecturas)
    repetida = proceso(ruta, 4, 2, claves[2])
    recibo = proceso(ruta, 4, 2, claves[2], 'recibo')
    assert repetida['generacion'] == recibo['generacion'] == 5
    assert repetida['eventos'] == recibo['eventos'] == lecturas[-1]['eventos']
    assert repetida['recibos'] == recibo['recibos'] == lecturas[-1]['recibos']
    assert repetida['resultado']['novedades_nuevas'] == 0
    assert recibo['resultado'] == {'recibo_encontrado': True, 'repetido': True}
    assert recibo['eventos'][0][2:] == [TipoCambio.PRIMERA_OBSERVACION.value, 'pendiente']


def test_g_commit_incierto_y_reenvio_explicito_en_otro_proceso(tmp_path):
    ruta = tmp_path / 'recorrido-sintetico.sqlite3'
    proceso(ruta, 3, 0, uuid4())
    clave = uuid4()
    incierta = proceso(ruta, 4, 1, clave, 'incierto')
    recibo = proceso(ruta, 4, 1, clave, 'recibo')
    repetida = proceso(ruta, 4, 1, clave)
    assert incierta['generacion'] == recibo['generacion'] == repetida['generacion'] == 2
    assert len(incierta['eventos']) == 1
    assert incierta['eventos'] == recibo['eventos'] == repetida['eventos']
    assert incierta['recibos'] == repetida['recibos']
    assert recibo['resultado']['recibo_encontrado'] is True
    assert repetida['resultado']['novedades_nuevas'] == 0


def lectura(s, contenido, *, gen):
    with cliente_sintetico([contenido]) as (cliente, llamadas):
        cliente.autenticar(USUARIO, CLAVE, tipo='2', total_casos_esperado=1)
        actuaciones = cliente.consultar_historial(101)
        assert len(llamadas) == 7
    # Conversión exclusiva de datos ficticios del harness; no es una vía real.
    return s.observar(CASO_OBSERVADO, list(actuaciones), clave=uuid4(), generacion_esperada=gen)


def test_h_i_j_m_antigua_duplicados_orden_y_anexo_sin_enlace(tmp_path):
    s = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path/'sintetico.sqlite3'))
    a, b, c = (bloque(f'CONTENIDO_SINTETICO_{n}') for n in range(3))
    antigua = bloque('CONTENIDO_SINTETICO_ANTIGUO', fecha='2018-01-01 10:00:00', extra=anexos())
    assert lectura(s, pagina(a, b, c), gen=0)['novedades_nuevas'] == 0
    assert lectura(s, pagina(antigua, a, b, c), gen=1)['novedades_nuevas'] == 1
    aviso = s.novedades()[0]
    assert aviso['tipo'] == TipoCambio.PRIMERA_OBSERVACION.value
    assert 'primera vez' in aviso['mensaje']
    assert '2018' not in aviso['mensaje'] and 'creada' not in aviso['mensaje']
    anexos_extraidos = s.detalle(CASO_OBSERVADO)['actuaciones'][0]['anexos']
    assert len(anexos_extraidos) == 2 and any(a['sin_enlace'] for a in anexos_extraidos)
    assert lectura(s, pagina(a, antigua, b, c), gen=2)['novedades_nuevas'] == 0
    assert lectura(s, pagina(a, antigua, b, c, a), gen=3)['novedades_nuevas'] == 1
    assert len(s.detalle(CASO_OBSERVADO)['actuaciones']) == 5
    assert lectura(s, pagina(a, a, c, antigua, b), gen=4)['novedades_nuevas'] == 0
    assert len(s.novedades()) == 2


@pytest.mark.parametrize('modo', ['parcial', 'otro', 'contradictorio', 'estructura'])
@pytest.mark.parametrize('previa', [False, True])
def test_k_rechazos_y_limite_de_completitud(tmp_path, previa, modo):
    s = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path/'sintetico.sqlite3'))
    base = pagina(bloque('A_SINTETICA'), bloque('B_SINTETICA'), bloque('C_SINTETICA'))
    if previa:
        lectura(s, base, gen=0)
    antes = snapshot(s)
    contenido = pagina(bloque('A_SINTETICA')) if modo == 'parcial' else base
    if modo != 'parcial':
        contenido = detalle('<table>'+bloque('A_SINTETICA')+'</table>',
                            numero='202' if modo == 'otro' else '101',
                            cabecera='202' if modo == 'contradictorio' else None)
        if modo == 'estructura':
            contenido = contenido.replace('2020-01-01 10:00:00', 'FECHA_ILEGIBLE_SINTETICA')
    with cliente_sintetico([contenido], envolver_detalle=modo == 'parcial') as (cliente, llamadas):
        cliente.autenticar(USUARIO, CLAVE, tipo='2', total_casos_esperado=1)
        from tinotify.integrations.sigac.sigac_client import SigacClientError
        if modo == 'parcial' and not previa:
            # Sin base ni total independiente, un subconjunto válido no se detecta.
            actuaciones = cliente.consultar_historial(101)
            assert s.observar(CASO_OBSERVADO, list(actuaciones), clave=uuid4(), generacion_esperada=0)['baseline'] is True
            return
        errores = (SigacIdentityError,) if modo in ('otro', 'contradictorio') else (SigacClientError, ObservacionRechazada)
        with pytest.raises(errores):
            actuaciones = cliente.consultar_historial(101)
            s.observar(CASO_OBSERVADO, list(actuaciones), clave=uuid4(), generacion_esperada=int(previa))
    assert snapshot(s) == antes


def test_l_dos_procesos_misma_generacion_una_transicion(tmp_path):
    ruta = tmp_path / 'recorrido-sintetico.sqlite3'
    proceso(ruta, 3, 0, uuid4())
    salida = tmp_path/'salida'
    listos = [tmp_path/f'listo{i}' for i in range(2)]
    escritores = [subprocess.Popen(comando(ruta, 4+i, 1, uuid4(), 'barrera', listos[i], salida),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(2)]
    try:
        limite = time.monotonic()+20
        while not all(p.exists() for p in listos):
            assert time.monotonic() < limite, 'Barrera agotada'
            time.sleep(0.01)
        salida.write_text('adelante', encoding='utf-8')
        resultados = []
        for escritor in escritores:
            stdout, stderr = escritor.communicate(timeout=30)
            assert escritor.returncode == 0, stderr
            resultados.append(json.loads(stdout))
        assert sum(r['resultado'].get('conflicto', False) for r in resultados) == 1
        assert all(r['generacion'] == 2 for r in resultados)
        assert all(len(r['recibos']) == 2 for r in resultados)
    finally:
        for escritor in escritores:
            if escritor.poll() is None:
                escritor.kill()
            escritor.communicate()


def test_script_actual_invoca_validador_dos_veces_y_no_abre_sqlite(monkeypatch, capsys):
    import logging
    import sqlite3
    import tinotify.integrations.sigac.sigac_client as modulo_cliente
    from backend.tests.test_sigac_flujo import cargar_entrada
    llamadas_validador = []
    original = modulo_cliente.validar_detalle
    def validar(*args, **kwargs):
        llamadas_validador.append(True)
        return original(*args, **kwargs)
    def no_sqlite(*args, **kwargs):
        pytest.fail('El ensayo sin persistencia no debe abrir SQLite')
    monkeypatch.setattr(modulo_cliente, 'validar_detalle', validar)
    monkeypatch.setattr(sqlite3, 'connect', no_sqlite)
    script = cargar_entrada()
    contenido = pagina(bloque('CONTENIDO_SINTETICO'))
    with cliente_sintetico([contenido, contenido]) as (cliente, llamadas):
        monkeypatch.setattr(script, 'SigacClient', lambda: cliente)
        monkeypatch.setattr(script.sys.stdin, 'isatty', lambda: True)
        monkeypatch.setattr('builtins.input', lambda _: 'SIGAC-LECTURA')
        entradas = iter([USUARIO, CLAVE])
        monkeypatch.setattr(script.getpass, 'getpass', lambda _: next(entradas))
        anterior = logging.root.manager.disable
        try:
            assert script.main(['--autorizar-sigac-real', '--tipo', '2', '--total-casos', '1',
                                '--indice-caso', '1', '--consultas', '2', '--diagnostico']) == 0
        finally:
            logging.disable(anterior)
        assert len(llamadas_validador) == 2 and len(llamadas) == 9
    salida = json.loads(capsys.readouterr().out)
    assert salida['persistencia'] == 'ninguna' and salida['eventos_posteriores'] == 0
