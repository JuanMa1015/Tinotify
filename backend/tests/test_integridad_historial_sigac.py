"""Integridad de extracción y novedades, exclusivamente con HTML sintético."""

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import json
import socket
import sqlite3
from urllib.parse import parse_qs

import httpx
import pytest

from tinotify.domain.actuaciones import VERSION_HUELLA
from tinotify.integrations.sigac.sigac_client import BASE_URL, SigacClient, SigacClientError
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.parsers.parser import ErrorParseoHistorial, parse_actuaciones
from tinotify.services.reconciliacion import reconciliar
import tinotify.services.ensayo_sigac as ensayo
from tinotify.services.monitor_local import Motivo, monitorear


SEP = '<tr><td colspan="2"><hr></td></tr>'


def bloque(texto='CONTENIDO_FICTICIO', *, fecha='2020-01-01 10:00:00', extra=''):
    return (SEP + '<tr><td>TITULO_FICTICIO</td><td>ASESOR--&gt;ESTUDIANTE</td></tr>'
            f'<tr><td>{fecha}</td><td>RESPONSABLE_FICTICIO</td></tr>'
            f'<tr><td>Actuación :</td><td>{texto}</td></tr>' + extra)


def pagina(*bloques):
    return '<html><body><form id="form1"><table>' + ''.join(bloques) + '</table></form></body></html>'


def historial_ambiguo(*, invertido=False):
    tablas = ['<table>' + bloque(extra='<tr><td>Campo</td><td><textarea></textarea></td></tr>') + '</table>',
              '<table>' + bloque('OTRO_CONTENIDO_FICTICIO') + '</table>']
    if invertido:
        tablas.reverse()
    return '<html><body><form id="form1">' + ''.join(tablas) + '</form></body></html>'


def historial_prefijo_ambiguo():
    prefijo = ('<tr><td>2020-01-01 10:00:00</td><td>RESPONSABLE_FICTICIO</td><td>CELDA_EXTRA_FICTICIA</td></tr>'
               '<tr><td>Actuación:</td><td>CONTENIDO_PREVIO_FICTICIO<input></td></tr>')
    return pagina(prefijo, bloque('OTRA_ACTUACION_FICTICIA'))


@pytest.fixture(autouse=True)
def sin_red(monkeypatch, tmp_path):
    def prohibido(*args, **kwargs):
        pytest.fail('La prueba solo admite HTTP simulado')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket, 'getaddrinfo', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)
    monkeypatch.setattr(sqlite3, 'connect', prohibido)
    monkeypatch.chdir(tmp_path)
    yield
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('invertido', [False, True], ids=['ambigua_primero', 'ambigua_despues'])
def test_dos_tablas_historicas_con_controles_no_devuelven_extraccion_parcial(invertido):
    # Antes de corregir: devuelve una actuación y descarta la otra tabla como
    # formulario. La excepción exigida evita considerar ese subconjunto válido.
    conteos = {}
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(historial_ambiguo(invertido=invertido), 'CASO_FICTICIO', estadisticas=conteos)
    assert error.value.codigo is CodigoHistorial.BLOQUE_CON_CONTROLES
    assert conteos['tablas_formulario_excluidas'] == 0
    assert not hasattr(error.value, 'actuaciones')


def test_prefijo_historico_malformado_con_controles_no_se_descarta():
    # Regresión: antes se devolvía solo el bloque posterior al separador.
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(historial_prefijo_ambiguo(), 'CASO_FICTICIO')
    assert error.value.codigo is CodigoHistorial.ANTES_DEL_SEPARADOR
    assert not hasattr(error.value, 'actuaciones')


@pytest.mark.parametrize('fecha', ['2020-01-01', 'FECHA_ROTA_FICTICIA'])
def test_prefijo_con_contenido_estatico_y_controles_rechaza(fecha):
    prefijo = (f'<tr><td>{fecha}</td><td>RESPONSABLE_FICTICIO</td></tr>'
               '<tr><td>Actuación:</td><td>CONTENIDO_PREVIO_FICTICIO<textarea></textarea></td></tr>')
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(pagina(prefijo, bloque()), 'CASO_FICTICIO')
    assert error.value.codigo is CodigoHistorial.ANTES_DEL_SEPARADOR


def test_prefijo_puramente_interactivo_sigue_admitido():
    prefijo = ('<tr><td>Actuación:</td><td><textarea>2020-01-01 BORRADOR_FICTICIO</textarea></td></tr>'
               '<tr><td>Fecha</td><td><input value="2020-01-01"></td></tr>')
    esperado = parse_actuaciones(pagina(bloque()), 'CASO_FICTICIO')
    obtenido = parse_actuaciones(pagina(prefijo, bloque()), 'CASO_FICTICIO')
    assert obtenido == esperado


@pytest.mark.parametrize('fecha', ['2020-01-01 10:00:00', '2020-01-01', 'FECHA_ROTA_FICTICIA'])
def test_cabecera_o_contenido_historico_impiden_exclusion(fecha):
    html = pagina(bloque(fecha=fecha, extra='<tr><td>Campo</td><td><input></td></tr>'))
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(html, 'CASO_FICTICIO')
    assert error.value.codigo is CodigoHistorial.BLOQUE_CON_CONTROLES


def test_formulario_inequivoco_sigue_excluido_sin_leer_valores():
    formulario = ('<table>' + SEP + '<tr><td>Actuación:</td><td><textarea>2020-01-01 BORRADOR_FICTICIO</textarea></td></tr>'
                  '<tr><td><select><option>2020-01-01</option></select></td><td><input value="2020-01-01"></td></tr></table>')
    html = '<html><body><form>' + formulario + '<table>' + bloque() + '</table></form></body></html>'
    conteos = {}
    resultado = parse_actuaciones(html, 'CASO_FICTICIO', estadisticas=conteos)
    assert len(resultado) == 1 and conteos['tablas_formulario_excluidas'] == 1


def test_ambito_verificado_excluye_tabla_ambigua_externa():
    html = historial_ambiguo().replace('<table>' + bloque('OTRO_CONTENIDO_FICTICIO'),
                                     '<table id="historial_ficticio">' + bloque('OTRO_CONTENIDO_FICTICIO'))
    with pytest.raises(ErrorParseoHistorial):
        parse_actuaciones(html, 'CASO_FICTICIO')
    assert len(parse_actuaciones(html, 'CASO_FICTICIO', contenedor_id='historial_ficticio')) == 1


ENLACE = ('<tr><td>ANEXO_FICTICIO</td><td><a href="general.descargarAnexo.con?codigo=CODIGO_FICTICIO">'
          'archivo_ficticio.txt</a></td></tr>')
SIN_ENLACE = '<tr><td>DESCRIPCION_SIN_ENLACE_FICTICIA</td><td></td></tr>'
CON_ENLACE = ('<tr><td>DESCRIPCION_SIN_ENLACE_FICTICIA</td><td>'
              '<a href="general.descargarAnexo.con?codigo=OTRO_FICTICIO">otro_ficticio.txt</a></td></tr>')


def anexos(sin_enlace=True):
    return ('<tr><td>Anexos:</td><td><table id="tablaAnexos">' + ENLACE
            + (SIN_ENLACE if sin_enlace else CON_ENLACE) + '</table></td></tr>')


def region(borrador='BORRADOR_FICTICIO'):
    return ('<tr><td colspan="2"><div id="tabs"><div id="tabs-1"><textarea>' + borrador
            + '</textarea><button>Guardar</button></div></div></td></tr>')


USUARIO, CLAVE, COOKIE = 'USUARIO_FICTICIO_INTEGRIDAD', 'CLAVE_FICTICIA_INTEGRIDAD', 'COOKIE_FICTICIA_INTEGRIDAD'
FORMULARIO = ('<html><body><form action="sesion.validar.ses" method="post">'
              '<select name="cboTipo"><option value="2">FICTICIO</option></select>'
              '<input name="txtUsuario"><input name="txtCaso" value=""><input type="password" name="txtClave">'
              '<input name="cmdIngresar" value="INGRESO_FICTICIO"></form></body></html>')
SELECTOR = ('<html><body><form action="sesion.cambiar.ses" method="post">'
            '<input name="chkTipoUsuario" value="ESTUDIANTE"><input name="cmdAceptar" value="Aceptar">'
            '</form></body></html>')
LISTADO = ('<html><body><table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr>'
           '<tr class="fila_enlace" onclick="abrir(101)"><td>101</td><td>CLIENTE_FICTICIO</td><td>FICTICIO</td></tr>'
           '</table></body></html>')


@contextmanager
def cliente_sintetico(historiales, *, envolver_detalle=True):
    respuestas = iter(historiales)
    llamadas = []
    def servidor(peticion):
        ruta = peticion.url.path.removeprefix('/sigac/')
        llamadas.append(ruta)
        if ruta == 'index.jsp':
            contenido = FORMULARIO
        elif ruta == 'sesion.validar.ses':
            assert peticion.method == 'POST'
            assert parse_qs(peticion.content.decode(), keep_blank_values=True) == {
                'cboTipo': ['2'], 'txtUsuario': [USUARIO], 'txtClave': [CLAVE],
                'txtCaso': [''], 'cmdIngresar': ['INGRESO_FICTICIO']}
            return httpx.Response(302, headers={'location': 'general.principal.con',
                'set-cookie': f'JSESSIONID={COOKIE}; Path=/sigac/; Secure; HttpOnly'})
        elif ruta == 'general.formCambiarTipoUsuario.con':
            contenido = SELECTOR
        elif ruta == 'sesion.cambiar.ses':
            assert peticion.content == b'chkTipoUsuario=ESTUDIANTE&cmdAceptar=Aceptar'
            return httpx.Response(302, headers={'location': 'general.principal.con'})
        elif ruta == 'general.principal.con':
            contenido = '<html><body>PRINCIPAL_FICTICIA</body></html>'
        elif ruta == 'casos.seleccionarCasos.con':
            assert peticion.method == 'GET' and peticion.url.query == b'motivo=ACTUAR_ESTUDIANTE'
            contenido = LISTADO
        elif ruta == 'casos.formCaso.con':
            assert peticion.method == 'POST' and peticion.content == b'hidCaso=101&hidMotivo=ACTUAR_ESTUDIANTE'
            from backend.tests.helpers.sigac_detalle import detalle
            # Solo el servidor simulado adapta la envoltura antigua a la del
            # endpoint confirmado; los fixtures del parser genérico no cambian.
            contenido = next(respuestas)
            if envolver_detalle:
                contenido = contenido.replace('<form id="form1">', '', 1).replace('</form>', '', 1)
                contenido = detalle(contenido)
        else:
            pytest.fail('Solicitud no incluida en el contrato sintético')
        return httpx.Response(200, text=contenido, headers={'content-type': 'text/html; charset=utf-8'})
    with httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(servidor)) as http:
        with SigacClient(http) as cliente:
            yield cliente, llamadas
        assert not http.cookies


A, B, C = bloque('A_FICTICIA'), bloque('B_FICTICIA'), bloque('C_FICTICIA')
CASOS = [
    ('estable', [pagina(A), pagina(A)], [[], []]),
    ('una_anadida', [pagina(A), pagina(A, B)], [[], ['primera_observacion']]),
    ('varias_anadidas', [pagina(A), pagina(A, B, C)], [[], ['primera_observacion'] * 2]),
    ('duplicados_estables', [pagina(A, A), pagina(A, A)], [[], []]),
    ('multiplicidad', [pagina(A, A), pagina(A, A, A)], [[], ['primera_observacion']]),
    ('reordenacion', [pagina(A, B), pagina(B, A)], [[], []]),
    ('edicion_sin_id', [pagina(A), pagina(B)], [[], ['cambio_ambiguo']]),
    ('historial_parcial', [pagina(A, B), pagina(A)], [[], []]),
    ('parcial_con_adicion', [pagina(A, B), pagina(A, C)], [[], ['cambio_ambiguo']]),
    ('sin_enlace_estable', [pagina(bloque(extra=anexos())), pagina(bloque(extra=anexos()))], [[], []]),
    ('enlace_intermitente', [pagina(bloque(extra=anexos())), pagina(bloque(extra=anexos(False))),
                             pagina(bloque(extra=anexos()))], [[], ['cambio_ambiguo'], []]),
    ('region_anadida', [pagina(A), pagina(A, SEP, region())], [[], []]),
    ('region_modificada', [pagina(A, SEP, region()), pagina(A, SEP, region('OTRO_BORRADOR_FICTICIO'))], [[], []]),
    ('novedad_repetida', [pagina(A), pagina(A, B), pagina(A, B)], [[], ['primera_observacion'], []]),
    ('reaparicion', [pagina(A, B), pagina(A), pagina(A, B)], [[], [], []]),
    ('reaparicion_duplicados', [pagina(A, A), pagina(A), pagina(A, A)], [[], [], []]),
    ('actuacion_antigua_tardia', [pagina(A), pagina(A, bloque('ANTIGUA_FICTICIA', fecha='2010-01-01 10:00:00'))],
     [[], ['primera_observacion']]),
]


@pytest.mark.parametrize('nombre,historiales,eventos_esperados', CASOS, ids=[c[0] for c in CASOS])
def test_html_cliente_ensayo_y_reconciliacion(nombre, historiales, eventos_esperados, monkeypatch):
    eventos, estados = [], []
    def observar_motor(estado, actuaciones, **kwargs):
        siguiente, resultado = reconciliar(estado, actuaciones, **kwargs)
        eventos.append([e.tipo.value for e in resultado.eventos])
        estados.append(deepcopy(siguiente))
        return siguiente, resultado
    monkeypatch.setattr(ensayo, 'reconciliar', observar_motor)
    with cliente_sintetico(historiales) as (cliente, llamadas):
        resumen = ensayo.ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo='2', total_casos=1,
                                         repeticiones=len(historiales), diagnostico=True)
        assert len(llamadas) == 5 + 2 * len(historiales)
    assert eventos == eventos_esperados
    assert resumen['eventos_baseline'] == 0
    assert resumen['eventos_posteriores'] == sum(map(len, eventos_esperados[1:]))
    assert resumen['completitud'] == 'completitud_no_verificada' and resumen['persistencia'] == 'ninguna'
    contadores = [Counter(a.huella_version for a in parse_actuaciones(h, '101')) for h in historiales]
    assert [c['sin_cambios'] for c in resumen['comparaciones']] == [c == contadores[0] for c in contadores[1:]]
    if nombre in ('historial_parcial', 'reaparicion'):
        assert len(estados[1]['records']) == 2
    if nombre == 'sin_enlace_estable':
        assert resumen['anexos_sin_enlace_por_consulta'] == [1, 1]
    if nombre == 'novedad_repetida':
        assert estados[1] == estados[2]
        # El resumen compara contra la base; el motor no reemite el evento.
        assert [c['ocurrencias_no_presentes_en_base'] for c in resumen['comparaciones']] == [1, 1]
    texto = json.dumps(resumen)
    assert all(v not in texto for v in (USUARIO, CLAVE, COOKIE, 'A_FICTICIA', 'RESPONSABLE_FICTICIO', '<html>'))


def test_709_sinteticas_con_region_y_anexo_sin_enlace():
    html = pagina(bloque('FICTICIA_0', extra=anexos()), *(bloque(f'FICTICIA_{i}') for i in range(1, 709)), SEP, region())
    with cliente_sintetico([html, html]) as (cliente, llamadas):
        resumen = ensayo.ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo='2', total_casos=1)
    assert resumen['actuaciones_por_consulta'] == [709, 709]
    assert resumen['regiones_interactivas_excluidas_por_consulta'] == [1, 1]
    assert resumen['filas_interactivas_excluidas_por_consulta'] == [1, 1]
    assert resumen['anexos_sin_enlace_por_consulta'] == [1, 1]
    assert resumen['eventos_posteriores'] == 0 and resumen['resultado'] == 'estable'
    assert len(llamadas) == 9 and VERSION_HUELLA == 1


@pytest.mark.parametrize('primera_valida', [False, True], ids=['sin_baseline', 'baseline_ya_establecida'])
@pytest.mark.parametrize('documento,codigo', [
    (historial_ambiguo, CodigoHistorial.BLOQUE_CON_CONTROLES),
    (historial_prefijo_ambiguo, CodigoHistorial.ANTES_DEL_SEPARADOR),
], ids=['tabla', 'prefijo'])
def test_ensayo_ambiguo_no_invoca_motor_ni_adelanta_baseline(primera_valida, documento, codigo, monkeypatch):
    llamadas_motor = []
    def motor(estado, actuaciones, **kwargs):
        siguiente, resultado = reconciliar(estado, actuaciones, **kwargs)
        llamadas_motor.append((deepcopy(siguiente), resultado))
        return siguiente, resultado
    monkeypatch.setattr(ensayo, 'reconciliar', motor)
    historiales = [pagina(A), documento()] if primera_valida else [documento()]
    with cliente_sintetico(historiales) as (cliente, llamadas):
        with pytest.raises(SigacClientError) as error:
            ensayo.ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo='2', total_casos=1, diagnostico=True)
        assert error.value.codigo is codigo
    assert len(llamadas_motor) == int(primera_valida)
    assert all(not resultado.eventos for _, resultado in llamadas_motor)
    if primera_valida:
        assert len(llamadas_motor[0][0]['records']) == 1


class ServicioMemoria:
    """Doble de la frontera de persistencia: usa el motor real, no escribe."""
    def __init__(self):
        self.estado = None
        self.observaciones = []
        self.eventos = []

    def observar(self, caso, actuaciones, *, titulo):
        self.estado, resultado = reconciliar(self.estado, list(actuaciones), caso=caso)
        self.observaciones.append(deepcopy(self.estado))
        self.eventos.extend(resultado.eventos)
        return {'novedades_nuevas': len(resultado.eventos)}


@pytest.mark.parametrize('primera_valida', [False, True], ids=['sin_baseline', 'baseline_ya_establecida'])
@pytest.mark.parametrize('documento,codigo', [
    (historial_ambiguo, CodigoHistorial.BLOQUE_CON_CONTROLES),
    (historial_prefijo_ambiguo, CodigoHistorial.ANTES_DEL_SEPARADOR),
], ids=['tabla', 'prefijo'])
def test_monitor_no_entrega_lectura_ambigua_a_persistencia(primera_valida, documento, codigo):
    servicio = ServicioMemoria()
    historiales = [pagina(A), documento()] if primera_valida else [documento()]
    tiempo, salida = [0.0], []
    def esperar(segundos):
        tiempo[0] += segundos
    with cliente_sintetico(historiales) as (cliente, llamadas):
        resultado = monitorear(cliente,
            lambda: cliente.autenticar(USUARIO, CLAVE, tipo='2', total_casos_esperado=1),
            total_casos=1, indice_caso=1, servicio=servicio, intervalo_s=600,
            max_ciclos=len(historiales), reloj=lambda: tiempo[0], espera=esperar, emitir=salida.append)
    assert resultado.motivo is Motivo.MAX_CICLOS
    assert resultado.ciclos_correctos == int(primera_valida) and resultado.ciclos_fallidos == 1
    assert len(servicio.observaciones) == int(primera_valida) and servicio.eventos == []
    assert sum(e['evento'] == 'ciclo' for e in salida) == int(primera_valida)
    fallos = [e for e in salida if e['evento'] == 'fallo']
    assert len(fallos) == 1 and fallos[0]['tipo'] == 'extraccion'
    assert fallos[0]['codigo'] == codigo.value
    if primera_valida:
        assert servicio.estado == servicio.observaciones[0]
    else:
        assert servicio.estado is None


def test_region_delimitada_conserva_unica_actuacion_con_controles():
    contenido = bloque('A_FICTICIA', extra=anexos())
    limpia = parse_actuaciones(pagina(contenido), 'CASO_FICTICIO')
    conteos = {}
    extraidas = parse_actuaciones(pagina(contenido, region()), 'CASO_FICTICIO', estadisticas=conteos)
    assert extraidas == limpia and conteos['regiones_interactivas_excluidas'] == 1
    assert [a.huella_version for a in extraidas] == [a.huella_version for a in limpia]


def test_subconjunto_estable_no_demuestra_completitud():
    completo_conocido_solo_por_la_prueba = pagina(A, B, C)
    recibido = pagina(A, B)
    assert len(parse_actuaciones(completo_conocido_solo_por_la_prueba, 'CASO_FICTICIO')) == 3
    with cliente_sintetico([recibido, recibido]) as (cliente, _):
        resumen = ensayo.ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo='2', total_casos=1)
    assert resumen['resultado'] == 'estable' and resumen['actuaciones_por_consulta'] == [2, 2]
    assert resumen['completitud'] == 'completitud_no_verificada'
    assert resumen['eventos_baseline'] == resumen['eventos_posteriores'] == 0
