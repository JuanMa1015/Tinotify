from pathlib import Path
from parser import parse_actuaciones


def test_actuacion_con_anexo():
    html = Path(__file__).with_name('caso_prueba.html').read_text(encoding='utf-8')
    actuaciones = parse_actuaciones(html, 'CASO_FICTICIO')
    assert len(actuaciones) == 1
    act = actuaciones[0]
    assert act.origen == 'ESTUDIANTE'
    assert act.destino == 'ASESOR'
    assert len(act.anexos) == 1
    assert act.anexos[0].descripcion == 'Documento de prueba'
    assert act.anexos[0].archivo == 'documento_prueba.png'
    assert 'CODIGO_FICTICIO_NO_VALIDO' in act.anexos[0].referencia


def test_anexo_no_cambia_huella_de_actuacion():
    html = Path(__file__).with_name('caso_prueba.html').read_text(encoding='utf-8')
    sin_anexo = html.split('<tr>\n    <td align="right" valign="top">Anexos :')[0] + '</table></body></html>'
    assert parse_actuaciones(html, 'CASO_FICTICIO')[0].huella == parse_actuaciones(sin_anexo, 'CASO_FICTICIO')[0].huella
