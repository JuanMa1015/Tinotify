"""Regresiones de consistencia del endpoint; exclusivamente HTTP sintético."""

import socket

import pytest

from backend.tests.helpers.sigac_detalle import detalle
from backend.tests.test_sigac_flujo import autenticar, cliente_servidor, historial_generico as historial, html
from tinotify.integrations.sigac.sigac_client import SigacIdentityError
from tinotify.parsers.diagnostico_historial import CodigoHistorial


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("Red real prohibida")
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket.socket, "connect", prohibido)


VALIDO = detalle(historial())
OCULTO = '<input name="hidCaso" id="hidCaso" type="hidden" value="101">'
CABECERA = '<div class="ui-state-default ui-corner-all">Información del caso Nro.101 - En proceso</div>'


@pytest.mark.parametrize("respuesta", [VALIDO, detalle(historial(), estado="Estado sintético distinto")])
def test_detalle_coincidente_se_acepta(respuesta):
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios["casos.formCaso.con"] = html(respuesta)
        assert len(cliente.consultar_historial(101)) == 1


@pytest.mark.parametrize("respuesta", [
    detalle(historial(), cabecera="202"),
    detalle(historial(), oculto="202"),
    detalle(historial(), numero="202"),
    VALIDO.replace(CABECERA, ""),
    VALIDO.replace(OCULTO, ""),
    VALIDO.replace(CABECERA, CABECERA * 2),
    VALIDO.replace(OCULTO, OCULTO * 2),
    detalle(historial(), cabecera=""),
    detalle(historial(), oculto=""),
    detalle(historial(), cabecera="NO_NUMERICO"),
    detalle(historial(), oculto="NO_NUMERICO"),
    detalle(historial(), cabecera="00101", oculto="00101"),
    VALIDO.replace('name="form1"', 'name="otro"'),
    VALIDO.replace('action="casos.guardarCaso.con"', 'action="otra.con"'),
    VALIDO.replace('type="hidden"', 'type="text"'),
    VALIDO.replace('id="hidCaso"', 'id="otro"'),
    VALIDO.replace(OCULTO, OCULTO.replace('type="hidden"', 'form="otro" type="hidden"')),
    VALIDO.replace(CABECERA, "<!--" + CABECERA + "-->"),
    VALIDO.replace(OCULTO, "<!--" + OCULTO + "-->"),
    VALIDO.replace(CABECERA, "").replace('</form>', CABECERA + '</form>'),
    VALIDO.replace(OCULTO, "").replace('</form>', '</form><form id="otro">' + OCULTO + '</form>'),
    # Marcadores únicamente dentro del contenido de una actuación.
    historial(CABECERA + OCULTO),
    # Historial enteramente fuera, o una segunda tabla fuera del detalle.
    detalle("").replace('</body>', historial().removeprefix('<html><body>').removesuffix('</body></html>') + '</body>'),
    VALIDO.replace('</body>', historial().removeprefix('<html><body>').removesuffix('</body></html>') + '</body>'),
])
def test_identidad_ausente_contradictoria_o_ambigua_rechaza(respuesta):
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios["casos.formCaso.con"] = html(respuesta)
        with pytest.raises(SigacIdentityError):
            cliente.consultar_historial(101)


@pytest.mark.parametrize("respuesta", [
    VALIDO.replace(CABECERA, '<textarea>' + CABECERA + '</textarea>'),
    VALIDO.replace(CABECERA, '<template>' + CABECERA + '</template>'),
    VALIDO.replace(OCULTO, '<table id="tablaAnexos"><tr><td>' + OCULTO + '</td></tr></table>'),
    VALIDO.replace('</form>', ''),
    VALIDO.replace('<form name=', '<form><form name=').replace('</form>', '</form></form>'),
    VALIDO.replace('id="form1"', 'id="form1" id="otro"'),
    VALIDO.replace('value="101"', 'value="101" value="202"'),
    VALIDO.replace('value="101"', 'value=" 101 "'),
    VALIDO.replace('Nro.101', 'Nro.+101'),
    VALIDO.replace('Nro.101', 'Nro.١٠١'),
    VALIDO.replace('multipart/form-data', 'application/x-www-form-urlencoded'),
    VALIDO.replace('<div class="ui-widget-content ui-corner-all">',
                   '<div class="ui-widget-content ui-corner-all"><div class="ui-widget-content ui-corner-all">')
          .replace('</body>', '</div></body>'),
    VALIDO.replace('</body>', VALIDO.removeprefix('<html><body>').removesuffix('</body></html>') + '</body>'),
])
def test_ambiguedades_de_propiedad_y_normalizacion_son_tipadas(respuesta):
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios['casos.formCaso.con'] = html(respuesta)
        with pytest.raises(SigacIdentityError) as error:
            cliente.consultar_historial(101, diagnostico=True)
        assert error.value.codigo is CodigoHistorial.IDENTIDAD_DETALLE_NO_CONFIRMADA
        assert error.value.diagnostico['diagnostico_version'] == 2
        assert not cliente.autenticada and not cliente.http.cookies


def test_clases_repetidas_ajenas_no_son_selectores_globales():
    ajeno = ('<div class="ui-widget-content ui-corner-all">'
             '<div class="ui-state-default ui-corner-all">OTRO PANEL SINTETICO</div></div>')
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios['casos.formCaso.con'] = html(VALIDO.replace('</body>', ajeno + '</body>'))
        assert len(cliente.consultar_historial(101)) == 1


def test_orden_multiplicidad_y_huellas_no_cambian_por_envoltura():
    from tinotify.parsers.parser import parse_actuaciones
    uno = historial('CONTENIDO_SINTETICO_A').removeprefix('<html><body>').removesuffix('</body></html>')
    dos = historial('CONTENIDO_SINTETICO_B').removeprefix('<html><body>').removesuffix('</body></html>')
    contenido = uno + dos + uno
    esperadas = parse_actuaciones(contenido, '101')
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios['casos.formCaso.con'] = html(detalle(contenido))
        extraidas = cliente.consultar_historial(101)
    assert list(extraidas) == esperadas and len(extraidas) == 3
    assert extraidas[0].huella_version == extraidas[2].huella_version
    assert extraidas[0].huella_version != extraidas[1].huella_version


def test_contenedor_opcional_no_puede_ocultar_historial_del_formulario():
    uno = historial().removeprefix('<html><body>').removesuffix('</body></html>')
    contenido = '<section id="subconjunto">' + uno + '</section>' + uno
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios['casos.formCaso.con'] = html(detalle(contenido))
        with pytest.raises(SigacIdentityError):
            cliente.consultar_historial(101, contenedor_id='subconjunto')


@pytest.mark.parametrize('previa', [False, True])
@pytest.mark.parametrize('respuesta', [
    detalle(historial(), cabecera='202'), detalle(historial(), oculto='202'),
    VALIDO.replace(OCULTO, ''),
    VALIDO.replace('</body>', historial().removeprefix('<html><body>').removesuffix('</body></html>') + '</body>'),
])
def test_rechazo_http_no_modifica_ningun_estado_sqlite_v2(tmp_path, monkeypatch, previa, respuesta):
    from uuid import uuid4
    from backend.tests.test_sqlite_local_v2 import servicio, observar, snapshot, CASO_OBSERVADO
    ruta = tmp_path / 'solo_sintetico.sqlite3'
    s = servicio(ruta)
    if previa:
        observar(s, 2, 0)
    antes = snapshot(s)
    bytes_antes = ruta.read_bytes()
    def no_persistir(*args, **kwargs):
        pytest.fail('Una respuesta rechazada no llega a reconciliacion/persistencia')
    monkeypatch.setattr(s, 'observar', no_persistir)
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios['casos.formCaso.con'] = html(respuesta)
        with pytest.raises(SigacIdentityError):
            actuaciones = cliente.consultar_historial(101)
            s.observar(CASO_OBSERVADO, actuaciones, clave=uuid4(), generacion_esperada=int(previa))
    assert snapshot(s) == antes
    assert ruta.read_bytes() == bytes_antes


def test_contradiccion_detiene_ensayo_antes_del_reconciliador(monkeypatch, caplog):
    import tinotify.services.ensayo_sigac as ensayo
    from backend.tests.test_sigac_flujo import USUARIO, CLAVE, TIPO, COOKIE
    def prohibido(*args, **kwargs):
        pytest.fail('El reconciliador no debe recibir la respuesta contradictoria')
    monkeypatch.setattr(ensayo, 'reconciliar', prohibido)
    with cliente_servidor() as (cliente, servidor):
        servidor.cambios['casos.formCaso.con'] = html(detalle(historial(), numero='202'))
        with pytest.raises(SigacIdentityError) as error:
            ensayo.ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo=TIPO, total_casos=2)
        assert len(servidor.llamadas) == 7
        assert all(s not in str(error.value) + caplog.text for s in (USUARIO, CLAVE, COOKIE, '101', '202'))
