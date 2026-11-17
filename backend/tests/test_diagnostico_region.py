"""Indicadores numéricos de `_region_interactiva`. Todo el material es sintético.

Solo diagnostican: cuando una actuación se rechaza por controles y no se excluyó ninguna región,
informan qué criterios se cumplen. No cambian el resultado del parser ni las reglas.
"""

import json

from bs4 import BeautifulSoup
import pytest

import tinotify.parsers.parser as modulo
from tinotify.parsers.diagnostico_historial import (
    CLAVES_CONTEOS, CLAVES_REGION_INTERACTIVA, CodigoHistorial, diagnostico_seguro,
)
from tinotify.parsers.parser import ErrorParseoHistorial, parse_actuaciones


SEP = '<tr><td colspan="2"><hr></td></tr>'
ENLACE = '<a href="general.descargarAnexo.con?codigo=CODIGO_FICTICIO">archivo_ficticio.pdf</a>'
ANEXOS = ('<tr><td>Anexos :</td><td><table id="tablaAnexos"><tr><td>ANEXO_FICTICIO</td><td>'
          + ENLACE + '</td></tr></table></td></tr>')


def bloque(n, extra=''):
    return (SEP + f'<tr><td>TITULO_{n}</td><td>ASESOR--&gt;ESTUDIANTE</td></tr>'
            f'<tr><td>2020-01-{n:02d} 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
            f'<tr><td>Actuación :</td><td>CONTENIDO_FICTICIO_{n}</td></tr>' + extra)


PANELES = ('<ul><li><a href="#tabs-1">Actuar</a></li></ul><div id="tabs-1"><table><tr><td>'
           '<select><option>a</option></select></td></tr><tr><td><textarea></textarea></td></tr>'
           '<tr><td><button>Guardar</button></td></tr></table></div><div id="tabs-3"></div>')
TABS = '<div id="tabs">' + PANELES + '</div>'
FILA_TABS = f'<tr><td colspan="2">{TABS}</td></tr>'
HISTORIAL = (bloque(1), bloque(2), bloque(3, ANEXOS))
OCULTO_PREFIJO = '<tr><td><input type="hidden" name="h"></td><td></td></tr>'


def pagina(*filas):
    return '<html><body><form id="form1"><table>' + ''.join(filas) + '</table></form></body></html>'


def resultado(html, **opciones):
    """('rechazo', código, conteos) o ('ok', n, conteos); nunca depende de los indicadores."""
    conteos = {}
    try:
        actuaciones = parse_actuaciones(html, 'CASO_FICTICIO', estadisticas=conteos, **opciones)
    except ErrorParseoHistorial as error:
        return 'rechazo', error.codigo, conteos
    return 'ok', actuaciones, conteos


def indicadores(html):
    tipo, codigo, conteos = resultado(html)
    assert tipo == 'rechazo' and codigo is CodigoHistorial.BLOQUE_CON_CONTROLES
    return {k: v for k, v in conteos.items() if k in CLAVES_REGION_INTERACTIVA}


def directo(html):
    """Diagnóstico y reconocimiento sobre el árbol, sin pasar por el parser completo."""
    soup = BeautifulSoup(html, 'html.parser')
    tabla = soup.find('table')
    filas = modulo._filas_propias(tabla)
    prefijo, bloques = modulo._bloques(tabla)
    return (modulo._diagnostico_region_interactiva(soup, tabla, filas, prefijo, bloques),
            modulo._region_interactiva(soup, tabla, filas))


def todos_ok(d, hasta=7):
    return all(d.get(f'region_c{i}_ok') == 1 for i in range(1, hasta + 1))


# --- Prefijo frente a actuaciones históricas (la distinción pedida) -----------------------------------

def test_controles_antes_del_primer_separador_se_distinguen_de_los_de_las_actuaciones():
    d = indicadores(pagina(OCULTO_PREFIJO, *HISTORIAL, SEP, FILA_TABS))
    assert d['region_controles_fuera_en_prefijo'] == 1 and d['region_controles_fuera_en_actuaciones'] == 0
    assert d['region_controles_fuera_otros'] == 0
    assert d['region_c3_ok'] == 0 and d['region_c7_ok'] == 1  # el prefijo no entra en los bloques conservados
    assert [d[f'region_c{i}_ok'] for i in (1, 2, 4, 5, 6)] == [1] * 5


def test_controles_dentro_de_una_actuacion_historica():
    boton = '<tr><td>Campo :</td><td><button>x</button></td></tr>'
    d = indicadores(pagina(bloque(1), bloque(2, boton), bloque(3, ANEXOS), SEP, FILA_TABS))
    assert d['region_controles_fuera_en_actuaciones'] == 1 and d['region_controles_fuera_en_prefijo'] == 0
    assert d['region_c3_ok'] == 0 and d['region_c7_ok'] == 0
    assert d['region_bloques_con_controles_tras_quitar_fila'] == 1


def test_controles_en_prefijo_y_en_actuaciones_a_la_vez():
    d = indicadores(pagina(OCULTO_PREFIJO, bloque(1, '<tr><td>C :</td><td><input></td></tr>'), bloque(2), SEP, FILA_TABS))
    assert d['region_controles_fuera_en_prefijo'] == 1 and d['region_controles_fuera_en_actuaciones'] == 1


def test_los_controles_internos_de_la_region_se_cuentan_aparte():
    d = indicadores(pagina(bloque(1), bloque(2, '<tr><td>C :</td><td><input></td></tr>'), SEP, FILA_TABS))
    assert d['region_controles_dentro'] == 3 and d['region_textareas'] == 1 and d['region_envios'] == 1
    assert d['region_paneles'] == 2 and d['region_controles_fuera_en_actuaciones'] == 1


# --- Cada criterio, de forma independiente ------------------------------------------------------------

BOTON_AJENO = '<tr><td>C :</td><td><button>x</button></td></tr>'  # fuerza el rechazo por controles


def con_region(fila_region, *antes, **kw):
    return pagina(bloque(1), bloque(2, BOTON_AJENO), bloque(3, ANEXOS), *antes, SEP, fila_region)


def test_criterio_1_unicidad_tipo_y_ubicacion():
    dos = indicadores(pagina(bloque(1), bloque(2, BOTON_AJENO), SEP, FILA_TABS, SEP, FILA_TABS))
    assert dos['region_ids_tabs'] == 2 and dos['region_c1_ok'] == 0
    assert not any(k in dos for k in ('region_c2_ok', 'region_c3_ok', 'region_celdas_fila', 'region_es_div'))
    ninguno = indicadores(pagina(bloque(1), bloque(2, BOTON_AJENO)))
    assert ninguno['region_ids_tabs'] == 0 and ninguno['region_c1_ok'] == 0
    assert ninguno['region_controles_fuera_en_actuaciones'] == 1
    span = indicadores(pagina(bloque(1), bloque(2, BOTON_AJENO), SEP, FILA_TABS.replace('<div id="tabs">', '<span id="tabs">')
                              .replace('</div></td>', '</span></td>')))
    assert span['region_es_div'] == 0 and span['region_c1_ok'] == 0 and span['region_dentro_de_tabla'] == 1
    fuera = indicadores(pagina(bloque(1), bloque(2, BOTON_AJENO)).replace('</table>', '</table>' + TABS))
    assert fuera['region_dentro_de_tabla'] == 0 and fuera['region_c1_ok'] == 0


@pytest.mark.parametrize('fila,celdas,ajenos,texto', [
    (f'<tr><td>ETIQUETA_FICTICIA</td><td>{TABS}</td></tr>', 2, 0, 1),
    (f'<tr><td colspan="2">TEXTO_FICTICIO{TABS}</td></tr>', 1, 0, 1),
    (f'<tr><td colspan="2">{TABS}<script>$("#tabs").tabs();</script></td></tr>', 1, 1, 1),
    (f'<tr><td colspan="2">{TABS}<a href="x">e</a></td></tr>', 1, 1, 1),
    (f'<tr><td colspan="2"><div>{TABS}</div></td></tr>', 1, 1, 0),
    (f'<tr><td colspan="2"><p>{TABS}</p></td></tr>', 1, 1, 0),
    (f'<tr><td colspan="2"><!-- COMENTARIO_FICTICIO -->{TABS}</td></tr>', 1, 0, 1),
    (f'<tr><th colspan="2">{TABS}</th></tr>', 1, 1, 0),
], ids=['dos_celdas', 'texto', 'script', 'enlace', 'div_envolvente', 'p', 'comentario', 'th'])
def test_criterio_2_fila_exclusiva(fila, celdas, ajenos, texto):
    d = indicadores(con_region(fila))
    assert d['region_celdas_fila'] == celdas and d['region_c2_ok'] == 0
    assert d['region_elementos_ajenos_fila'] == ajenos and d['region_texto_ajeno_fila'] == texto


@pytest.mark.parametrize('region,t,e,p', [
    ('<div id="tabs"><div id="tabs-1"><select></select><button>x</button></div></div>', 0, 1, 1),
    ('<div id="tabs"><div id="tabs-1"><textarea></textarea></div></div>', 1, 0, 1),
    ('<div id="tabs"><textarea></textarea><button>x</button></div>', 1, 1, 0),
    ('<div id="tabs"><div id="panel1"><textarea></textarea><button>x</button></div></div>', 1, 1, 0),
    ('<div id="tabs"><div id="tabs-1"><textarea></textarea><a href="#">Guardar</a></div></div>', 1, 0, 1),
    ('<div id="tabs"><div id="tabs-1"><textarea></textarea><input type="text"></div></div>', 1, 0, 1),
    ('<div id="tabs"><div id="tabs-1"><textarea></textarea><input type="submit"></div></div>', 1, 1, 1),
], ids=['sin_textarea', 'sin_envio', 'sin_paneles', 'panel_no_reconocido', 'enlace_como_boton', 'input_texto', 'submit_ok'])
def test_criterio_3_region_reconocible(region, t, e, p):
    d = indicadores(pagina(bloque(1), bloque(2, BOTON_AJENO), SEP, f'<tr><td colspan="2">{region}</td></tr>'))
    assert (d['region_textareas'] >= 1, d['region_envios'] >= 1, d['region_paneles'] >= 1) == (bool(t), bool(e), bool(p))
    assert d['region_c3_ok'] == 0  # además hay un control ajeno


def test_criterio_3_solo_controles_dentro_cumple_aunque_el_conjunto_siga_fallando_por_otro_criterio():
    d = indicadores(pagina(*HISTORIAL, SEP, f'<tr><td colspan="2">{TABS}<script>x</script></td></tr>'))
    assert d['region_c3_ok'] == 1 and d['region_c2_ok'] == 0
    assert d['region_controles_fuera_en_actuaciones'] == d['region_controles_fuera_en_prefijo'] == 0


def test_criterio_4_gramatica_de_actuacion_dentro_de_la_region():
    interna = '<table id="tablaAnexos"><tr><td>D</td><td>' + ENLACE + '</td></tr></table>'
    fecha = '<table><tr><td>2020-05-05 10:00:00</td><td>R</td></tr></table>'
    for contenido, clave in ((interna, 'region_tablas_anexos_dentro'), (fecha, 'region_filas_fecha_dentro')):
        region = f'<div id="tabs"><div id="tabs-1">{contenido}<textarea></textarea><button>x</button></div></div>'
        d = indicadores(pagina(*HISTORIAL, SEP, f'<tr><td colspan="2">{region}</td></tr>'))
        assert d[clave] == 1 and d['region_c4_ok'] == 0 and d['region_c3_ok'] == 1


def test_criterio_5_filas_posteriores():
    d = indicadores(pagina(*HISTORIAL, SEP, FILA_TABS, '<tr><td colspan="2"><a href="x">Volver</a></td></tr>',
                           '<tr><td>NOTA</td><td>V</td></tr>', '<tr><td></td><td></td></tr>'))
    assert d['region_filas_posteriores_no_vacias'] == 2 and d['region_c5_ok'] == 0
    assert indicadores(pagina(bloque(1), bloque(2, BOTON_AJENO), SEP, FILA_TABS, SEP, '<tr><td></td><td></td></tr>'))[
        'region_filas_posteriores_no_vacias'] == 0


@pytest.mark.parametrize('previa,tipo', [
    ('<tr><td>Reparto :</td><td>V</td></tr>', 4),
    (ANEXOS, 3),
    ('<tr><td></td><td></td></tr>', 2),
    (SEP, 1),
], ids=['otra', 'anexos', 'vacia', 'separador'])
def test_criterio_6_tipo_de_la_fila_previa(previa, tipo):
    d = indicadores(pagina(bloque(1), bloque(2, BOTON_AJENO), bloque(3, previa), FILA_TABS))
    assert d['region_fila_previa_tipo'] == tipo and d['region_c6_ok'] == int(tipo != 4)


def test_criterio_6_sin_fila_previa_y_fila_previa_ancestro():
    inicial, _ = directo(f'<table><tr><td colspan="2">{TABS}</td></tr>{bloque(1)}</table>')
    assert inicial['region_fila_previa_tipo'] == 0 and inicial['region_c6_ok'] == 1
    anidada, _ = directo(f'<table>{bloque(1)}<tr><td>x</td><td>y</td><tr><td colspan="2">{TABS}</td></tr></table>')
    assert anidada['region_fila_previa_tipo'] == 5 and anidada['region_c6_ok'] == 0


def test_criterio_7_bloques_con_controles_tras_quitar_la_fila():
    d = indicadores(pagina(bloque(1, BOTON_AJENO), bloque(2, BOTON_AJENO), bloque(3), SEP, FILA_TABS))
    assert d['region_bloques_con_controles_tras_quitar_fila'] == 2 and d['region_c7_ok'] == 0


# --- Coherencia con la función real --------------------------------------------------------------------

CASOS = {
    'S1': pagina(*HISTORIAL, SEP, FILA_TABS),
    'S2': pagina(bloque(1), bloque(2), bloque(3, ANEXOS + FILA_TABS)),
    'S3': pagina(bloque(1), bloque(2), bloque(3, ANEXOS + f'<tr><td colspan="2"><table><tr><td>{TABS}</td></tr></table></td></tr>')),
    'prefijo': pagina(OCULTO_PREFIJO, *HISTORIAL, SEP, FILA_TABS),
    'control_en_actuacion': con_region(FILA_TABS),
    'script_ajeno': pagina(*HISTORIAL, SEP, f'<tr><td colspan="2">{TABS}<script>x</script></td></tr>'),
    'dos_celdas': pagina(*HISTORIAL, SEP, f'<tr><td>x</td><td>{TABS}</td></tr>'),
    'fila_posterior': pagina(*HISTORIAL, SEP, FILA_TABS, '<tr><td>NOTA</td><td>V</td></tr>'),
    'previa_otra': pagina(bloque(1), bloque(2), bloque(3, '<tr><td>Campo :</td><td>V</td></tr>' + FILA_TABS)),
    'sin_paneles': pagina(*HISTORIAL, SEP, '<tr><td colspan="2"><div id="tabs"><textarea></textarea><button>x</button></div></td></tr>'),
    'dos_tabs': pagina(*HISTORIAL, SEP, FILA_TABS, SEP, FILA_TABS),
    'anexos_de_formulario': pagina(*HISTORIAL, SEP, '<tr><td colspan="2"><div id="tabs">' + PANELES + '<div id="tabs-4">'
                                   '<table id="tablaAnexos"><tr><th>D</th></tr><tr><td><input type="file"></td></tr></table>'
                                   '</div></div></td></tr>'),
    'anexos_con_enlace_en_region': pagina(*HISTORIAL, SEP, '<tr><td colspan="2"><div id="tabs">' + PANELES + '<div id="tabs-4">'
                                          '<table id="tablaAnexos"><tr><td>D</td><td>' + ENLACE + '</td></tr></table>'
                                          '</div></div></td></tr>'),
    'anexos_con_fila_de_texto_en_region': pagina(*HISTORIAL, SEP, '<tr><td colspan="2"><div id="tabs">' + PANELES + '<div id="tabs-4">'
                                                 '<table id="tablaAnexos"><tr><td>D</td><td></td></tr></table>'
                                                 '</div></div></td></tr>'),
    'en_contenido': pagina(bloque(1), bloque(2, f'<tr><td>Reparto :</td><td>V{TABS}</td></tr>'), bloque(3, ANEXOS)),
}


@pytest.mark.parametrize('html', CASOS.values(), ids=CASOS.keys())
def test_los_criterios_1_a_6_coinciden_con_el_reconocimiento_real(html):
    d, region = directo(html)
    assert (region is not None) == todos_ok(d, hasta=6)


@pytest.mark.parametrize('html', CASOS.values(), ids=CASOS.keys())
def test_los_indicadores_no_cambian_el_resultado_del_parser(html, monkeypatch):
    con = resultado(html)
    monkeypatch.setattr(modulo, '_diagnostico_region_interactiva', lambda *args: {})
    sin = resultado(html)
    assert con[0] == sin[0]
    if con[0] == 'rechazo':
        assert con[1] is sin[1]
    else:
        assert con[1] == sin[1]
    base = {k: v for k, v in con[2].items() if k not in CLAVES_REGION_INTERACTIVA}
    assert base == sin[2]


def test_un_fallo_inesperado_del_diagnostico_no_cambia_el_codigo(monkeypatch):
    def falla(*args):
        raise RuntimeError('fallo_ficticio')
    monkeypatch.setattr(modulo, '_diagnostico_region_interactiva', falla)
    tipo, codigo, conteos = resultado(CASOS['control_en_actuacion'])
    assert tipo == 'rechazo' and codigo is CodigoHistorial.BLOQUE_CON_CONTROLES
    assert not any(k in conteos for k in CLAVES_REGION_INTERACTIVA)


# --- Cuándo aparecen ---------------------------------------------------------------------------------------

def claves_region(conteos):
    return [k for k in conteos if k in CLAVES_REGION_INTERACTIVA]


def test_no_aparecen_si_se_acepta_ni_si_la_region_se_excluye():
    for nombre in ('S1', 'S2', 'S3'):
        tipo, _, conteos = resultado(CASOS[nombre])
        assert tipo == 'ok' and conteos['regiones_interactivas_excluidas'] == 1 and not claves_region(conteos)
    tipo, _, conteos = resultado(pagina(*HISTORIAL))
    assert tipo == 'ok' and not claves_region(conteos)


def test_no_aparecen_con_otros_codigos_de_rechazo():
    for html, codigo in (
        (pagina(bloque(1), SEP + '<tr><td>2020-01-05 10:00:00</td><td>R</td></tr>'), CodigoHistorial.SIN_CONTENIDO),
        (pagina(bloque(1, '<tr><td>Anexos :</td><td><table id="tablaAnexos"><tr><td>solo</td></tr></table></td></tr>')),
         CodigoHistorial.ANEXO_FILA_INVALIDA),
        (pagina(bloque(1, '<tr><td>2020-01-09 10:00:00</td><td>R</td></tr>')), CodigoHistorial.SEPARADOR_AUSENTE),
    ):
        tipo, rechazo, conteos = resultado(html)
        assert tipo == 'rechazo' and rechazo is codigo and not claves_region(conteos)
        assert rechazo is not CodigoHistorial.BLOQUE_CON_CONTROLES


def test_no_aparecen_con_contenedor_explicito():
    html = CASOS['control_en_actuacion'].replace('<table>', '<table id="historial_ficticio">', 1)
    tipo, codigo, conteos = resultado(html, contenedor_id='historial_ficticio')
    assert tipo == 'rechazo' and codigo is CodigoHistorial.BLOQUE_CON_CONTROLES and not claves_region(conteos)


def test_aparecen_cuando_la_region_no_se_reconoce():
    assert claves_region(resultado(CASOS['control_en_actuacion'])[2])
    assert claves_region(resultado(CASOS['script_ajeno'])[2])


# --- Seguridad de la salida -----------------------------------------------------------------------------------

def test_solo_enteros_no_negativos_de_la_lista_cerrada_y_sin_contenido():
    conteos = resultado(CASOS['control_en_actuacion'])[2]
    salida = diagnostico_seguro(CodigoHistorial.BLOQUE_CON_CONTROLES, conteos)['estadisticas_estructurales']
    region = {k: v for k, v in salida.items() if k.startswith('region_')}
    assert region and set(region) <= set(CLAVES_REGION_INTERACTIVA) <= set(CLAVES_CONTEOS)
    assert all(type(v) is int and v >= 0 for v in salida.values())
    texto = json.dumps(salida)
    for secreto in ('CONTENIDO_FICTICIO', 'RESPONSABLE_FICTICIO', 'TITULO_', 'ANEXO_FICTICIO', 'REFERENCIA', 'Guardar', 'Actuar', 'tabs-1'):
        assert secreto not in texto
    assert set(salida) <= set(CLAVES_CONTEOS)


def test_un_valor_no_determinable_se_omite_y_no_se_sustituye_por_cero():
    d = indicadores(pagina(bloque(1), bloque(2, BOTON_AJENO), SEP, FILA_TABS, SEP, FILA_TABS))
    assert d['region_ids_tabs'] == 2
    for clave in ('region_c2_ok', 'region_c3_ok', 'region_c4_ok', 'region_c5_ok', 'region_c6_ok', 'region_c7_ok',
                  'region_celdas_fila', 'region_fila_previa_tipo', 'region_textareas'):
        assert clave not in d
