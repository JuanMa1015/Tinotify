"""Formato local v2: archivos temporales, cero SIGAC y cero servicios remotos."""

from dataclasses import replace
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from uuid import UUID, uuid4

import pytest

from tinotify.demo.novedades import CASO_OBSERVADO, ServicioNovedadesLocal, html_historial_sintetico
from tinotify.parsers.parser import parse_actuaciones
from tinotify.persistence.sqlite_local import (
    AlmacenLocalNoDisponible, AlmacenSqliteLocal, ConflictoPersistenciaLocal,
    ResultadoCommitIncierto, UnidadSqliteLocal, CREDENCIAL_LOCAL,
    BINDING_LOCAL,
)
from tinotify.services.observacion_local import ObservacionRechazada, contenido_logico
from tinotify.domain.actuaciones import resumir


WORKER = Path(__file__).parent / 'helpers' / 'sqlite_v2_worker.py'


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('Estas pruebas nunca abren red')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket, 'getaddrinfo', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / 'sintetico.sqlite3'


def servicio(ruta, perfil='sintetico'):
    return ServicioNovedadesLocal(AlmacenSqliteLocal(ruta, perfil=perfil))


def lote(n=2):
    return parse_actuaciones(html_historial_sintetico(n), CASO_OBSERVADO)


def observar(s, n, gen, clave=None):
    return s.observar(CASO_OBSERVADO, lote(n), clave=clave or uuid4(), generacion_esperada=gen)


def snapshot(s):
    with s.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
        return {tabla: [tuple(f) for f in unidad._c.execute('SELECT * FROM ' + tabla + ' ORDER BY rowid')]
                for tabla in ('meta', 'seguimientos', 'expedientes', 'actuaciones', 'sincronizaciones', 'eventos',
                              'vista_casos', 'vista_actuaciones')}


def proceso(ruta, n, gen, clave, modo='normal', *extras):
    return subprocess.run([sys.executable, '-B', str(WORKER), str(ruta), str(n), str(gen), str(clave), modo,
                           *map(str, extras)], capture_output=True, text=True, timeout=30)


def test_tres_procesos_conservan_identidades_recibos_y_evento(ruta):
    claves = [uuid4() for _ in range(3)]
    salidas = []
    for n, gen, clave in zip((2, 3, 3), (0, 1, 2), claves):
        r = proceso(ruta, n, gen, clave)
        assert r.returncode == 0, r.stderr
        salidas.append(json.loads(r.stdout))
    assert [s['resultado']['novedades_nuevas'] for s in salidas] == [0, 1, 0]
    assert set(salidas[0]['identidades']) < set(salidas[1]['identidades'])
    assert salidas[1]['identidades'] == salidas[2]['identidades']
    assert set(map(tuple, salidas[0]['recibos'])) < set(map(tuple, salidas[1]['recibos']))
    assert len(servicio(ruta).novedades()) == 1


def test_idempotencia_recupera_recibo_sin_reescribir_vista(ruta):
    s, clave = servicio(ruta), uuid4()
    primero = observar(s, 2, 0, clave)
    antes = snapshot(s)
    repetido = observar(s, 2, 0, clave)
    assert primero == repetido and snapshot(s) == antes
    recibo = servicio(ruta).consultar_recibo(CASO_OBSERVADO, lote(), clave=clave, generacion_esperada=0)
    assert recibo.repetido and recibo.generacion == 1
    with pytest.raises(ConflictoPersistenciaLocal):
        observar(s, 3, 0, clave)
    assert snapshot(s) == antes


def test_recibo_antiguo_no_retrocede_una_vista_nueva(ruta):
    s, clave = servicio(ruta), uuid4()
    observar(s, 2, 0, clave)
    observar(s, 3, 1)
    antes = snapshot(s)
    assert observar(s, 2, 0, clave)['generacion'] == 1
    assert snapshot(s) == antes and s.generacion(CASO_OBSERVADO) == 2


def test_clave_global_no_puede_reutilizarse_en_otro_caso(ruta):
    s, clave = servicio(ruta), uuid4()
    observar(s, 2, 0, clave)
    antes = snapshot(s)
    otro = str(uuid4())
    with pytest.raises(ConflictoPersistenciaLocal):
        s.observar(otro, lote(), clave=clave, generacion_esperada=0)
    with pytest.raises(ConflictoPersistenciaLocal):
        s.consultar_recibo(otro, lote(), clave=clave, generacion_esperada=0)
    assert snapshot(s) == antes


def test_digest_canonico_multiplicidades_y_orden_semantico(ruta):
    s = servicio(ruta)
    a, b = lote()
    def digest(observaciones):
        return resumir(contenido_logico('demo-local', CASO_OBSERVADO, 'sintetico', s.observador.politica,
                                       observaciones, 'FICTICIO', 0))
    assert digest([a,b]) == digest([b,a])
    assert digest([a,a]) != digest([a])
    assert digest([a,b]) != digest([replace(a, descripcion='CAMBIO_FICTICIO'),b])
    assert digest([a]) != digest([replace(a, descripcion='fila1\nfila2')])
    assert digest([replace(a, descripcion='fila1\nfila2')]) != digest([replace(a, descripcion='fila2\nfila1')])
    assert digest([replace(a, descripcion='revisio\u0301n')]) == digest([replace(a, descripcion='revisión')])


def test_misma_operacion_reordenada_no_cambia_recibo_ni_proyeccion(ruta):
    s, clave = servicio(ruta), uuid4()
    a, b = lote()
    s.observar(CASO_OBSERVADO, [a,b], clave=clave, generacion_esperada=0)
    antes = snapshot(s)
    assert s.observar(CASO_OBSERVADO, [b,a], clave=clave, generacion_esperada=0)['novedades_nuevas'] == 0
    assert snapshot(s) == antes


def test_vista_con_identidad_o_version_incorrecta_no_confirma(ruta):
    s = servicio(ruta)
    observar(s, 2, 0)
    antes = snapshot(s)
    with pytest.raises(ValueError):
        with s.almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
            filas = unidad.vista(CASO_OBSERVADO)['actuaciones']
            unidad.guardar_vista(CASO_OBSERVADO, 'FICTICIO',
                [(a['local_id'], 'f' * 64, {}) for a in filas])
    assert snapshot(s) == antes


@pytest.mark.parametrize('n', [2, 3])
def test_conflicto_generacion_no_modifica_nada(ruta, n):
    s = servicio(ruta)
    observar(s, 2, 0)
    antes = snapshot(s)
    with pytest.raises(ConflictoPersistenciaLocal):
        observar(s, n, 0)
    assert snapshot(s) == antes


def test_dos_escritores_procesos_un_conflicto_sin_fusion(ruta, tmp_path):
    observar(servicio(ruta), 2, 0)
    salida = tmp_path / 'salida'
    procesos = []
    for i, n in enumerate((3,4)):
        listo = tmp_path / f'listo{i}'
        procesos.append(subprocess.Popen([sys.executable, '-B', str(WORKER), str(ruta), str(n), '1',
                         str(uuid4()), 'barrera', str(listo), str(salida)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    try:
        limite = time.monotonic() + 15
        while not all((tmp_path / f'listo{i}').exists() for i in range(2)):
            assert time.monotonic() < limite
            time.sleep(0.01)
        salida.write_text('adelante', encoding='utf-8')
        resultados = []
        for p in procesos:
            out, err = p.communicate(timeout=20)
            assert p.returncode == 0, err
            resultados.append(json.loads(out))
        assert sum('resultado' in r for r in resultados) == 1
        assert sum('conflicto_generacion_o_idempotencia' in r for r in resultados) == 1
        s = servicio(ruta)
        ganador = next(r['resultado'] for r in resultados if 'resultado' in r)
        assert s.generacion(CASO_OBSERVADO) == 2
        assert s.detalle(CASO_OBSERVADO)['total_actuaciones'] == ganador['actuaciones']
    finally:
        for p in procesos:
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=10)


@pytest.mark.parametrize('modo,codigo,confirmado', [('antes',71,False), ('durante',72,False), ('despues',73,True)])
def test_interrupciones_de_proceso_y_recibo_desde_nueva_conexion(ruta, modo, codigo, confirmado):
    observar(servicio(ruta), 2, 0)
    clave = uuid4()
    r = proceso(ruta, 3, 1, clave, modo)
    assert r.returncode == codigo, r.stderr
    consulta = proceso(ruta, 3, 1, clave, 'recibo')
    assert consulta.returncode == 0, consulta.stderr
    assert json.loads(consulta.stdout)['confirmado'] is confirmado
    s = servicio(ruta)
    assert s.generacion(CASO_OBSERVADO) == (2 if confirmado else 1)
    assert len(s.novedades()) == int(confirmado)
    assert s.detalle(CASO_OBSERVADO)['total_actuaciones'] == (3 if confirmado else 2)


@pytest.mark.parametrize('punto', ['antes_commit', 'durante_commit', 'vista'])
def test_fallos_inyectados_revierte_estado_recibo_eventos_y_vista(ruta, monkeypatch, punto):
    s = servicio(ruta)
    observar(s, 2, 0)
    antes = snapshot(s)
    if punto == 'vista':
        original = UnidadSqliteLocal.guardar_vista
        def fallar(self, *args):
            original(self, *args)
            raise RuntimeError('fallo ficticio de vista')
        monkeypatch.setattr(UnidadSqliteLocal, 'guardar_vista', fallar)
    else:
        def fallar(c):
            if punto == 'durante_commit':
                # Violación diferible: SQLite falla al ejecutar COMMIT.
                c.execute('UPDATE vista_casos SET generacion=999')
                c.execute('COMMIT')
            raise sqlite3.OperationalError('fallo ficticio antes de commit')
        monkeypatch.setattr(s.almacen, '_commit', fallar)
    with pytest.raises((AlmacenLocalNoDisponible, RuntimeError)):
        observar(s, 3, 1)
    assert snapshot(servicio(ruta)) == antes


def test_commit_confirmado_con_ack_perdido_consulta_recibo_sin_reintento(ruta, monkeypatch):
    s = servicio(ruta)
    observar(s, 2, 0)
    llamadas = []
    original = s.almacen._commit
    def commit(c):
        original(c)
        llamadas.append(1)
        if len(llamadas) == 1:
            raise sqlite3.OperationalError('ack ficticio perdido')
    monkeypatch.setattr(s.almacen, '_commit', commit)
    resultado = observar(s, 3, 1)
    assert resultado['generacion'] == 2 and resultado['novedades_nuevas'] == 0
    assert len(llamadas) == 2  # escritura + consulta del recibo en otra conexión
    assert len(servicio(ruta).novedades()) == 1


def test_duplicados_marcan_solo_ocurrencia_nueva(ruta):
    s = servicio(ruta)
    a = lote(1)[0]
    s.observar(CASO_OBSERVADO, [a,a], clave=uuid4(), generacion_esperada=0)
    s.observar(CASO_OBSERVADO, [a,a,a], clave=uuid4(), generacion_esperada=1)
    detalle = s.detalle(CASO_OBSERVADO)
    assert sum(a['nueva'] for a in detalle['actuaciones']) == 1
    assert len({a['local_id'] for a in detalle['actuaciones']}) == 3
    assert len(s.novedades()) == 1


@pytest.mark.parametrize('modificar', [False, True])
def test_lectura_parcial_o_ambigua_no_adelanta_base(ruta, modificar):
    s = servicio(ruta)
    observar(s, 2, 0)
    antes = snapshot(s)
    observaciones = lote(1)
    if modificar:
        observaciones = [replace(a, descripcion='CAMBIO_AMBIGUO_FICTICIO') for a in lote(2)]
    with pytest.raises(ObservacionRechazada):
        s.observar(CASO_OBSERVADO, observaciones, clave=uuid4(), generacion_esperada=1)
    assert snapshot(s) == antes


@pytest.mark.parametrize('previa', [False, True])
def test_html_ambiguo_no_crea_recibo_ni_base(ruta, previa):
    s = servicio(ruta)
    if previa:
        observar(s, 2, 0)
    antes = snapshot(s)
    prefijo = ('<tr><td>2020-01-01 10:00:00</td><td>FICTICIO</td><td>EXTRA</td></tr>'
               '<tr><td>Actuación:</td><td>TEXTO_FICTICIO<input></td></tr>')
    html = html_historial_sintetico(2).replace('<table>', '<table>' + prefijo, 1)
    with pytest.raises(ObservacionRechazada):
        s.observar_html(CASO_OBSERVADO, html, clave=uuid4(), generacion_esperada=int(previa))
    assert snapshot(s) == antes


def test_conflicto_inicial_revierte_incluso_creacion_de_seguimiento(ruta):
    s = servicio(ruta)
    antes = snapshot(s)
    with pytest.raises(ConflictoPersistenciaLocal):
        observar(s, 2, 7)
    assert snapshot(s) == antes


@pytest.mark.parametrize('modo', ['v1','vacia','corrupta','incompatible','perfil','esquema_ajeno'])
def test_rechazo_no_modifica_archivos_preexistentes(ruta, modo, monkeypatch):
    if modo == 'vacia':
        ruta.touch()
    elif modo == 'corrupta':
        ruta.write_bytes(b'NO ES SQLITE FICTICIO')
    elif modo == 'v1':
        with sqlite3.connect(ruta) as c:
            c.executescript("CREATE TABLE meta(clave TEXT PRIMARY KEY,valor TEXT NOT NULL);"
                            "INSERT INTO meta VALUES ('esquema','1'); CREATE TABLE legado(dato TEXT);")
    else:
        servicio(ruta)
        with sqlite3.connect(ruta) as c:
            if modo == 'incompatible': c.execute("UPDATE meta SET valor='99' WHERE clave='esquema'")
            if modo == 'esquema_ajeno': c.execute('CREATE TABLE objeto_ajeno(id INTEGER)')
    antes = ruta.read_bytes()
    existentes = {p.name:p.read_bytes() for p in ruta.parent.iterdir() if p.is_file()}
    def prohibido(*a,**k): pytest.fail('No debe abrirse el original para escritura')
    monkeypatch.setattr(AlmacenSqliteLocal, '_abrir', prohibido)
    with pytest.raises(AlmacenLocalNoDisponible):
        AlmacenSqliteLocal(ruta, perfil='real' if modo == 'perfil' else 'sintetico')
    assert ruta.read_bytes() == antes
    assert {p.name:p.read_bytes() for p in ruta.parent.iterdir() if p.is_file()} == existentes


def test_v1_con_wal_y_shm_permanece_byte_a_byte_intacto(ruta):
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute('PRAGMA journal_mode=WAL')
        conexion.executescript("CREATE TABLE meta(clave TEXT,valor TEXT); INSERT INTO meta VALUES ('esquema','1');")
        conexion.commit()
        antes = {p.name:p.read_bytes() for p in ruta.parent.iterdir() if p.is_file()}
        with pytest.raises(AlmacenLocalNoDisponible):
            AlmacenSqliteLocal(ruta)
        assert {p.name:p.read_bytes() for p in ruta.parent.iterdir() if p.is_file()} == antes
    finally:
        conexion.close()


def test_perfil_real_minimo_no_almacena_textos_ni_anexos(ruta):
    from backend.tests.test_integridad_historial_sigac import pagina, bloque, cliente_sintetico, USUARIO, CLAVE
    from tinotify.integrations.sigac.lectura_validada import leer_historial_validado
    anexo = ('<tr><td>Anexos:</td><td><table id="tablaAnexos"><tr><td>ANEXO_PRIVADO_NO_GUARDAR</td>'
             '<td><a href="general.descargarAnexo.con?codigo=REFERENCIA_PRIVADA_NO_GUARDAR">'
             'archivo_privado_no_guardar</a></td></tr></table></td></tr>')
    contenido = pagina(bloque('DESCRIPCION_JUDICIAL_FICTICIA_NO_GUARDAR', extra=anexo))
    contenido = contenido.replace('RESPONSABLE_FICTICIO', 'NOMBRE_FICTICIO_NO_GUARDAR').replace(
        'TITULO_FICTICIO', 'ETAPA_FICTICIA_NO_GUARDAR TITULO_PRIVADO_NO_GUARDAR')
    s = ServicioNovedadesLocal(AlmacenSqliteLocal(ruta, perfil='real'), instancia='sigac-real')
    with cliente_sintetico([contenido]) as (cliente, _):
        cliente.autenticar(USUARIO, CLAVE, tipo='2', total_casos_esperado=1)
        lectura = leer_historial_validado(cliente, 101)
    resultado = s.observar_validada(lectura, clave=uuid4(), generacion_esperada=0)
    raw = ruta.read_bytes()
    assert all(v.encode() not in raw for v in ('DESCRIPCION_JUDICIAL_FICTICIA_NO_GUARDAR',
        'NOMBRE_FICTICIO_NO_GUARDAR','ETAPA_FICTICIA_NO_GUARDAR','TITULO_PRIVADO_NO_GUARDAR',
        'ANEXO_PRIVADO_NO_GUARDAR','archivo_privado_no_guardar','REFERENCIA_PRIVADA_NO_GUARDAR'))
    with s.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
        assert unidad._c.execute('SELECT contenido FROM vista_actuaciones').fetchone()[0] == '{}'
    assert s.detalle(resultado['caso'])['titulo'] == 'Expediente local'


def test_formato_sqlite_y_json_son_versiones_independientes(ruta):
    s = servicio(ruta)
    observar(s, 2, 0)
    with s.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
        assert unidad._c.execute("SELECT valor FROM meta WHERE clave='esquema'").fetchone()[0] == '2'
    estado = s.seguimiento.estado(CREDENCIAL_LOCAL, binding=BINDING_LOCAL)
    assert estado['schema_version'] == 2 and estado['state_revision'] == 2 and estado['fingerprint_version'] == 1


def test_reiniciar_cli_no_borra_un_v1(ruta):
    with sqlite3.connect(ruta) as c:
        c.executescript("CREATE TABLE meta(clave TEXT,valor TEXT); INSERT INTO meta VALUES ('esquema','1');")
    antes = ruta.read_bytes()
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'novedades_local.py'
    r = subprocess.run([sys.executable,'-B',str(script),'--db',str(ruta),'reiniciar','--confirmar'],
                       capture_output=True,text=True,timeout=20)
    assert r.returncode == 2 and ruta.read_bytes() == antes


def test_claves_foraneas_y_generaciones_de_vista_consistentes(ruta):
    s = servicio(ruta)
    observar(s, 2, 0)
    observar(s, 3, 1)
    with s.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
        assert unidad._c.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert unidad._c.execute('PRAGMA synchronous').fetchone()[0] == 2
        assert unidad._c.execute('PRAGMA foreign_key_check').fetchall() == []
        assert unidad._c.execute('SELECT COUNT(*) FROM vista_actuaciones v JOIN expedientes e ON e.id=v.expediente_id '
                                'WHERE v.generacion<>e.generacion').fetchone()[0] == 0


def test_vista_averiada_no_es_fuente_para_rechazar_observacion(ruta):
    s = servicio(ruta)
    observar(s, 2, 0)
    # Manipulación ficticia de una proyección, manteniendo sus FK. La base real
    # sigue teniendo dos ocurrencias y debe impedir aceptar el subconjunto.
    with s.almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
        unidad._c.execute('DELETE FROM vista_actuaciones')
    antes = snapshot(s)
    with pytest.raises(ObservacionRechazada):
        observar(s, 1, 1)
    assert snapshot(s) == antes


def test_clave_y_generacion_explicitas_requeridas(ruta):
    s = servicio(ruta)
    with pytest.raises(TypeError):
        s.observar(CASO_OBSERVADO, lote())
    with pytest.raises(ValueError):
        s.observar_html(CASO_OBSERVADO, html_historial_sintetico(2), clave=uuid4())
    assert s.generacion(CASO_OBSERVADO) == 0


def test_identidad_institucional_no_se_inventa_ni_se_consulta(monkeypatch, tmp_path, capsys):
    from tinotify.services.consulta_real_local import consultar_expediente, IdentidadExpedienteNoVerificada
    class NoUsar:
        def __getattr__(self, nombre):
            pytest.fail('No se debe autenticar ni escribir')
    with pytest.raises(IdentidadExpedienteNoVerificada):
        consultar_expediente(NoUsar(), 'FICTICIO', 'FICTICIO', tipo='2', total_casos=1,
                             indice_caso=1, servicio=NoUsar())
    import importlib.util
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'sigac_local.py'
    spec = importlib.util.spec_from_file_location('cli_identidad_cerrada', script)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setattr(modulo.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(modulo, '_servicio', lambda *a: pytest.fail('No se debe abrir SQLite'))
    monkeypatch.setattr(modulo.getpass, 'getpass', lambda *a: pytest.fail('No se deben pedir credenciales'))
    for orden in ('consultar','monitorear'):
        assert modulo.main(['--db', str(tmp_path/'no_crear.sqlite3'), orden, '--autorizar-sigac-real',
                            '--tipo','2','--total-casos','1','--caso-numero','1']) == 4
    assert not (tmp_path/'no_crear.sqlite3').exists()
    salida = capsys.readouterr().out.lower()
    assert 'bloquead' in salida and 'deshabilitado' in salida
