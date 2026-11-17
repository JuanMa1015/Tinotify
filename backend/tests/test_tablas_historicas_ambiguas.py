"""Clasificación conservadora de tablas omitidas: únicamente fixtures sintéticas."""

import socket

import pytest

from backend.tests.helpers.sigac_detalle import detalle
from backend.tests.test_auditoria_completitud_sigac import A, B, leer, documento
from tinotify.integrations.sigac.lectura_validada import _resolver_lectura
from tinotify.integrations.sigac.sigac_client import SigacClientError
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.parsers.parser import parse_actuaciones


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('No se permite red real')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)


@pytest.mark.parametrize('contenido', [
    '<table><tr><td>Fecha</td><td>2020-01-01 10:00:00</td></tr>'
    '<tr><td>Responsable</td><td>REFERENCIA SINTETICA</td></tr>'
    '<tr><td>Título</td><td>Resumen de una actuación anterior</td></tr></table>',
    '<table><tr><th>Fecha</th><th>Responsable</th><th>Título</th></tr>'
    '<tr><td>2020-01-01 10:00:00</td><td>REFERENCIA SINTETICA</td><td>Resumen</td></tr></table>',
    '<table><tr><td>Nota</td><td>El texto menciona 2020-01-01 y un responsable.</td></tr></table>',
])
def test_presentacion_y_menciones_no_crean_ocurrencias(contenido):
    fragmento = '<table>' + A.replace('CONTENIDO_A_SINTETICO', contenido) + '</table>'
    _, actos = _resolver_lectura(leer(detalle(fragmento)))
    assert len(actos) == 1


def test_anexos_validados_no_se_reinterpretan_como_historial_por_su_descripcion():
    # Incluso un texto que parece fecha de cabecera sigue siendo metadato
    # cuando el bloque lo valida como una referencia de anexo legítima.
    anexos = ('<tr><td>Anexos:</td><td><table id="tablaAnexos"><tr>'
              '<td>2020-01-01 10:00:00</td><td><a href="general.descargarAnexo.con?codigo=FICTICIO">'
              'archivo_sintetico.txt</a></td></tr></table></td></tr>')
    _, actos = _resolver_lectura(leer(documento(A + anexos)))
    assert len(actos) == 1 and len(actos[0].anexos) == 1
    assert actos[0].anexos[0].descripcion == '2020-01-01 10:00:00'


@pytest.mark.parametrize('bloques', [(A, B), (A, A)])
def test_envoltura_transparente_acredita_pertenencia_sin_fusionar_ni_duplicar(bloques):
    # Es la regla de layout existente, no un selector SIGAC nuevo. Las tablas
    # históricas están dentro del formulario validado y fuera de descripciones.
    hijas = ''.join('<table>' + bloque + '</table>' for bloque in bloques)
    envuelto = '<table><tbody><tr><td>' + hijas + '</td></tr></tbody></table>'
    _, actos = _resolver_lectura(leer(detalle(envuelto)))
    esperadas = parse_actuaciones(hijas, '101')
    assert list(actos) == esperadas and len(actos) == 2


@pytest.mark.parametrize('tabla,codigo', [
    ('<table id="tablaAnexos"><tr><td>2020-01-01 10:00:00</td><td>RESPONSABLE SINTETICO</td></tr></table>',
     CodigoHistorial.ANEXO_ENLACE_AUSENTE),
    ('<table id="tablaAnexos"><tr><td>Actuación:</td><td>CONTENIDO_SINTETICO<input></td></tr></table>',
     CodigoHistorial.BLOQUE_CON_CONTROLES),
    ('<table><tr><td>2020-01-01 10:00:00</td><td>RESPONSABLE SINTETICO</td></tr></table>',
     CodigoHistorial.AMBITO_NO_VERIFICADO),
    ('<table><tr><td>Actuación:</td><td>CONTENIDO_SINTETICO</td></tr></table>',
     CodigoHistorial.AMBITO_NO_VERIFICADO),
    ('<table><tr><td><table>'+B+'</table></td></tr></table>',
     CodigoHistorial.AMBITO_NO_VERIFICADO),
])
def test_historia_reconocible_sin_clasificacion_no_se_absorbe(tabla, codigo):
    fragmento = '<table>' + A.replace('CONTENIDO_A_SINTETICO', tabla) + '</table>'
    with pytest.raises(SigacClientError) as error:
        leer(detalle(fragmento))
    assert error.value.codigo is codigo


def test_fixture_original_con_historia_citada_se_rechaza_como_ambigua():
    from backend.tests.test_parser_historial import documento as fixture, parsear
    from tinotify.parsers.parser import ErrorParseoHistorial
    with pytest.raises(ErrorParseoHistorial) as error:
        parsear(fixture('historial_dom_sintetico.html'), contenedor_id='historial_ficticio')
    assert error.value.codigo is CodigoHistorial.AMBITO_NO_VERIFICADO
