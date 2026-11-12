from tinotify.parsers.parser import parse_actuaciones

HTML = '''<table>
<tr><td colspan="2"><hr/></td></tr>
<tr><td style="color:red"><strong>Pendiente Firma Poder</strong></td><td style="color:red"><strong>ASESOR-->ESTUDIANTE</strong></td></tr>
<tr><td><strong>2026-11-04 21:59:39</strong></td><td><strong>ASESOR DE PRUEBA</strong></td></tr>
<tr><td align="right">Actuación :</td><td>Saludos:<br/><br/>Recuerda la anotación anterior.</td></tr>
<tr><td colspan="2"><hr/></td></tr>
<tr><td><strong>Pendiente Firma Poder</strong></td><td><strong>ASESOR-->ESTUDIANTE</strong></td></tr>
<tr><td><strong>2026-11-10 19:55:33</strong></td><td><strong>ASESOR DE PRUEBA</strong></td></tr>
<tr><td>Actuación :</td><td>Por favor revisa el caso.</td></tr>
</table>'''

def test_extract():
    rows = parse_actuaciones(HTML, 'CASO-DE-PRUEBA')
    assert len(rows) == 2
    assert rows[0].descripcion == 'Saludos:\nRecuerda la anotación anterior.'
    assert rows[1].destino == 'ESTUDIANTE'
    assert rows[0].huella != rows[1].huella
    assert parse_actuaciones(HTML, 'CASO-DE-PRUEBA') == rows
