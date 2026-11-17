"""Conservación de cabeceras históricas. Todo el material es sintético y sin red.

Cada fila de cabecera reconocible (dos celdas y fecha completa en la primera) de una tabla de
historial debe haber producido una actuación. Si no, se rechaza todo el historial, nunca se
devuelve una extracción parcial.
"""

from pathlib import Path

import pytest

import tinotify.parsers.parser as modulo
from tinotify.parsers.diagnostico_historial import (
    CLAVES_CABECERAS, CLAVES_CONTEOS, CodigoHistorial, diagnostico_seguro,
)
from tinotify.parsers.parser import ErrorParseoHistorial, parse_actuaciones


FIXTURES = Path(__file__).parent / 'fixtures'
SEP = '<tr><td colspan="2"><hr></td></tr>'
ENLACE = '<a href="general.descargarAnexo.con?codigo=CODIGO_FICTICIO">archivo_ficticio.pdf</a>'
ANEXOS = ('<tr><td>Anexos :</td><td><table id="tablaAnexos"><tr><td>ANEXO_FICTICIO</td><td>'
          + ENLACE + '</td></tr></table></td></tr>')
SEP_CON_CONTROL = '<tr><td colspan="2"><hr><input type="hidden" name="x"></td></tr>'


def bloque(n, extra='', separador=SEP):
    return (separador + f'<tr><td>TITULO_{n}</td><td>ASESOR--&gt;ESTUDIANTE</td></tr>'
            f'<tr><td>2020-01-{n:02d} 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
            f'<tr><td>Actuación :</td><td>CONTENIDO_FICTICIO_{n}</td></tr>' + extra)


PANELES = ('<div id="tabs-1"><table><tr><td><select></select></td></tr><tr><td><textarea></textarea></td></tr>'
           '<tr><td><button>Guardar</button></td></tr></table></div>')
FILA_TABS = f'<tr><td colspan="2"><div id="tabs">{PANELES}</div></td></tr>'
HISTORIAL = (bloque(1), bloque(2), bloque(3, ANEXOS))


def pagina(*filas):
    return '<html><body><form id="form1"><table>' + ''.join(filas) + '</table></form></body></html>'


def dos_tablas(*primera, segunda):
    return ('<html><body><form id="form1"><table>' + ''.join(primera) + '</table>'
            '<table>' + ''.join(segunda) + '</table></form></body></html>')


def extraer(html):
    conteos = {}
    return parse_actuaciones(html, 'CASO_FICTICIO', estadisticas=conteos), conteos


def rechazado(html, codigo=CodigoHistorial.CABECERAS_DISCORDANTES):
    conteos = {}
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(html, 'CASO_FICTICIO', estadisticas=conteos)
    assert error.value.codigo is codigo
    assert not hasattr(error.value, 'actuaciones')  # nunca una extracción parcial
    return conteos


SIN_FORMULARIO, _ = extraer(pagina(*HISTORIAL))


# --- Entradas válidas: la conservación no las rechaza ni las cambia --------------------------------------

@pytest.mark.parametrize('nombre,cantidad', [
    ('caso_prueba.html', 1), ('historial_dom_sintetico.html', 3), ('historial_malformado_recuperable.html', 1),
])
def test_los_fixtures_validos_siguen_extrayendose(nombre, cantidad):
    from backend.tests.test_parser_historial import documento_con_presentacion
    contexto = {'contenedor_id': 'historial_ficticio'} if nombre == 'historial_dom_sintetico.html' else {}
    conteos = {}
    # El original DOM contiene historia anidada ambigua, ahora prueba de rechazo.
    html = (documento_con_presentacion() if nombre == 'historial_dom_sintetico.html'
            else (FIXTURES / nombre).read_text(encoding='utf-8'))
    resultado = parse_actuaciones(html, 'CASO_FICTICIO',
                                 estadisticas=conteos, **contexto)
    assert len(resultado) == cantidad and 'cabeceras_historicas_tabla' not in conteos


def test_el_fixture_ambiguo_sigue_rechazandose_con_su_codigo_anterior():
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones((FIXTURES / 'historial_malformado_ambiguo.html').read_text(encoding='utf-8'), 'CASO_FICTICIO')
    assert error.value.codigo is not CodigoHistorial.CABECERAS_DISCORDANTES


def test_historial_con_cabecera_interna_no_se_acepta_como_texto_inocuo():
    # No contar esta cabecera en la tabla exterior no basta: su pertenencia a
    # una ocurrencia separada es ambigua y debe rechazarse todo el lote.
    interna = ('<tr><td>Reparto :</td><td>VALOR<table><tr><td colspan="2"><hr></td></tr>'
               '<tr><td>2020-05-05 10:00:00</td><td>INTERNO_FICTICIO</td></tr></table></td></tr>')
    conteos = rechazado(pagina(bloque(1), bloque(2, interna), bloque(3, ANEXOS)),
                       CodigoHistorial.AMBITO_NO_VERIFICADO)
    assert conteos['tablas_no_interpretadas'] == 1


@pytest.mark.parametrize('estructura', ['S1', 'S2', 'S3'])
def test_s1_s2_s3_con_region_excluida_conservan_igualdad_de_huellas_y_anexos(estructura):
    html = {
        'S1': pagina(*HISTORIAL, SEP, FILA_TABS),
        'S2': pagina(bloque(1), bloque(2), bloque(3, ANEXOS + FILA_TABS)),
        'S3': pagina(bloque(1), bloque(2), bloque(3, ANEXOS + f'<tr><td colspan="2"><table><tr><td><div id="tabs">'
                                                               f'{PANELES}</div></td></tr></table></td></tr>')),
    }[estructura]
    resultado, conteos = extraer(html)
    assert resultado == SIN_FORMULARIO
    assert [a.huella_version for a in resultado] == [a.huella_version for a in SIN_FORMULARIO]
    assert len(resultado[-1].anexos) == 1 and conteos['regiones_interactivas_excluidas'] == 1
    assert 'cabeceras_historicas_tabla' not in conteos


def test_varias_tablas_de_historial_validas():
    resultado, conteos = extraer(dos_tablas(*HISTORIAL, segunda=(bloque(4), bloque(5))))
    assert len(resultado) == 5 and conteos['tablas_con_bloques'] == 2


def test_tabla_con_fecha_historica_y_controles_no_se_excluye():
    formulario = ('<form><table>' + SEP + '<tr><td>2020-02-01 10:00:00</td><td>R</td></tr>'
                  '<tr><td>Actuación :</td><td><textarea></textarea></td></tr></table></form>')
    conteos = rechazado(formulario + '<table>' + ''.join(HISTORIAL) + '</table>', CodigoHistorial.BLOQUE_CON_CONTROLES)
    assert conteos['tablas_formulario_excluidas'] == 0


# --- Pérdida silenciosa que ahora se detecta ---------------------------------------------------------------

def test_control_en_la_separadora_inicial_de_la_primera_actuacion():
    html = pagina(bloque(1, separador=SEP_CON_CONTROL), bloque(2), bloque(3, ANEXOS))
    conteos = rechazado(html)
    assert conteos['cabeceras_historicas_tabla'] == 3 and conteos['actuaciones_extraidas_tabla'] == 2


def test_cabecera_absorbida_en_el_prefijo_con_controles():
    prefijo = ('<tr><td>2020-02-02 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
               '<tr><td></td><td><input type="hidden"></td></tr>')
    conteos = rechazado(pagina(prefijo, *HISTORIAL))
    assert conteos['cabeceras_historicas_tabla'] == 4 and conteos['actuaciones_extraidas_tabla'] == 3


def test_varias_tablas_la_discordancia_se_mide_por_tabla():
    conteos = rechazado(dos_tablas(*HISTORIAL, segunda=(bloque(4, separador=SEP_CON_CONTROL), bloque(5), bloque(6))))
    assert conteos['cabeceras_historicas_tabla'] == 3 and conteos['actuaciones_extraidas_tabla'] == 2
    # Una cabecera sobrante en una tabla no se compensa con una actuación de otra.
    assert conteos['tablas_con_bloques'] == 2


def test_primera_tabla_con_perdida_y_segunda_correcta():
    rechazado(dos_tablas(bloque(1, separador=SEP_CON_CONTROL), bloque(2), segunda=(bloque(4), bloque(5))))


# --- Estructuras ambiguas o malformadas: se rechazan de forma explícita, sin ajustar el conteo ----------------

def test_un_separador_malformado_se_rechaza_explicitamente():
    # Separador sin <hr> o con texto: el bloque siguiente se absorbe y el parser ya lo rechaza por su código.
    for separador in ('<tr><td colspan="2"></td></tr>', '<tr><td colspan="2"><hr>TEXTO_FICTICIO</td></tr>'):
        with pytest.raises(ErrorParseoHistorial):
            parse_actuaciones(pagina(bloque(1), bloque(2, separador=separador), bloque(3)), 'CASO_FICTICIO')


def test_separador_con_hr_en_tabla_interna_no_cuenta_como_separador():
    interno = '<tr><td colspan="2"><table><tr><td><hr></td></tr></table></td></tr>'
    with pytest.raises(ErrorParseoHistorial):
        parse_actuaciones(pagina(bloque(1), bloque(2, separador=interno), bloque(3)), 'CASO_FICTICIO')


def test_fecha_en_el_prefijo_sin_controles_conserva_su_codigo_especifico():
    prefijo = '<tr><td>2020-02-02 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
    rechazado(pagina(prefijo, *HISTORIAL), codigo=CodigoHistorial.ANTES_DEL_SEPARADOR)


def test_fila_con_fecha_fuera_de_posicion_de_cabecera_conserva_su_codigo_especifico():
    rechazado(pagina(bloque(1, '<tr><td>2020-09-09 10:00:00</td><td>R</td></tr>'), bloque(2)),
              codigo=CodigoHistorial.SEPARADOR_AUSENTE)


def test_fila_de_dos_celdas_con_fecha_incompleta_no_cuenta_como_cabecera():
    resultado, _ = extraer(pagina(bloque(1, '<tr><td>2020-09-09</td><td>VALOR_FICTICIO</td></tr>'), bloque(2)))
    assert len(resultado) == 2


def test_fecha_con_otra_cantidad_de_celdas_no_es_cabecera_y_el_parser_la_rechaza_por_su_codigo():
    for fila in ('<tr><td>2020-09-09 10:00:00</td><td>R</td><td>S</td></tr>', '<tr><td>2020-09-09 10:00:00</td></tr>'):
        rechazado(pagina(bloque(1, fila), bloque(2)), codigo=CodigoHistorial.FILA_INVALIDA)


def test_el_conteo_coincide_con_la_gramatica_del_parser_en_entradas_validas():
    from bs4 import BeautifulSoup
    from backend.tests.test_parser_historial import documento_con_presentacion
    casos = [
        (pagina(*HISTORIAL), None),
        (pagina(bloque(1), bloque(2), bloque(3, ANEXOS + FILA_TABS)), None),
        ((FIXTURES / 'caso_prueba.html').read_text(encoding='utf-8'), None),
        ((FIXTURES / 'historial_malformado_recuperable.html').read_text(encoding='utf-8'), None),
        (documento_con_presentacion(), 'historial_ficticio'),
    ]
    for html, tabla_id in casos:
        tabla = BeautifulSoup(html, 'html.parser').find('table', id=tabla_id) if tabla_id else             BeautifulSoup(html, 'html.parser').find('table')
        assert modulo._cabeceras_historicas(tabla) == len(parse_actuaciones(html, 'CASO_FICTICIO', contenedor_id=tabla_id))


# --- Salida segura ------------------------------------------------------------------------------------------

def test_conteos_solo_aparecen_en_este_rechazo_y_son_enteros_sin_contenido():
    conteos = rechazado(pagina(bloque(1, separador=SEP_CON_CONTROL), bloque(2), bloque(3)))
    assert {k for k in conteos if k in CLAVES_CABECERAS} == set(CLAVES_CABECERAS)
    salida = diagnostico_seguro(CodigoHistorial.CABECERAS_DISCORDANTES, conteos)
    assert salida['categoria'] == 'actuaciones_cabeceras_discordantes'
    assert set(salida['estadisticas_estructurales']) <= set(CLAVES_CONTEOS)
    assert all(type(v) is int and v >= 0 for v in salida['estadisticas_estructurales'].values())
    texto = str(salida)
    for secreto in ('CONTENIDO_FICTICIO', 'RESPONSABLE_FICTICIO', 'TITULO_', '2020-01'):
        assert secreto not in texto
    _, aceptado = extraer(pagina(*HISTORIAL))
    assert not any(k in aceptado for k in CLAVES_CABECERAS)
    prefijo = '<tr><td>2020-02-02 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
    otro = rechazado(pagina(prefijo, *HISTORIAL), codigo=CodigoHistorial.ANTES_DEL_SEPARADOR)
    assert not any(k in otro for k in CLAVES_CABECERAS)


def test_no_cambian_las_huellas_ni_los_anexos_de_las_entradas_validas():
    resultado, _ = extraer(pagina(*HISTORIAL))
    assert [a.huella_version for a in resultado] == [a.huella_version for a in SIN_FORMULARIO]
    assert [len(a.anexos) for a in resultado] == [0, 0, 1]
