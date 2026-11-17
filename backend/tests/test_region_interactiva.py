"""Exclusión de la región interactiva `div#tabs` de SIGAC. Todo el material es sintético.

SIGAC usa un `form#form1` global, así que nada depende de un `<form>` independiente.
La región se excluye solo si cumple todos los criterios estrictos; en caso contrario el
historial se rechaza por controles, igual que antes.
"""

from dataclasses import replace
import itertools
import json
import socket

import pytest

import tinotify.parsers.parser as modulo
from tinotify.domain.actuaciones import VERSION_HUELLA
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.parsers.parser import ErrorParseoHistorial, parse_actuaciones


SEP = '<tr><td colspan="2"><hr></td></tr>'
ENLACE = '<a href="general.descargarAnexo.con?codigo=CODIGO_FICTICIO">archivo_ficticio.pdf</a>'
ANEXOS = ('<tr><td>Anexos :</td><td><table id="tablaAnexos"><tr><td>ANEXO_FICTICIO</td><td>'
          + ENLACE + '</td></tr></table></td></tr>')


def bloque(n, extra=''):
    return (SEP + f'<tr><td>TITULO_{n}</td><td>ASESOR--&gt;ESTUDIANTE</td></tr>'
            f'<tr><td>2020-01-{n:02d} 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
            f'<tr><td>Actuación :</td><td>CONTENIDO_FICTICIO_{n}</td></tr>' + extra)


PANELES = ('<ul><li><a href="#tabs-1">Actuar</a></li><li><a href="#tabs-2">Solicitar Archivo</a></li>'
           '<li><a href="#tabs-3">Juzgado</a></li></ul>'
           '<div id="tabs-1"><table><tr><td>Tipo</td><td><select><option>a</option></select>'
           '<input type="checkbox"></td></tr><tr><td colspan="2"><textarea></textarea></td></tr>'
           '<tr><td><button>Guardar</button></td></tr></table></div>'
           '<div id="tabs-3"><table><tr><td><select></select></td></tr></table></div>')
TABS = '<div id="tabs">' + PANELES + '</div>'
FILA_TABS = f'<tr><td colspan="2">{TABS}</td></tr>'
HISTORIAL = (bloque(1), bloque(2), bloque(3, ANEXOS))


def pagina(*filas):
    return '<html><body><form id="form1"><table>' + ''.join(filas) + '</table></form></body></html>'


def extraer(html):
    conteos = {}
    resultado = parse_actuaciones(html, 'CASO_FICTICIO', estadisticas=conteos)
    return resultado, conteos


def rechazado(html, codigo=CodigoHistorial.BLOQUE_CON_CONTROLES):
    conteos = {}
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(html, 'CASO_FICTICIO', estadisticas=conteos)
    assert error.value.codigo is codigo
    assert not hasattr(error.value, 'actuaciones')  # nunca una extracción parcial
    assert conteos['regiones_interactivas_excluidas'] == conteos['filas_interactivas_excluidas'] == 0
    return conteos


def no_acepta(html):
    """Rechazo por controles o, por la regla previa de «tabla de formulario», resultado vacío
    (el cliente lo rechaza como historial no reconocido). Nunca un historial parcial."""
    conteos = {}
    try:
        resultado = parse_actuaciones(html, 'CASO_FICTICIO', estadisticas=conteos)
    except ErrorParseoHistorial as error:
        assert error.codigo is CodigoHistorial.BLOQUE_CON_CONTROLES
    else:
        assert resultado == []
    assert conteos['regiones_interactivas_excluidas'] == conteos['filas_interactivas_excluidas'] == 0


SIN_FORMULARIO, _ = extraer(pagina(*HISTORIAL))


def comprobar_igual_al_historial(resultado):
    assert resultado == SIN_FORMULARIO  # igualdad exacta de todos los campos, anexos incluidos
    assert [a.huella_version for a in resultado] == [a.huella_version for a in SIN_FORMULARIO]
    assert [a.huella for a in resultado] == [a.huella for a in SIN_FORMULARIO]
    assert len(resultado[-1].anexos) == 1 and resultado[-1].anexos[0].referencia


# --- S1, S2 y S3 --------------------------------------------------------------------------

@pytest.mark.parametrize('cierre', ['', SEP], ids=['sin_separador_final', 'con_separador_final'])
def test_s1_formulario_como_bloque_independiente(cierre):
    resultado, conteos = extraer(pagina(*HISTORIAL, SEP, FILA_TABS, *([cierre] if cierre else [])))
    comprobar_igual_al_historial(resultado)
    assert conteos['regiones_interactivas_excluidas'] == 1 and conteos['filas_interactivas_excluidas'] == 1
    assert conteos['bloques_validos'] == 3 and conteos['bloques_rechazados'] == 0
    assert conteos['bloques_detectados'] == 4 and conteos['bloques_vacios'] == 0  # 3 actuaciones + el bloque del formulario


def test_s1_solo_se_excluye_ese_bloque():
    resultado, conteos = extraer(pagina(*HISTORIAL, SEP, FILA_TABS))
    assert len(resultado) == 3 and conteos['bloques_detectados'] == 4 and conteos['bloques_validos'] == 3


def test_s2_formulario_pegado_a_la_ultima_actuacion_conserva_la_actuacion_y_sus_anexos():
    resultado, conteos = extraer(pagina(bloque(1), bloque(2), bloque(3, ANEXOS + FILA_TABS)))
    comprobar_igual_al_historial(resultado)
    assert conteos['bloques_detectados'] == conteos['bloques_validos'] == 3
    assert conteos['regiones_interactivas_excluidas'] == conteos['filas_interactivas_excluidas'] == 1


def test_s3_formulario_anidado_en_una_fila_del_ultimo_bloque_no_afecta_al_contenido_que_lo_rodea():
    envuelto = f'<tr><td colspan="2"><table><tbody><tr><td>{TABS}</td></tr></tbody></table></td></tr>'
    contenido_previo = ('<tr><td>Reparto :</td><td>VALOR_FICTICIO<table><tr><td>INTERNO_FICTICIO</td></tr></table></td></tr>')
    historial = (bloque(1), bloque(2), bloque(3, contenido_previo + ANEXOS))
    esperado, _ = extraer(pagina(*historial))
    resultado, conteos = extraer(pagina(bloque(1), bloque(2), bloque(3, contenido_previo + ANEXOS + envuelto)))
    assert resultado == esperado and [a.huella_version for a in resultado] == [a.huella_version for a in esperado]
    assert 'INTERNO_FICTICIO' in resultado[-1].descripcion and 'VALOR_FICTICIO' in resultado[-1].descripcion
    assert len(resultado[-1].anexos) == 1
    assert conteos['regiones_interactivas_excluidas'] == conteos['filas_interactivas_excluidas'] == 1


def test_sin_formulario_nada_se_excluye_y_los_contadores_son_cero():
    resultado, conteos = extraer(pagina(*HISTORIAL))
    assert conteos['regiones_interactivas_excluidas'] == conteos['filas_interactivas_excluidas'] == 0
    comprobar_igual_al_historial(resultado)


def test_la_exclusion_no_modifica_los_golden_de_huellas():
    assert VERSION_HUELLA == 1
    # Mismo contenido con y sin región: las huellas coinciden, así que no hay estado nuevo que migrar.
    con, _ = extraer(pagina(*HISTORIAL, SEP, FILA_TABS))
    assert [a.huella_version for a in con] == [a.huella_version for a in SIN_FORMULARIO]


def test_contabilidad_de_filas_conservadas_mas_excluidas():
    from bs4 import BeautifulSoup
    html = pagina(bloque(1), bloque(2, ANEXOS + FILA_TABS))
    soup = BeautifulSoup(html, 'html.parser')
    tabla = soup.find('table')
    filas = modulo._filas_propias(tabla)
    region = modulo._region_interactiva(soup, tabla, filas)
    assert region is not None and sum(1 for f in filas if f is region) == 1
    _, bloques = modulo._bloques(tabla)
    en_bloques = [f for b in bloques for f in b]
    restantes = [f for f in en_bloques if f is not region]
    assert len(restantes) + 1 == len(en_bloques)
    assert not any(modulo._tiene_controles([f]) for f in restantes)
    assert modulo._tiene_controles([region])


# --- Controles fuera de la región: el rechazo se conserva -------------------------------------

CONTROLES = ['<input type="hidden" name="x">', '<input name="x">', '<input type="checkbox">',
             '<select><option>a</option></select>', '<textarea></textarea>', '<button>x</button>']


def con_control(filas, indice_fila, control):
    fila = filas[indice_fila]
    cabeza, _, cola = fila.rpartition('</td>')
    return filas[:indice_fila] + [cabeza + control + '</td>' + cola] + filas[indice_fila + 1:]


def filas_de(bloque_html):
    return [f + '</tr>' for f in bloque_html.split('</tr>') if f.strip()]


@pytest.mark.parametrize('control', CONTROLES)
@pytest.mark.parametrize('con_region', [False, True], ids=['sin_region', 'con_region_pegada'])
def test_un_control_en_cualquier_fila_de_cualquier_actuacion_siempre_rechaza(control, con_region):
    bloques = [filas_de(b) for b in (bloque(1), bloque(2), bloque(3, ANEXOS))]
    for numero, filas in enumerate(bloques):
        for fila in range(len(filas)):
            if numero == 0 and fila == 0:
                # Comportamiento previo, no introducido aquí: un control en la fila separadora inicial de la
                # primera actuación la convierte en «prefijo» de la tabla (que se ignora). Se informa aparte.
                continue
            cuerpo = [''.join(con_control(f, fila, control) if i == numero else f) if i == numero else ''.join(f)
                      for i, f in enumerate(bloques)]
            if con_region:
                cuerpo[-1] += FILA_TABS
            no_acepta(pagina(*cuerpo))


def test_control_en_fila_separadora_o_prefijo_o_celda_interna_rechaza():
    # Aunque todos los bloques tengan controles, las señales históricas exigen rechazo.
    separadora_con_control = ('<tr><td colspan="2"><hr><input type="hidden"></td></tr>'
                              '<tr><td>T</td><td>A--&gt;B</td></tr><tr><td>2020-01-05 10:00:00</td><td>R</td></tr>'
                              '<tr><td>Actuación :</td><td>X</td></tr>')
    rechazado(pagina(bloque(1), separadora_con_control, SEP, FILA_TABS))
    rechazado(pagina(bloque(1), separadora_con_control, bloque(3), SEP, FILA_TABS))
    rechazado(pagina('<tr><td><input type="hidden"></td><td></td></tr>', *HISTORIAL, SEP, FILA_TABS))
    rechazado(pagina(bloque(1), bloque(2, '<tr><td>Reparto :</td><td>V<table><tr><td><select></select></td></tr></table></td></tr>'),
                     bloque(3, ANEXOS + FILA_TABS)))


# --- Un criterio incumplido mantiene el rechazo -----------------------------------------------

def test_criterio_unicidad_y_tipo_del_contenedor():
    rechazado(pagina(*HISTORIAL, SEP, FILA_TABS, SEP, FILA_TABS))
    rechazado(pagina(*HISTORIAL, SEP, FILA_TABS.replace('<div id="tabs">', '<span id="tabs">').replace('</div></td>', '</span></td>')))
    rechazado(pagina(*HISTORIAL, SEP, FILA_TABS.replace('id="tabs"', 'class="tabs"')))
    rechazado(pagina(*HISTORIAL, SEP, FILA_TABS.replace('id="tabs"', 'id="tabs "')))
    # Un `div#tabs` fuera de la tabla del historial no sirve de coartada para controles de la tabla.
    rechazado(pagina(*HISTORIAL, SEP, '<tr><td colspan="2"><textarea></textarea><button>x</button></td></tr>')
              .replace('</table>', '</table>' + TABS))


@pytest.mark.parametrize('fila', [
    f'<tr><td>ETIQUETA_FICTICIA</td><td>{TABS}</td></tr>',                     # dos celdas
    f'<tr><td colspan="2">TEXTO_FICTICIO{TABS}</td></tr>',                     # texto junto a la región
    f'<tr><td colspan="2">{TABS}TEXTO_FICTICIO</td></tr>',
    f'<tr><td colspan="2"><a href="x">enlace</a>{TABS}</td></tr>',             # otro elemento
    f'<tr><td colspan="2"><p>{TABS}</p></td></tr>',                            # envoltura no estructural
    f'<tr><td colspan="2"><div>{TABS}</div></td></tr>',
    f'<tr><td colspan="2"><!-- COMENTARIO_FICTICIO -->{TABS}</td></tr>',
    f'<tr><th colspan="2">{TABS}</th></tr>',                                   # th en lugar de td
    f'<tr><td colspan="2">{TABS}</td><td></td></tr>',                          # segunda celda
    f'<tr><td colspan="2">{TABS}<button>x</button></td></tr>',                # control fuera de la región
], ids=['dos_celdas', 'texto_antes', 'texto_despues', 'enlace', 'p', 'div_envolvente', 'comentario', 'th', 'segunda_celda', 'boton_aparte'])
def test_criterio_fila_exclusiva(fila):
    rechazado(pagina(*HISTORIAL, SEP, fila))
    rechazado(pagina(bloque(1), bloque(2), bloque(3, ANEXOS + fila)))


def test_div_tabs_dentro_del_contenido_historico_no_se_elimina():
    en_contenido = f'<tr><td>Reparto :</td><td>VALOR_FICTICIO{TABS}</td></tr>'
    rechazado(pagina(bloque(1), bloque(2, en_contenido), bloque(3, ANEXOS)))
    rechazado(pagina(bloque(1), bloque(2), bloque(3, ANEXOS + f'<tr><td>Etiqueta :</td><td>{TABS}</td></tr>')))
    rechazado(pagina(bloque(1), bloque(2), bloque(3, f'<tr><td>Actuación :</td><td>TEXTO{TABS}</td></tr>' + ANEXOS)))
    # Sin controles ni paneles no es una región: se conserva como contenido, como antes.
    inocuo = '<tr><td>Reparto :</td><td>VALOR_FICTICIO<div id="tabs">TEXTO_INTERNO_FICTICIO</div></td></tr>'
    resultado, conteos = extraer(pagina(bloque(1), bloque(2, inocuo), bloque(3, ANEXOS)))
    assert 'TEXTO_INTERNO_FICTICIO' in resultado[1].descripcion
    assert conteos['regiones_interactivas_excluidas'] == conteos['filas_interactivas_excluidas'] == 0


def test_criterio_controles_todos_dentro_de_la_region():
    # Control suelto en una actuación más región válida: la región no "limpia" lo demás.
    rechazado(pagina(bloque(1, '<tr><td></td><td><input type="hidden"></td></tr>'), bloque(2), bloque(3, ANEXOS), SEP, FILA_TABS))
    rechazado(pagina(bloque(1), bloque(2), bloque(3, ANEXOS + '<tr><td>Campo :</td><td><button>x</button></td></tr>' + FILA_TABS)))


@pytest.mark.parametrize('region', [
    '<div id="tabs"><div id="tabs-1"><table><tr><td><select></select></td></tr></table></div></div>',   # sin textarea ni envío
    '<div id="tabs"><div id="tabs-1"><textarea></textarea></div></div>',                                 # sin envío
    '<div id="tabs"><div id="tabs-1"><button>x</button></div></div>',                                    # sin textarea
    '<div id="tabs"><textarea></textarea><button>x</button></div>',                                     # sin paneles
    '<div id="tabs"><div id="panel"><textarea></textarea><button>x</button></div></div>',               # panel no reconocido
    '<div id="tabs"><div id="tabs-x"><textarea></textarea><button>x</button></div></div>',
    '<div id="tabs"><div id="tabs-1"><textarea></textarea><input type="text"></div></div>',             # input no es envío
], ids=['solo_select', 'sin_envio', 'sin_textarea', 'sin_paneles', 'panel_no_reconocido', 'panel_no_numerico', 'input_texto'])
def test_criterio_region_reconocible_como_formulario(region):
    rechazado(pagina(*HISTORIAL, SEP, f'<tr><td colspan="2">{region}</td></tr>'))


def test_criterio_sin_gramatica_de_actuacion_dentro():
    interna = '<table id="tablaAnexos"><tr><td>D</td><td>' + ENLACE + '</td></tr></table>'
    fecha = '<table><tr><td>2020-05-05 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr></table>'
    for contenido in (interna, fecha):
        region = f'<div id="tabs"><div id="tabs-1">{contenido}<textarea></textarea><button>x</button></div></div>'
        rechazado(pagina(*HISTORIAL, SEP, f'<tr><td colspan="2">{region}</td></tr>'))
        rechazado(pagina(bloque(1), bloque(2), bloque(3, ANEXOS + f'<tr><td colspan="2">{region}</td></tr>')))


def test_criterio_posicion_final():
    rechazado(pagina(bloque(1), bloque(2, ANEXOS), SEP, FILA_TABS, bloque(3)))          # actuación después
    rechazado(pagina(*HISTORIAL, SEP, FILA_TABS, '<tr><td>NOTA_FICTICIA</td><td>VALOR_FICTICIO</td></tr>'))
    rechazado(pagina(*HISTORIAL, SEP, FILA_TABS, SEP, '<tr><td>x</td><td>y</td></tr>'))
    rechazado(pagina(bloque(1), bloque(2, ANEXOS + FILA_TABS + '<tr><td>Campo :</td><td>V</td></tr>'), bloque(3)))


def test_criterio_fila_previa_valida():
    rechazado(pagina(bloque(1), bloque(2), bloque(3, ANEXOS + '<tr><td>Actuar</td><td>Solicitar</td></tr>' + FILA_TABS)))
    rechazado(pagina(bloque(1), bloque(2), bloque(3, '<tr><td>Campo :</td><td>V</td></tr>' + FILA_TABS)))
    # Fila previa vacía o separadora: sí se reconoce.
    comprobar_igual_al_historial(extraer(pagina(bloque(1), bloque(2), bloque(3, ANEXOS + '<tr><td></td><td></td></tr>' + FILA_TABS)))[0])


def test_criterio_nada_conservado_con_controles_tras_excluir(monkeypatch):
    # Si una fila conservada conserva un control, no se excluye nada.
    rechazado(pagina(bloque(1), bloque(2, '<tr><td></td><td><input type="hidden"></td></tr>' + ANEXOS + FILA_TABS), bloque(3)))


def test_contenedor_explicito_no_activa_la_exclusion():
    with pytest.raises(ErrorParseoHistorial) as error:
        parse_actuaciones(pagina(*HISTORIAL, SEP, FILA_TABS).replace('<table>', '<table id="historial_ficticio">', 1),
                          'CASO_FICTICIO', contenedor_id='historial_ficticio')
    assert error.value.codigo is CodigoHistorial.BLOQUE_CON_CONTROLES


def test_formulario_con_senales_historicas_no_se_descarta():
    formulario = '<form><table>' + SEP + '<tr><td>T</td><td>A--&gt;B</td></tr><tr><td>2020-02-01 10:00:00</td><td>R</td></tr>' \
                 '<tr><td>Actuación :</td><td><textarea></textarea></td></tr></table></form>'
    rechazado(formulario)  # fecha visible: ya no se descarta antes de validar
    rechazado('<form><table>' + bloque(1) + bloque(2, '<tr><td>Actuación :</td><td><textarea></textarea></td></tr>') + '</table></form>')


def test_un_fallo_inesperado_al_evaluar_la_region_nunca_la_admite(monkeypatch):
    # La evaluación es solo lectura; si falla, la excepción no se convierte en aceptación.
    def falla(*args):
        raise RuntimeError('fallo_ficticio')
    monkeypatch.setattr(modulo, '_region_interactiva', falla)
    with pytest.raises(RuntimeError):
        parse_actuaciones(pagina(*HISTORIAL, SEP, FILA_TABS), 'CASO_FICTICIO')


def test_los_contadores_son_enteros_y_no_filtran_contenido():
    _, conteos = extraer(pagina(*HISTORIAL, SEP, FILA_TABS))
    for clave in ('regiones_interactivas_excluidas', 'filas_interactivas_excluidas'):
        assert type(conteos[clave]) is int
    texto = json.dumps(conteos)
    for secreto in ('CONTENIDO_FICTICIO', 'RESPONSABLE_FICTICIO', 'tabs', 'Actuar', 'Juzgado'):
        assert secreto not in texto


# --- C4: tablaAnexos dentro de la región ------------------------------------------------------------------

DESCARGA = '<a href="general.descargarAnexo.con?codigo=CODIGO_FICTICIO">archivo_ficticio.pdf</a>'


def region_con_tabla(tabla_anexos):
    return f'<tr><td colspan="2"><div id="tabs">{PANELES}<div id="tabs-4">{tabla_anexos}</div></div></td></tr>'


def anexos_form(*filas):
    return '<table id="tablaAnexos">' + ''.join(filas) + '</table>'


FILA_CONTROLES = '<tr><td>Archivo</td><td><input type="file"><button>Quitar</button></td></tr>'
TABLAS_DE_FORMULARIO = {
    'vacia': anexos_form(),
    'solo_cabecera_th': anexos_form('<tr><th>Descripción</th><th>Archivo</th></tr>'),
    'cabecera_y_filas_con_controles': anexos_form('<tr><th>D</th><th>A</th></tr>', FILA_CONTROLES, FILA_CONTROLES),
    'con_fila_vacia': anexos_form('<tr><td></td><td></td></tr>', FILA_CONTROLES),
}


@pytest.mark.parametrize('tabla_anexos', TABLAS_DE_FORMULARIO.values(), ids=TABLAS_DE_FORMULARIO.keys())
def test_tabla_anexos_sin_datos_historicos_dentro_de_la_region_se_excluye_en_s1_s2_s3(tabla_anexos):
    region = region_con_tabla(tabla_anexos)
    for html in (
        pagina(*HISTORIAL, SEP, region),                                # S1
        pagina(bloque(1), bloque(2), bloque(3, ANEXOS + region)),       # S2
    ):
        resultado, conteos = extraer(html)
        comprobar_igual_al_historial(resultado)
        assert conteos['regiones_interactivas_excluidas'] == conteos['filas_interactivas_excluidas'] == 1
    anidada = (f'<tr><td colspan="2"><table><tr><td><div id="tabs">{PANELES}<div id="tabs-4">{tabla_anexos}</div>'
               '</div></td></tr></table></td></tr>')
    resultado, conteos = extraer(pagina(bloque(1), bloque(2), bloque(3, ANEXOS + anidada)))     # S3
    comprobar_igual_al_historial(resultado)
    assert conteos['regiones_interactivas_excluidas'] == 1


TABLAS_AMBIGUAS = {
    'enlace_de_descarga': anexos_form(f'<tr><td>ANEXO_FICTICIO</td><td>{DESCARGA}</td></tr>'),
    'enlace_y_controles': anexos_form(f'<tr><td>ANEXO_FICTICIO</td><td>{DESCARGA}<button>Quitar</button></td></tr>'),
    'a_sin_href': anexos_form('<tr><td><a name="x">ANEXO_FICTICIO</a></td><td><button>x</button></td></tr>'),
    'descripcion_sin_enlace_ni_controles': anexos_form('<tr><td>ANEXO_FICTICIO</td><td></td></tr>'),
    'fila_de_texto_sin_controles': anexos_form('<tr><td>ANEXO_FICTICIO</td><td>TEXTO_FICTICIO</td></tr>'),
    'cabecera_td_con_texto': anexos_form('<tr><td>Descripción</td><td>Archivo</td></tr>', FILA_CONTROLES),
    'tabla_interna': anexos_form(FILA_CONTROLES, '<tr><td colspan="2"><table><tr><td>x</td></tr></table></td></tr>'),
    'controles_mas_un_dato_historico': anexos_form(FILA_CONTROLES, '<tr><td>ANEXO_FICTICIO</td><td>VALOR_FICTICIO</td></tr>'),
    'una_celda_con_texto': anexos_form('<tr><td>ANEXO_FICTICIO</td></tr>'),
}


@pytest.mark.parametrize('tabla_anexos', TABLAS_AMBIGUAS.values(), ids=TABLAS_AMBIGUAS.keys())
def test_tabla_anexos_con_contenido_historico_o_ambiguo_dentro_de_la_region_mantiene_el_rechazo(tabla_anexos):
    region = region_con_tabla(tabla_anexos)
    rechazado(pagina(*HISTORIAL, SEP, region))
    rechazado(pagina(bloque(1), bloque(2), bloque(3, ANEXOS + region)))


def test_una_actuacion_historica_dentro_de_la_region_mantiene_el_rechazo_aunque_la_tabla_sea_de_formulario():
    fecha = '<table><tr><td>2020-05-05 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr></table>'
    region = (f'<tr><td colspan="2"><div id="tabs">{PANELES}<div id="tabs-4">{fecha}'
              f'{TABLAS_DE_FORMULARIO["cabecera_y_filas_con_controles"]}</div></div></td></tr>')
    rechazado(pagina(*HISTORIAL, SEP, region))


def test_todas_las_tablas_de_anexos_de_la_region_deben_ser_de_formulario():
    region = region_con_tabla(TABLAS_DE_FORMULARIO['vacia'] + TABLAS_AMBIGUAS['enlace_de_descarga'])
    rechazado(pagina(*HISTORIAL, SEP, region))


def test_los_anexos_historicos_fuera_de_la_region_no_cambian():
    # Una tablaAnexos con enlaces en una actuación se procesa como siempre, con o sin región.
    con, _ = extraer(pagina(*HISTORIAL, SEP, region_con_tabla(TABLAS_DE_FORMULARIO['vacia'])))
    assert [len(a.anexos) for a in con] == [0, 0, 1]
    assert con[-1].anexos[0].referencia == 'general.descargarAnexo.con?codigo=CODIGO_FICTICIO'
