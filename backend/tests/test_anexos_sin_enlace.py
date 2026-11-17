"""Anexos con descripción y sin enlace de descarga. Todo el material es sintético y sin red.

`sin_enlace` solo significa que la respuesta no trajo referencia de descarga; no afirma
que el archivo no exista. La fila se admite únicamente con las siete condiciones estrictas.
"""

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest

import tinotify.parsers.parser as modulo
from tinotify.domain.actuaciones import Actuacion, Anexo, TipoCambio
from tinotify.domain.actuaciones import adaptar_observacion
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.parsers.parser import ErrorParseoHistorial, parse_actuaciones
from tinotify.services.ensayo_sigac import ejecutar_ensayo


SEP = '<tr><td colspan="2"><hr></td></tr>'
CABECERA = '<tr><td>TITULO_FICTICIO</td><td>ASESOR--&gt;ESTUDIANTE</td></tr>'
FECHA = '<tr><td>2020-01-01 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
CONTENIDO = '<tr><td>Actuación :</td><td>CONTENIDO_FICTICIO</td></tr>'
BLOQUE = SEP + CABECERA + FECHA + CONTENIDO
ENLACE = '<a href="general.descargarAnexo.con?codigo=CODIGO_FICTICIO">archivo_ficticio.pdf</a>'
CON_ENLACE = '<tr><td>ANEXO_CON_ENLACE_FICTICIO</td><td>' + ENLACE + '</td></tr>'
SIN_ENLACE = '<tr><td>ANEXO_SIN_ENLACE_FICTICIO</td><td></td></tr>'


def anexos(*filas, etiqueta='Anexos :'):
    return f'<tr><td>{etiqueta}</td><td><table id="tablaAnexos">' + ''.join(filas) + '</table></td></tr>'


def historial(*filas, etiqueta='Anexos :'):
    return '<table>' + BLOQUE + anexos(*filas, etiqueta=etiqueta) + '</table>'


def extraer(html):
    return parse_actuaciones(html, 'CASO_FICTICIO')


def rechazado(html):
    with pytest.raises(ErrorParseoHistorial) as error:
        extraer(html)
    assert error.value.codigo is CodigoHistorial.ANEXO_ENLACE_AUSENTE
    assert not hasattr(error.value, 'actuaciones')  # nunca una extracción parcial


# --- Invariantes del modelo -------------------------------------------------------------

def test_anexo_sin_enlace_valido_y_su_representacion():
    a = Anexo('DESCRIPCION_FICTICIA', '', '', sin_enlace=True)
    assert a.contenido() == {'descripcion': 'DESCRIPCION_FICTICIA', 'archivo': '', 'referencia': '', 'sin_enlace': True}


def test_anexo_con_enlace_no_incluye_la_clave_nueva():
    a = Anexo('DESCRIPCION_FICTICIA', 'archivo.pdf', 'general.descargarAnexo.con?codigo=X')
    assert set(a.contenido()) == {'descripcion', 'archivo', 'referencia'} and a.sin_enlace is False


@pytest.mark.parametrize('campos', [
    ('', '', ''), ('   ', '', ''), ('D', 'archivo.pdf', ''), ('D', '', 'general.descargarAnexo.con?codigo=X'),
])
def test_invariantes_de_anexo_sin_enlace(campos):
    with pytest.raises(ValueError):
        Anexo(*campos, sin_enlace=True)


@pytest.mark.parametrize('marca', [1, 0, 'si', None])
def test_marca_debe_ser_booleana(marca):
    with pytest.raises(ValueError):
        Anexo('D', '', '', sin_enlace=marca)


@pytest.mark.parametrize('referencia', ['', '   '])
def test_anexo_sin_marca_exige_referencia(referencia):
    with pytest.raises(ValueError):
        Anexo('D', '', referencia)
    with pytest.raises(ValueError):
        Anexo('D', 'archivo.pdf', referencia)


def test_actuacion_acepta_anexos_sin_enlace_y_el_adaptador_no_los_inventa():
    a = Anexo('D', '', '', sin_enlace=True)
    act = Actuacion('E', 'A', 'B', datetime(2020, 1, 1), 'R', 'X', anexos=(a,))
    assert act.anexos == (a,)
    assert adaptar_observacion({'fecha': '2020-01-01T00:00:00', 'direccion': 'A-->B', 'descripcion': 'X'}).anexos == ()


# --- Admisión en el parser ---------------------------------------------------------------

@pytest.mark.parametrize('orden', ['sin_enlace_primero', 'sin_enlace_despues'])
def test_fila_sin_enlace_se_conserva_junto_a_una_con_enlace(orden):
    filas = (SIN_ENLACE, CON_ENLACE) if orden == 'sin_enlace_primero' else (CON_ENLACE, SIN_ENLACE)
    (actuacion,) = extraer(historial(*filas))
    por_marca = {a.sin_enlace: a for a in actuacion.anexos}
    assert len(actuacion.anexos) == 2
    assert por_marca[True] == Anexo('ANEXO_SIN_ENLACE_FICTICIO', '', '', sin_enlace=True)
    assert por_marca[False].descripcion == 'ANEXO_CON_ENLACE_FICTICIO' and por_marca[False].referencia


def test_el_orden_de_las_filas_no_cambia_la_huella_y_los_duplicados_si():
    a = extraer(historial(SIN_ENLACE, CON_ENLACE))[0]
    b = extraer(historial(CON_ENLACE, SIN_ENLACE))[0]
    duplicada = extraer(historial(SIN_ENLACE, SIN_ENLACE, CON_ENLACE))[0]
    solo_con_enlace = extraer(historial(CON_ENLACE))[0]
    assert a.huella_version == b.huella_version
    assert len(duplicada.anexos) == 3 and duplicada.huella_version != a.huella_version
    assert solo_con_enlace.huella_version != a.huella_version  # no se ignora silenciosamente


def test_varias_filas_sin_enlace_y_tablas_independientes_por_bloque():
    html = ('<table>' + BLOQUE + anexos(SIN_ENLACE, '<tr><td>OTRO_FICTICIO</td><td></td></tr>', CON_ENLACE)
            + BLOQUE.replace('2020-01-01', '2020-01-02') + anexos(CON_ENLACE, SIN_ENLACE) + '</table>')
    primera, segunda = extraer(html)
    assert [a.sin_enlace for a in primera.anexos].count(True) == 2 and len(primera.anexos) == 3
    assert [a.sin_enlace for a in segunda.anexos].count(True) == 1 and len(segunda.anexos) == 2


def test_variantes_de_etiqueta_de_la_fila_anexos():
    for etiqueta in ('ANEXOS', 'ánexos:', ' anexos  :'):
        assert len(extraer(historial(CON_ENLACE, SIN_ENLACE, etiqueta=etiqueta))[0].anexos) == 2


# --- Cada condición incumplida mantiene el rechazo ---------------------------------------

def test_condicion_1_la_tabla_debe_colgar_de_la_fila_anexos_del_bloque():
    en_contenido = ('<table>' + SEP + CABECERA + FECHA + '<tr><td>Actuación :</td><td>TEXTO_FICTICIO'
                    '<table id="tablaAnexos">' + CON_ENLACE + SIN_ENLACE + '</table></td></tr></table>')
    rechazado(en_contenido)
    rechazado(historial(CON_ENLACE, SIN_ENLACE, etiqueta='Reparto :'))
    interna = ('<table>' + BLOQUE + '<tr><td>Anexos :</td><td><table><tr><td><table id="tablaAnexos">'
               + CON_ENLACE + SIN_ENLACE + '</table></td></tr></table></td></tr></table>')
    rechazado(interna)


@pytest.mark.parametrize('fila', [
    '<tr><th>ANEXO_FICTICIO</th><td></td></tr>',
    '<tr><td>ANEXO_FICTICIO</td><th></th></tr>',
], ids=['primera_th', 'segunda_th'])
def test_condicion_2_ambas_celdas_deben_ser_td(fila):
    rechazado(historial(CON_ENLACE, fila))


def test_condicion_2_otra_cantidad_de_celdas_sigue_siendo_fila_invalida():
    for fila in ('<tr><td>ANEXO_FICTICIO</td></tr>', '<tr><td>A</td><td></td><td></td></tr>'):
        with pytest.raises(ErrorParseoHistorial) as error:
            extraer(historial(CON_ENLACE, fila))
        assert error.value.codigo is CodigoHistorial.ANEXO_FILA_INVALIDA


def test_condicion_3_la_primera_celda_no_puede_tener_forma_de_fecha_de_cabecera():
    rechazado(historial(CON_ENLACE, '<tr><td>2020-01-02 10:00:00</td><td></td></tr>'))


@pytest.mark.parametrize('segunda', [
    '<!-- COMENTARIO_FICTICIO -->', '<script>var x = 1;</script>',
    '<style>a { color: red }</style>', '<span></span>', 'TEXTO_FICTICIO', '<img src="x">',
    '<a>sin_href</a>',
], ids=['comentario', 'script', 'style', 'span_vacio', 'texto', 'imagen', 'a_sin_href'])
def test_condicion_4_la_segunda_celda_no_puede_tener_ningun_nodo(segunda):
    rechazado(historial(CON_ENLACE, f'<tr><td>ANEXO_FICTICIO</td><td>{segunda}</td></tr>'))


@pytest.mark.parametrize('segunda', ['', ' ', '&nbsp;', '<br>', '<br/>', ' &nbsp; <br> ', '\n'])
def test_condicion_4_espacios_nbsp_y_br_cuentan_como_celda_vacia(segunda):
    r = extraer(historial(CON_ENLACE, f'<tr><td>ANEXO_FICTICIO</td><td>{segunda}</td></tr>'))
    assert [a.sin_enlace for a in r[0].anexos] == [False, True]


def test_condicion_5_celda_autocerrada_o_no_verificable_se_rechaza(monkeypatch):
    rechazado(historial(CON_ENLACE, '<tr><td>ANEXO_FICTICIO</td><td/></tr>'))
    assert len(extraer(historial(CON_ENLACE, SIN_ENLACE))[0].anexos) == 2
    monkeypatch.setattr(modulo, '_celda_autocerrada', lambda *args: None)  # correspondencia no verificada
    rechazado(historial(CON_ENLACE, SIN_ENLACE))


@pytest.mark.parametrize('fila', [
    '<tr><td>ANEXO_FICTICIO</td><td></td>' + ENLACE + '</tr>',                 # enlace fuera de las celdas
    '<tr><td>ANEXO_FICTICIO</td><td/>' + ENLACE + '</tr>',                     # `<td/>` y enlace posterior
    '<tr><td><a href="general.descargarAnexo.con?codigo=X">d</a></td><td></td></tr>',  # enlace en la primera celda
], ids=['fuera_de_celdas', 'td_autocerrada', 'enlace_en_primera_celda'])
def test_condicion_6_ningun_enlace_en_la_fila(fila):
    rechazado(historial(CON_ENLACE, fila))


def test_tabla_solo_con_anexos_sin_enlace_se_admite_y_se_conserva():
    r = extraer(historial(SIN_ENLACE, '<tr><td>OTRO_FICTICIO</td><td>&nbsp;</td></tr>'))
    assert [a.sin_enlace for a in r[0].anexos] == [True, True]


def test_un_fallo_inesperado_al_evaluar_la_fila_nunca_la_admite(monkeypatch):
    def falla(*args):
        raise RuntimeError('fallo_ficticio')
    monkeypatch.setattr(modulo, '_tabla_en_fila_anexos', falla)
    rechazado(historial(CON_ENLACE, SIN_ENLACE))


def test_las_demas_reglas_de_anexos_no_cambian():
    for fila, codigo in (
        (CON_ENLACE.replace('</td></tr>', ENLACE + '</td></tr>'), CodigoHistorial.ANEXO_ENLACES_MULTIPLES),
        (CON_ENLACE.replace('general.descargarAnexo.con', 'RUTA_NO_ADMITIDA'), CodigoHistorial.ANEXO_REFERENCIA_INVALIDA),
    ):
        with pytest.raises(ErrorParseoHistorial) as error:
            extraer(historial(SIN_ENLACE, fila))
        assert error.value.codigo is codigo


def test_el_rechazo_conserva_los_indicadores_diagnosticos():
    conteos = {}
    with pytest.raises(ErrorParseoHistorial):
        parse_actuaciones(historial(CON_ENLACE, '<tr><td>ANEXO_FICTICIO</td><td><span></span></td></tr>'),
                          'CASO_FICTICIO', estadisticas=conteos)
    assert conteos['anexo_ausente_celda1_con_texto'] == 1 and conteos['anexo_ausente_celda2_hijos'] == 1
    assert conteos['anexo_ausente_tabla_en_fila_anexos'] == 1 and conteos['anexo_ausente_celda2_autocerrada'] == 0
    admitido = {}
    parse_actuaciones(historial(CON_ENLACE, SIN_ENLACE), 'CASO_FICTICIO', estadisticas=admitido)
    assert not any(k.startswith('anexo_ausente_') for k in admitido)


# --- Huella y reconciliación -------------------------------------------------------------

def test_transicion_de_sin_enlace_a_con_enlace_produce_modificacion(tmp_path, actuacion_ficticia, monitor_ficticio):
    sin = Anexo('ANEXO FICTICIO', '', '', sin_enlace=True)
    con = Anexo('ANEXO FICTICIO', 'archivo.pdf', 'general.descargarAnexo.con?codigo=FICTICIO')
    a = actuacion_ficticia(id_origen='FICTICIO-A', anexos=(sin,))
    m = monitor_ficticio(tmp_path / 'estado.json')
    assert not m.reconciliar('CASO_FICTICIO', [a]).eventos  # la línea base no genera eventos
    assert not m.reconciliar('CASO_FICTICIO', [a]).eventos  # sin cambios
    resultado = m.reconciliar('CASO_FICTICIO', [replace(a, anexos=(con,))])
    assert [e.tipo for e in resultado.eventos] == [TipoCambio.MODIFICACION_CONFIRMADA]
    de_vuelta = m.reconciliar('CASO_FICTICIO', [a])
    assert [e.tipo for e in de_vuelta.eventos] == [TipoCambio.MODIFICACION_CONFIRMADA]


def test_anexos_reordenados_con_sin_enlace_no_producen_eventos(tmp_path, actuacion_ficticia, anexo_ficticio, monitor_ficticio):
    sin = Anexo('ANEXO FICTICIO', '', '', sin_enlace=True)
    a = actuacion_ficticia(anexos=(sin, anexo_ficticio))
    m = monitor_ficticio(tmp_path / 'estado.json')
    m.reconciliar('CASO_FICTICIO', [a])
    assert not m.reconciliar('CASO_FICTICIO', [replace(a, anexos=(anexo_ficticio, sin))]).eventos


# --- Resumen del ensayo ------------------------------------------------------------------

def test_el_resumen_del_ensayo_informa_solo_la_cantidad_de_anexos_sin_enlace():
    sin = Anexo('DESCRIPCION_PRIVADA_FICTICIA', '', '', sin_enlace=True)
    con = Anexo('D', 'a.pdf', 'general.descargarAnexo.con?codigo=X')
    base = Actuacion('E', 'A', 'B', datetime(2020, 1, 1), 'R', 'X')
    historiales = [[replace(base, anexos=(sin, sin, con))], [replace(base, anexos=(sin, sin, con))]]

    class Cliente:
        def autenticar(self, *args, **kwargs):
            return [SimpleNamespace(numero='CASO_FICTICIO')]

        def listar_casos(self, **kwargs):
            return [SimpleNamespace(numero='CASO_FICTICIO')]

        def consultar_historial(self, *args, **kwargs):
            return historiales.pop(0)

    resumen = ejecutar_ensayo(Cliente(), 'u', 'c', tipo='T', total_casos=1)
    assert resumen['anexos_sin_enlace_por_consulta'] == [2, 2]
    assert resumen['resultado'] == 'estable'
    assert 'DESCRIPCION_PRIVADA_FICTICIA' not in str(resumen)
