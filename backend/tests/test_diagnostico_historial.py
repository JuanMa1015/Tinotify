"""Códigos y conteos sintéticos; no conservar ni imprimir contenido DOM."""

import json
import socket

import pytest

from tinotify.parsers.diagnostico_historial import CLAVES_CONTEOS, CodigoHistorial, diagnostico_seguro
from tinotify.parsers.parser import ErrorParseoHistorial, parse_actuaciones


PRIVADO = 'MARCADOR_PRIVADO_FICTICIO_NO_IMPRIMIR'
SEPARADOR = '<tr><td colspan="2"><hr></td></tr>'
CABECERA = '<tr><td>TITULO_FICTICIO</td><td>ASESOR--&gt;ESTUDIANTE</td></tr>'
FECHA = '<tr><td>2020-01-01 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
CONTENIDO = '<tr><td>Actuación :</td><td>' + PRIVADO + '</td></tr>'
BLOQUE = SEPARADOR + CABECERA + FECHA + CONTENIDO
BASE = '<table>' + BLOQUE + '</table>'
ENLACE = '<a href="general.descargarAnexo.con?codigo=REFERENCIA_FICTICIA">ARCHIVO_FICTICIO</a>'


def anexos(fila):
    return '<tr><td>Anexos :</td><td><table id="tablaAnexos">' + fila + '</table></td></tr>'


def con_anexos(fila):
    return '<table>' + BLOQUE + anexos(fila) + '</table>'


CASOS = [
    (BASE, {'contenedor_id': ''}, CodigoHistorial.CONTENEDOR_INVALIDO),
    (BASE, {'contenedor_id': PRIVADO}, CodigoHistorial.CONTENEDOR_AUSENTE),
    ('<section id="x"></section><section id="x"></section>' + BASE,
     {'contenedor_id': 'x'}, CodigoHistorial.CONTENEDOR_DUPLICADO),
    (con_anexos('<tr><td>ANEXO_FICTICIO</td><td>' + ENLACE + '</td></tr>'),
     {'contenedor_id': 'tablaAnexos'}, CodigoHistorial.CONTENEDOR_ANEXOS),
    ('<section id="x"></section>', {'contenedor_id': 'x'}, CodigoHistorial.CONTENEDOR_SIN_TABLAS),
    (BASE + '<table><tr><td>' + PRIVADO + '</td></tr></table>', {}, CodigoHistorial.AMBITO_NO_VERIFICADO),
    ('<table>' + BLOQUE.removeprefix(SEPARADOR) + BLOQUE + '</table>', {}, CodigoHistorial.ANTES_DEL_SEPARADOR),
    (BASE.replace(PRIVADO, '<input value="' + PRIVADO + '">'), {}, CodigoHistorial.BLOQUE_CON_CONTROLES),
    (BASE.replace('2020-01-01 10:00:00', PRIVADO), {}, CodigoHistorial.CABECERA_INVALIDA),
    (BASE.replace('2020-01-01', '2020-99-01'), {}, CodigoHistorial.FECHA_INVALIDA),
    (BASE.replace('RESPONSABLE_FICTICIO', ''), {}, CodigoHistorial.RESPONSABLE_AUSENTE),
    (BASE.replace(CABECERA, '<tr><td>A</td><td>B</td><td>C</td></tr>'), {}, CodigoHistorial.TITULO_INVALIDO),
    (BASE.replace('ASESOR--&gt;ESTUDIANTE', PRIVADO), {}, CodigoHistorial.COMUNICACION_INVALIDA),
    (BASE.replace(CONTENIDO, '<tr><td>A</td><td>B</td><td>C</td></tr>'), {}, CodigoHistorial.FILA_INVALIDA),
    (BASE.replace('Actuación :', '<table><tr><td>ETIQUETA_FICTICIA</td></tr></table>'), {}, CodigoHistorial.ETIQUETA_INVALIDA),
    (BASE.replace(CONTENIDO, FECHA + CONTENIDO), {}, CodigoHistorial.SEPARADOR_AUSENTE),
    (BASE.replace(CONTENIDO, ''), {}, CodigoHistorial.SIN_CONTENIDO),
    ('<table>' + BLOQUE + '<tr><td>Anexos :</td><td>' + PRIVADO + '</td></tr></table>',
     {}, CodigoHistorial.ANEXOS_CONTENIDO_INVALIDO),
    (con_anexos('<table id="tablaAnexos"></table>'), {}, CodigoHistorial.ANEXOS_ANIDADOS),
    (con_anexos('<tr><td>ANEXO_FICTICIO</td></tr>'), {}, CodigoHistorial.ANEXO_FILA_INVALIDA),
    (con_anexos('<tr><td>ANEXO_FICTICIO</td><td>' + PRIVADO + '</td></tr>'), {}, CodigoHistorial.ANEXO_ENLACE_AUSENTE),
    (con_anexos('<tr><td>ANEXO_FICTICIO</td><td>' + ENLACE * 2 + '</td></tr>'), {}, CodigoHistorial.ANEXO_ENLACES_MULTIPLES),
    (con_anexos('<tr><td>ANEXO_FICTICIO</td><td>' + ENLACE.replace('general.descargarAnexo.con', 'RUTA_NO_ADMITIDA') + '</td></tr>'),
     {}, CodigoHistorial.ANEXO_REFERENCIA_INVALIDA),
]


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('La prueba de diagnóstico no puede abrir conexiones')
    monkeypatch.setattr(socket.socket, 'connect', prohibido)
    monkeypatch.setattr(socket, 'create_connection', prohibido)


@pytest.mark.parametrize('html,opciones,codigo', CASOS, ids=[c[2].value for c in CASOS])
def test_codigo_preciso_y_salida_sin_datos(html, opciones, codigo, capsys):
    conteos = {}
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(html, PRIVADO, estadisticas=conteos, **opciones)
    assert error.value.codigo is codigo
    salida = diagnostico_seguro(error.value.codigo, conteos)
    assert salida['categoria'] == codigo.value
    assert set(salida) == {'diagnostico_version', 'etapa', 'categoria', 'estadisticas_estructurales'}
    assert set(salida['estadisticas_estructurales']) <= set(CLAVES_CONTEOS)
    assert all(type(v) is int and v >= 0 for v in salida['estadisticas_estructurales'].values())
    texto = json.dumps(salida)
    for secreto in (PRIVADO, 'TITULO_FICTICIO', 'RESPONSABLE_FICTICIO', '2020-01-01',
                    'REFERENCIA_FICTICIA', 'ARCHIVO_FICTICIO', 'tablaAnexos', 'RUTA_NO_ADMITIDA'):
        assert secreto not in texto
    assert capsys.readouterr().out == ''


CERO = {
    'anexo_ausente_celdas_th': 0, 'anexo_ausente_celda1_con_texto': 1,
    'anexo_ausente_celda2_con_texto': 0, 'anexo_ausente_a_sin_href_celda2': 0,
    'anexo_ausente_a_href_celda1': 0, 'anexo_ausente_a_href_anidado_celda2': 0,
    'anexo_ausente_imagenes_celda2': 0, 'anexo_ausente_onclick_celda2': 0,
}
NUEVOS = ('anexo_ausente_celda2_autocerrada', 'anexo_ausente_a_fuera_de_celdas',
          'anexo_ausente_celda2_no_visibles', 'anexo_ausente_celda2_hijos')
FILA = '<tr><td>ANEXO_FICTICIO</td><td>{}</td></tr>'
VARIANTES_ENLACE_AUSENTE = {
    'a_sin_href': (FILA.format('<a>' + PRIVADO + '</a>'),
                   {'anexo_ausente_a_sin_href_celda2': 1, 'anexo_ausente_celda2_con_texto': 1}),
    'enlace_en_primera_celda': ('<tr><td>' + ENLACE + '</td><td>' + PRIVADO + '</td></tr>',
                                {'anexo_ausente_a_href_celda1': 1, 'anexo_ausente_celda2_con_texto': 1}),
    'enlace_en_tabla_anidada': (FILA.format('<table><tr><td>' + ENLACE + '</td></tr></table>'),
                                {'anexo_ausente_a_href_anidado_celda2': 1, 'anexo_ausente_celda2_con_texto': 1}),
    'fila_informativa': (FILA.format(PRIVADO), {'anexo_ausente_celda2_con_texto': 1}),
    'celda_vacia': (FILA.format(''), {}),
    'fila_con_th': ('<tr><td>ANEXO_FICTICIO</td><th>' + PRIVADO + '</th></tr>',
                    {'anexo_ausente_celdas_th': 1, 'anexo_ausente_celda2_con_texto': 1}),
    'imagen': (FILA.format('<img src="' + PRIVADO + '">'), {'anexo_ausente_imagenes_celda2': 1}),
    'onclick': (FILA.format('<span onclick="' + PRIVADO + '">X</span>'),
                {'anexo_ausente_onclick_celda2': 1, 'anexo_ausente_celda2_con_texto': 1}),
    'onclick_en_a_sin_href': (FILA.format('<a onclick="' + PRIVADO + '">X</a>'),
                              {'anexo_ausente_a_sin_href_celda2': 1, 'anexo_ausente_onclick_celda2': 1,
                               'anexo_ausente_celda2_con_texto': 1}),
}


@pytest.mark.parametrize('fila,esperado', VARIANTES_ENLACE_AUSENTE.values(),
                         ids=VARIANTES_ENLACE_AUSENTE.keys())
def test_indicadores_de_enlace_ausente(fila, esperado):
    conteos = {}
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(con_anexos(fila), PRIVADO, estadisticas=conteos)
    assert error.value.codigo is CodigoHistorial.ANEXO_ENLACE_AUSENTE
    salida = diagnostico_seguro(error.value.codigo, conteos)['estadisticas_estructurales']
    assert {k: v for k, v in salida.items() if k in CERO} == {**CERO, **esperado}
    assert set(NUEVOS) <= set(salida)  # verificables aquí: la posición original coincide
    assert salida['bloques_rechazados'] == 1 and salida['bloques_validos'] == 0
    assert set(salida) <= set(CLAVES_CONTEOS)
    texto = json.dumps(salida)
    for secreto in (PRIVADO, 'REFERENCIA_FICTICIA', 'ARCHIVO_FICTICIO', 'ANEXO_FICTICIO', 'general.descargarAnexo'):
        assert secreto not in texto


# Pruebas de caracterización: fijan el comportamiento ACTUAL (rechazo) ante marcado
# que produce la misma firma que el ensayo real. No demuestran que SIGAC use ninguna
# de estas formas ni justifican relajar el parser.
ANEXO_VALIDO = FILA.format(ENLACE)
MISMA_FIRMA = {
    'enlace_fuera_de_la_celda': '<tr><td>ANEXO_FICTICIO</td><td></td>' + ENLACE + '</tr>',
    'td_autocerrada_seguida_de_enlace': '<tr><td>ANEXO_FICTICIO</td><td/>' + ENLACE + '</tr>',
    'celda2_solo_comentario': FILA.format('<!-- COMENTARIO_FICTICIO -->'),
    'celda2_solo_script': FILA.format('<script>var x_ficticio = 1;</script>'),
    'celda2_solo_style': FILA.format('<style>a { color: red }</style>'),
    # Sin ninguna fila con enlace en la tabla (condición 7) la fila vacía sigue rechazándose.
    'fila_informativa_sola_sin_filas_con_enlace': '<tr><td>TOTAL_FICTICIO</td><td></td></tr>',
}
FUERA = '<tr><td>ANEXO_FICTICIO</td><td></td>' + ENLACE + '</tr>'  # enlace fuera de la celda: rechazo


@pytest.mark.parametrize('fila', MISMA_FIRMA.values(), ids=MISMA_FIRMA.keys())
def test_marcado_con_la_firma_observada_sigue_rechazandose(fila):
    conteos = {}
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(con_anexos(fila), PRIVADO, estadisticas=conteos)
    assert error.value.codigo is CodigoHistorial.ANEXO_ENLACE_AUSENTE
    indicadores = {k: v for k, v in conteos.items() if k in CERO}
    assert indicadores == CERO  # indistinguibles con los ocho indicadores originales
    assert conteos['bloques_validos'] == 0 and conteos['bloques_rechazados'] == 1


ACEPTADOS = {
    'tabla_vacia': ('', 0),
    'solo_cabecera_th': ('<tr><th>D</th><th>A</th></tr>', 0),
    'tr_sin_cerrar_todas_con_enlace': ('<tr><td>A</td><td>' + ENLACE + '</td><tr><td>B</td><td>' + ENLACE + '</td>', 2),
    'fila_de_separador_hr': ('<tr><td colspan="2"><hr></td></tr>' + ANEXO_VALIDO, 1),
    'fila_totalmente_vacia': ('<tr><td></td><td></td></tr>' + ANEXO_VALIDO, 1),
}


@pytest.mark.parametrize('filas,cantidad', ACEPTADOS.values(), ids=ACEPTADOS.keys())
def test_estructuras_de_anexos_que_se_aceptan_hoy(filas, cantidad):
    resultado = parse_actuaciones(con_anexos(filas), PRIVADO)
    assert len(resultado) == 1 and len(resultado[0].anexos) == cantidad


def test_tablas_de_anexos_repetidas_en_un_bloque_se_acumulan():
    html = '<table>' + BLOQUE + anexos(ANEXO_VALIDO) + anexos(ANEXO_VALIDO) + '</table>'
    assert len(parse_actuaciones(html, PRIVADO)[0].anexos) == 2


# (autocerrada, a_fuera_de_celdas, no_visibles, hijos) para cada variante.
NUEVE_VARIANTES = {
    'td_autocerrada_y_enlace_posterior': ('<tr><td>ANEXO_FICTICIO</td><td/>' + ENLACE + '</tr>', (1, 1, 0, 0)),
    'td_autocerrada_con_atributo_y_signo_mayor': (
        '<tr><td>ANEXO_FICTICIO</td><td class="a>b" />' + ENLACE + '</tr>', (1, 1, 0, 0)),
    'enlace_fuera_de_la_celda': ('<tr><td>ANEXO_FICTICIO</td><td></td>' + ENLACE + '</tr>', (0, 1, 0, 0)),
    'script': (FILA.format('<script>var x_ficticio = 1;</script>'), (0, 0, 1, 1)),
    'style': (FILA.format('<style>a { color: red }</style>'), (0, 0, 1, 1)),
    'comentario': (FILA.format('<!-- COMENTARIO_FICTICIO -->'), (0, 0, 1, 1)),
    'realmente_vacia': (FILA.format(''), (0, 0, 0, 0)),
    'solo_espacios_ascii': (FILA.format('  \n\t '), (0, 0, 0, 0)),
    'br': (FILA.format('<br>'), (0, 0, 0, 1)),
    'nbsp': (FILA.format('&nbsp;'), (0, 0, 0, 1)),
    'td_autocerrada_sin_enlace': ('<tr><td>ANEXO_FICTICIO</td><td/></tr>', (1, 0, 0, 0)),
}


def rechazar(html):
    conteos = {}
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(html, PRIVADO, estadisticas=conteos)
    assert error.value.codigo is CodigoHistorial.ANEXO_ENLACE_AUSENTE
    return conteos


def nuevos(conteos):
    return tuple(conteos.get(k) for k in NUEVOS)


@pytest.mark.parametrize('fila,esperado', NUEVE_VARIANTES.values(), ids=NUEVE_VARIANTES.keys())
def test_indicadores_de_posicion_distinguen_las_hipotesis(fila, esperado):
    conteos = rechazar(con_anexos(fila))
    assert nuevos(conteos) == esperado
    assert all(type(conteos[k]) is int and conteos[k] >= 0 for k in NUEVOS)
    texto = json.dumps(diagnostico_seguro(CodigoHistorial.ANEXO_ENLACE_AUSENTE, conteos))
    for secreto in (PRIVADO, 'COMENTARIO_FICTICIO', 'x_ficticio', 'ANEXO_FICTICIO', 'REFERENCIA_FICTICIA'):
        assert secreto not in texto


SEPARADORES = ['\r\n', '\r', '\x0b', '\x0c', '\x1c', '\x1d', '\x1e', '\x85', ' ', ' ']


@pytest.mark.parametrize('separador', SEPARADORES, ids=[repr(s) for s in SEPARADORES])
def test_separadores_de_linea_especiales_no_desplazan_la_correspondencia(separador):
    prefijo = '<p>' + separador + 'año 😀 ñ' + separador + '</p>\n<p>\r\n</p>\n'
    for fila, valor in (('<tr><td>ANEXO_FICTICIO</td><td/></tr>', 1), (FUERA, 0)):
        # Antes del rechazo hay una fila idéntica en texto, con enlace, y una `<td/>` ajena.
        previas = ('<tr><td>Campo ficticio :</td><td/></tr>', '\n' + ANEXO_VALIDO + '\n')
        html = prefijo + '<table>' + BLOQUE + previas[0] + anexos(previas[1] + fila) + '</table>'
        assert nuevos(rechazar(html))[0] == valor


def test_filas_identicas_repetidas_no_se_confunden():
    # Una `<td/>` ajena anterior no contamina una fila vacía normal posterior...
    anterior = '<tr><td>Campo ficticio :</td><td/></tr>'
    html = '<table>' + BLOQUE + anterior + anexos(ANEXO_VALIDO + FUERA) + '</table>'
    assert nuevos(rechazar(html))[0] == 0
    # ...ni una vacía normal anterior oculta la `<td/>` rechazada.
    previas = FILA.format('VALOR_FICTICIO') + ANEXO_VALIDO
    html = ('<table>' + BLOQUE + anexos(ANEXO_VALIDO) + anexos(ANEXO_VALIDO) + '</table>'
            '<table>' + BLOQUE + '<tr><td>Campo ficticio :</td><td></td></tr>'
            + anexos(ANEXO_VALIDO + '<tr><td>ANEXO_FICTICIO</td><td/></tr>') + '</table>')
    assert nuevos(rechazar(html))[0] == 1


def test_etiqueta_larga_usa_tramos_y_falla_cerrado_si_excede():
    larga = '<tr><td>ANEXO_FICTICIO</td><td class="' + 'x' * 20000 + '"/></tr>'
    assert rechazar(con_anexos(larga))['anexo_ausente_celda2_autocerrada'] == 1
    excesiva = '<tr><td>ANEXO_FICTICIO</td><td class="' + 'x' * 140000 + '"/></tr>'
    conteos = rechazar(con_anexos(excesiva))
    assert 'anexo_ausente_celda2_autocerrada' not in conteos  # desconocido, no 0
    assert conteos['anexo_ausente_a_fuera_de_celdas'] == 0 and 'anexo_ausente_celda2_hijos' in conteos


def _segunda_celda(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, 'html.parser').find_all('td')[1]


def test_fallos_de_correspondencia_omiten_el_dato_en_lugar_de_informar_cero():
    from tinotify.parsers.parser import _celda_autocerrada
    html = '<table>\n<tr><td>A</td><td/></tr></table>'
    celda = _segunda_celda(html)
    assert _celda_autocerrada(html, celda) == 1
    assert _celda_autocerrada(None, celda) is None
    assert _celda_autocerrada(html.replace('<td/>', '<th/>'), celda) is None   # otro nombre
    assert _celda_autocerrada(html.replace('<td/>', ' td/>'), celda) is None   # no hay '<'
    assert _celda_autocerrada(html[:-20], celda) is None                       # documento truncado
    assert _celda_autocerrada('<table><tr><td>A</td><td/></tr></table>', celda) is None  # línea distinta
    for campo, valor in (('sourceline', None), ('sourcepos', None), ('sourceline', 0),
                         ('sourcepos', -1), ('sourceline', 99), ('sourcepos', 10**6),
                         ('sourceline', True)):
        copia = _segunda_celda(html)
        setattr(copia, campo, valor)
        assert _celda_autocerrada(html, copia) is None, (campo, valor)


def test_si_la_correspondencia_no_se_verifica_el_rechazo_y_los_demas_indicadores_no_cambian(monkeypatch):
    import tinotify.parsers.parser as modulo
    html = con_anexos('<tr><td>ANEXO_FICTICIO</td><td/>' + ENLACE + '</tr>')
    con = rechazar(html)
    monkeypatch.setattr(modulo, '_celda_autocerrada', lambda *a: None)
    sin = rechazar(html)
    assert 'anexo_ausente_celda2_autocerrada' in con and 'anexo_ausente_celda2_autocerrada' not in sin
    assert {k: v for k, v in con.items() if k != 'anexo_ausente_celda2_autocerrada'} == sin


def test_error_inesperado_en_el_diagnostico_no_cambia_el_codigo_de_rechazo(monkeypatch):
    import tinotify.parsers.parser as modulo
    def falla(*args):
        raise RuntimeError('fallo_ficticio')
    monkeypatch.setattr(modulo, '_indicadores_posicion_enlace_ausente', falla)
    conteos = rechazar(con_anexos(FILA.format('')))
    assert not any(k in conteos for k in NUEVOS) and 'anexo_ausente_celdas_th' in conteos


def test_enlace_en_fila_anterior_o_en_celdas_ajenas_no_cuenta_como_fuera_de_celdas():
    # `<tr>` sin cerrar: el enlace de la fila siguiente (anidada en el DOM) no es "fuera de celdas".
    html = con_anexos('<tr><td>ANEXO_FICTICIO</td><td></td><tr><td>OTRO</td><td>' + ENLACE + '</td>')
    assert nuevos(rechazar(html)) == (0, 0, 0, 0)
    # Un enlace dentro de una tabla interna de la segunda celda cuenta como anidado, no como "fuera".
    html = con_anexos(FILA.format('<table><tr><td>' + ENLACE + '</td></tr></table>'))
    conteos = rechazar(html)
    assert conteos['anexo_ausente_a_href_anidado_celda2'] == 1 and conteos['anexo_ausente_a_fuera_de_celdas'] == 0


CONTEXTO = ('anexo_ausente_tabla_en_fila_anexos', 'anexo_ausente_filas_forma_cabecera',
            'anexo_ausente_filas_equivalentes_otras_tablas')
VACIA = '<tr><td>ANEXO_FICTICIO</td><td></td></tr>'
FILA_ANEXOS = '<tr><td>{}</td><td><table id="tablaAnexos">{}</table></td></tr>'


def contexto(conteos):
    return tuple(conteos.get(k) for k in CONTEXTO)


def bloque_con(fila_final, etiqueta='Anexos :'):
    return '<table>' + BLOQUE + FILA_ANEXOS.format(etiqueta, fila_final) + '</table>'


@pytest.mark.parametrize('etiqueta', ['Anexos :', 'ANEXOS', 'ánexos:', ' anexos  :'])
def test_ubicacion_en_la_fila_anexos_de_su_propio_bloque(etiqueta):
    assert contexto(rechazar(bloque_con(VACIA, etiqueta)))[0] == 1


def test_ubicacion_fuera_de_la_fila_anexos_o_en_casos_ambiguos_da_cero():
    contenido = '<tr><td>Actuación :</td><td>TEXTO_FICTICIO<table id="tablaAnexos">' + VACIA + '</table></td></tr>'
    otra = bloque_con(VACIA, 'Reparto :')
    interna = ('<table>' + BLOQUE + '<tr><td>Anexos :</td><td><table><tr><td>'
               '<table id="tablaAnexos">' + VACIA + '</table></td></tr></table></td></tr></table>')
    for html in ('<table>' + SEPARADOR + CABECERA + FECHA + contenido + '</table>', otra, interna):
        assert contexto(rechazar(html))[0] == 0


def test_ubicacion_se_refiere_a_la_fila_de_su_propio_bloque_no_a_otra():
    # La segunda actuación (rechazada) tiene su tabla bajo otra etiqueta; la primera sí está bajo «Anexos».
    html = ('<table>' + BLOQUE + FILA_ANEXOS.format('Anexos :', ANEXO_VALIDO)
            + BLOQUE + FILA_ANEXOS.format('Otra cosa :', VACIA) + '</table>')
    assert contexto(rechazar(html))[0] == 0


CABECERA_ACTUACION = '<tr><td>2020-01-02 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'


def test_filas_con_forma_de_cabecera_de_actuacion():
    assert contexto(rechazar(bloque_con(VACIA)))[1] == 0
    assert contexto(rechazar(bloque_con(VACIA + CABECERA_ACTUACION + CABECERA_ACTUACION)))[1] == 2
    # Un anexo legítimo cuya descripción es una fecha, con enlace, no cuenta.
    con_enlace = '<tr><td>2020-01-02 10:00:00</td><td>' + ENLACE + '</td></tr>'
    assert contexto(rechazar(bloque_con(con_enlace + FUERA + con_enlace)))[1] == 0
    # Fecha incompleta o segunda celda vacía: no tiene esa forma.
    parcial = '<tr><td>2020-01-02</td><td>X</td></tr><tr><td>2020-01-02 10:00:00</td><td></td></tr>'
    assert contexto(rechazar(bloque_con(VACIA + parcial)))[1] == 0


def test_filas_con_forma_de_cabecera_solo_se_cuentan_en_la_tabla_rechazada():
    html = ('<table>' + BLOQUE + FILA_ANEXOS.format('Anexos :', CABECERA_ACTUACION.replace('RESPONSABLE', 'OTRO') + ANEXO_VALIDO)
            + '</table>')
    assert parse_actuaciones.__name__  # la fila con texto y sin enlace de esa tabla es la rechazada, no un contexto
    conteos = rechazar(html)
    assert conteos['anexo_ausente_celda2_con_texto'] == 1 and conteos['anexo_ausente_filas_forma_cabecera'] == 1


def doble(rechazada, otra, etiqueta_otra='Anexos :'):
    return ('<table>' + BLOQUE + FILA_ANEXOS.format('Anexos :', rechazada)
            + BLOQUE + FILA_ANEXOS.format(etiqueta_otra, otra) + '</table>')


def test_filas_equivalentes_en_otras_tablas_incluidas_las_no_procesadas():
    assert contexto(rechazar(doble(VACIA, VACIA + VACIA)))[2] == 2
    assert contexto(rechazar(bloque_con(VACIA)))[2] == 0
    # Normalización: mayúsculas, acentos, dos puntos finales y espacios.
    equivalente = '<tr><td> Ánexo_Ficticio : </td><td> </td></tr>'
    assert contexto(rechazar(doble(VACIA, equivalente)))[2] == 1


def test_filas_no_equivalentes_no_se_cuentan():
    casos = {
        'otro_texto': '<tr><td>OTRO_FICTICIO</td><td></td></tr>',
        'segunda_celda_con_br': '<tr><td>ANEXO_FICTICIO</td><td><br></td></tr>',
        'segunda_celda_con_comentario': '<tr><td>ANEXO_FICTICIO</td><td><!-- c --></td></tr>',
        'segunda_celda_con_enlace': FILA.format(ENLACE),
        'primera_celda_th': '<tr><th>ANEXO_FICTICIO</th><td></td></tr>',
        'tres_celdas': '<tr><td>ANEXO_FICTICIO</td><td></td><td></td></tr>',
    }
    for nombre, otra in casos.items():
        assert contexto(rechazar(doble(VACIA, otra)))[2] == 0, nombre


def test_las_filas_equivalentes_de_la_propia_tabla_no_cuentan_como_otras():
    assert contexto(rechazar(bloque_con(VACIA + VACIA + VACIA)))[2] == 0


def test_equivalentes_se_busca_en_todo_el_documento_y_solo_en_tablas_de_anexos():
    ajena = '<table><tr><td>ANEXO_FICTICIO</td><td></td></tr></table>'  # sin id tablaAnexos
    assert contexto(rechazar(ajena + bloque_con(VACIA)))[2] == 0
    html = bloque_con(VACIA) + '<table id="tablaAnexos">' + VACIA + '</table>'  # fuera del historial
    assert contexto(rechazar(html))[2] == 1


def test_sin_texto_en_la_primera_celda_la_equivalencia_se_omite():
    html = bloque_con('<tr><td></td><td>' + PRIVADO + '</td></tr>')
    conteos = rechazar(html)
    assert 'anexo_ausente_filas_equivalentes_otras_tablas' not in conteos
    assert 'anexo_ausente_tabla_en_fila_anexos' in conteos and 'anexo_ausente_filas_forma_cabecera' in conteos


def test_mediciones_de_contexto_son_independientes_y_omiten_si_fallan(monkeypatch):
    import tinotify.parsers.parser as modulo
    def falla(*args):
        raise RuntimeError('fallo_ficticio')
    for nombre, clave in (('_tabla_en_fila_anexos', CONTEXTO[0]), ('_filas_forma_cabecera', CONTEXTO[1]),
                          ('_filas_equivalentes_otras_tablas', CONTEXTO[2])):
        with monkeypatch.context() as m:
            m.setattr(modulo, nombre, falla)
            conteos = rechazar(bloque_con(VACIA))
        assert clave not in conteos
        assert all(otra in conteos for otra in CONTEXTO if otra != clave)
    with monkeypatch.context() as m:
        m.setattr(modulo, '_indicadores_contexto_enlace_ausente', falla)
        conteos = rechazar(bloque_con(VACIA))
    assert not any(k in conteos for k in CONTEXTO) and 'anexo_ausente_celda2_hijos' in conteos


def test_documento_sin_raiz_verificable_omite_la_equivalencia():
    from bs4 import BeautifulSoup
    from tinotify.parsers.parser import _filas_equivalentes_otras_tablas
    soup = BeautifulSoup('<table id="tablaAnexos">' + VACIA + '</table>', 'html.parser')
    tabla = soup.table.extract()  # sin árbol de documento
    assert _filas_equivalentes_otras_tablas(tabla, tabla.find('td')) is None


def test_el_contexto_se_mide_sobre_el_arbol_existente_sin_reparsear_ni_mutarlo(monkeypatch):
    import tinotify.parsers.parser as modulo
    from bs4 import BeautifulSoup
    llamadas = []
    original = modulo.BeautifulSoup
    def contado(*args, **kwargs):
        llamadas.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(modulo, 'BeautifulSoup', contado)
    rechazar(doble(VACIA, VACIA))
    assert len(llamadas) == 1  # el mismo árbol del parseo; ninguna segunda extracción
    soup = BeautifulSoup(doble(VACIA, VACIA), 'html.parser')
    antes = str(soup)
    tabla = soup.find('table', id='tablaAnexos')
    fila = tabla.find_parent('tr')
    modulo._indicadores_contexto_enlace_ausente(fila, tabla, modulo._celdas(tabla.find('tr')))
    assert str(soup) == antes


def test_contexto_no_aparece_fuera_de_enlace_ausente_ni_filtra_contenido():
    for html in (con_anexos(FILA.format(ENLACE * 2)), con_anexos('<tr><td>ANEXO_FICTICIO</td></tr>')):
        conteos = {}
        with pytest.raises(ErrorParseoHistorial):
            parse_actuaciones(html, PRIVADO, estadisticas=conteos)
        assert not any(k in conteos for k in CONTEXTO)
    conteos = {}
    parse_actuaciones(con_anexos(ANEXO_VALIDO), PRIVADO, estadisticas=conteos)
    assert not any(k in conteos for k in CONTEXTO)
    salida = diagnostico_seguro(CodigoHistorial.ANEXO_ENLACE_AUSENTE, rechazar(doble(VACIA, VACIA)))
    assert all(type(v) is int and v >= 0 for v in salida['estadisticas_estructurales'].values())
    texto = json.dumps(salida)
    for secreto in (PRIVADO, 'ANEXO_FICTICIO', 'RESPONSABLE_FICTICIO', 'tablaAnexos', 'Anexos'):
        assert secreto not in texto


def test_boton_o_input_en_anexo_sigue_rechazado_como_control_sin_indicadores():
    for control in ('<button>X</button>', '<input value="' + PRIVADO + '">'):
        conteos = {}
        with pytest.raises(ErrorParseoHistorial) as error:
            parse_actuaciones(con_anexos(FILA.format(control)), PRIVADO, estadisticas=conteos)
        assert error.value.codigo is CodigoHistorial.BLOQUE_CON_CONTROLES
        assert not any(k.startswith('anexo_ausente_') for k in conteos)


def test_indicadores_solo_aparecen_en_enlace_ausente_y_no_alteran_otros_resultados():
    for html, codigo in (
        (con_anexos(FILA.format(ENLACE * 2)), CodigoHistorial.ANEXO_ENLACES_MULTIPLES),
        (con_anexos('<tr><td>ANEXO_FICTICIO</td></tr>'), CodigoHistorial.ANEXO_FILA_INVALIDA),
    ):
        conteos = {}
        with pytest.raises(ErrorParseoHistorial) as error:
            parse_actuaciones(html, PRIVADO, estadisticas=conteos)
        assert error.value.codigo is codigo
        assert not any(k.startswith('anexo_ausente_') for k in conteos)
    conteos = {}
    assert parse_actuaciones(con_anexos(FILA.format(ENLACE)), PRIVADO, estadisticas=conteos)
    assert not any(k.startswith('anexo_ausente_') for k in conteos)


def test_estadisticas_del_rechazo_no_permiten_recuperar_extraccion_parcial():
    conteos = {}
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(BASE + '<table><tr><td>DESCONOCIDO_FICTICIO</td></tr></table>', 'FICTICIO', estadisticas=conteos)
    assert error.value.codigo is CodigoHistorial.AMBITO_NO_VERIFICADO
    assert conteos['tablas_documento'] == conteos['tablas_ambito'] == 2
    assert conteos['bloques_validos'] == conteos['tablas_no_interpretadas'] == 1
    assert not hasattr(error.value, 'actuaciones')
    with pytest.raises(ErrorParseoHistorial):
        parse_actuaciones(BASE + '<table><tr><td>DESCONOCIDO_FICTICIO</td></tr></table>', 'FICTICIO')


def test_diagnostico_no_cambia_datos_aceptados_y_limpia_colector():
    conteos = {PRIVADO: PRIVADO}
    esperado = parse_actuaciones(BASE, 'FICTICIO')
    assert parse_actuaciones(BASE, 'FICTICIO', estadisticas=conteos) == esperado
    assert conteos['bloques_validos'] == 1 and conteos['bloques_rechazados'] == 0
    assert PRIVADO not in conteos


def test_exportador_falla_cerrado_ante_campos_o_codigos_no_autorizados():
    salida = diagnostico_seguro(PRIVADO, {PRIVADO: PRIVADO, 'tablas_documento': PRIVADO,
                                          'filas_documento': -1, 'bloques_validos': True})
    assert salida == {'diagnostico_version': 2, 'etapa': 'no_determinada', 'categoria': 'fallo_no_clasificado',
                      'estadisticas_estructurales': {}}
