"""Contrato observado con servidor sintético; no demuestra acceso real a SIGAC."""

from contextlib import contextmanager
from pathlib import Path
import importlib.util
import json
import logging
import socket
import traceback
import warnings
from urllib.parse import parse_qs

import httpx
import pytest
from backend.tests.helpers.sigac_detalle import detalle

from tinotify.integrations.sigac.sigac_client import BASE_URL, SigacClient, SigacClientError, SigacSessionExpired
from tinotify.parsers.casos_parser import extraer_casos
from tinotify.parsers.diagnostico_historial import (
    CodigoHistorial, ContextoDiagnostico, EtapaSigac, diagnostico_seguro,
)
from tinotify.services.ensayo_sigac import ejecutar_ensayo


USUARIO = "USUARIO_FICTICIO"
CLAVE = "CLAVE_FICTICIA_NO_REAL"
COOKIE = "SESION_FICTICIA_NO_REAL"
TIPO = "OPCION_FICTICIA"


def pagina(contenido):
    return "<html><body>" + contenido + "</body></html>"


ACCESO = pagina('''<form action="sesion.validar.ses" method="post">
<select name="cboTipo"><option value="OPCION_FICTICIA">DEMO</option></select>
<input name="txtUsuario"><input name="txtCaso" value="">
<input type="password" name="txtClave"><input type="submit" name="cmdIngresar" value="INGRESO_FICTICIO">
</form>''')
ROLES = pagina('''<form action="sesion.cambiar.ses" method="post">
<input type="radio" name="chkTipoUsuario" value="ESTUDIANTE">
<input type="submit" name="cmdAceptar" value="Aceptar"></form>''')


def fila_caso(numero):
    return f'<tr class="fila_enlace" onclick="abrir({numero})"><td>{numero}</td><td>CLIENTE FICTICIO</td><td>ESTADO FICTICIO</td></tr>'


LISTADO = pagina('<table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr>' + fila_caso(101) + fila_caso(202) + '</table>')


def historial_generico(texto="CONTENIDO_FICTICIO"):
    return pagina('<section id="historial_ficticio"><table><tr><td colspan="2"><hr></td></tr>'
                  '<tr><td></td><td></td></tr><tr><td>2020-01-01 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
                  f'<tr><td>Reparto :</td><td>{texto}</td></tr></table></section>')


def historial(texto="CONTENIDO_FICTICIO"):
    return detalle(historial_generico(texto))


def html(texto):
    return httpx.Response(200, text=texto, headers={"content-type": "text/html; charset=utf-8"})


class Servidor:
    def __init__(self):
        self.llamadas = []
        self.cambios = {}

    def __call__(self, peticion):
        ruta = peticion.url.path.removeprefix("/sigac/")
        # Solo las pruebas retienen estas solicitudes, todas ficticias.
        self.llamadas.append(peticion)
        if ruta in self.cambios:
            respuesta = self.cambios[ruta]
            return respuesta(peticion) if callable(respuesta) else respuesta
        if ruta == "index.jsp":
            return html(ACCESO)
        if ruta == "sesion.validar.ses":
            assert peticion.method == "POST"
            assert peticion.headers["content-type"] == "application/x-www-form-urlencoded"
            assert parse_qs(peticion.content.decode(), keep_blank_values=True) == {
                "cboTipo": [TIPO], "txtUsuario": [USUARIO], "txtClave": [CLAVE],
                "txtCaso": [""], "cmdIngresar": ["INGRESO_FICTICIO"],
            }
            return httpx.Response(302, headers={"location": "general.formCambiarTipoUsuario.con",
                "set-cookie": f"JSESSIONID={COOKIE}; Path=/sigac/; Secure; HttpOnly"})
        assert peticion.headers["cookie"] == f"JSESSIONID={COOKIE}"
        if ruta == "general.formCambiarTipoUsuario.con":
            return html(ROLES)
        if ruta == "sesion.cambiar.ses":
            assert peticion.content == b"chkTipoUsuario=ESTUDIANTE&cmdAceptar=Aceptar"
            return httpx.Response(302, headers={"location": "general.principal.con"})
        if ruta == "general.principal.con":
            return html(pagina("PAGINA_PRINCIPAL_FICTICIA"))
        if ruta == "casos.seleccionarCasos.con":
            assert peticion.method == "GET" and peticion.url.query == b"motivo=ACTUAR_ESTUDIANTE"
            return html(LISTADO)
        if ruta == "casos.formCaso.con":
            assert peticion.method == "POST"
            datos = parse_qs(peticion.content.decode())
            assert datos["hidCaso"][0] in {"101", "202"}
            assert datos["hidMotivo"] == ["ACTUAR_ESTUDIANTE"]
            assert set(datos) == {"hidCaso", "hidMotivo"}
            return html(detalle(historial_generico(), numero=datos["hidCaso"][0]))
        pytest.fail("Solicitud no incluida en el contrato sintético")


@contextmanager
def cliente_servidor(servidor=None):
    servidor = servidor or Servidor()
    with httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(servidor)) as http:
        with SigacClient(http) as cliente:
            yield cliente, servidor
        assert not http.cookies


def autenticar(cliente, **kwargs):
    return cliente.autenticar(USUARIO, CLAVE, tipo=TIPO, total_casos_esperado=2, **kwargs)


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("Estas pruebas no deben usar red")
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket.socket, "connect", prohibido)


def test_flujo_completo_sin_persistencia_y_consultas_repetidas(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with cliente_servidor() as (cliente, servidor):
        resumen = ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo=TIPO, total_casos=2,
                                  total_actuaciones=1, contenedor_id="historial_ficticio")
        assert cliente.autenticada
        assert resumen == {"resultado": "estable", "casos": 2, "actuaciones": 1,
                           "consultas_historial": 2, "eventos_baseline": 0,
                           "eventos_posteriores": 0, "persistencia": "ninguna",
                           "lectura_funcional": True, "completitud": "total_contrastado",
                           "actuaciones_por_consulta": [1, 1], "anexos_sin_enlace_por_consulta": [0, 0],
                           "regiones_interactivas_excluidas_por_consulta": [0, 0],
                           "filas_interactivas_excluidas_por_consulta": [0, 0],
                           "comparaciones": [
                               {"consulta": 2, "sin_cambios": True,
                                "ocurrencias_no_presentes_en_base": 0, "ocurrencias_no_observadas": 0}]}
        assert len(servidor.llamadas) == 9
        assert not list(tmp_path.iterdir())
        assert not any(v in repr(cliente.__dict__) for v in (USUARIO, CLAVE, COOKIE))


@pytest.mark.parametrize("destino", ["https://ajeno.invalid/", "//ajeno.invalid/", "index.jsp",
    "general.formCambiarTipoUsuario.con?token=FICTICIO", "general.formCambiarTipoUsuario.con#x",
    "general.formCambiarTipoUsuario.con\r\nX:valor"])
def test_login_redireccion_no_confirmada_no_se_sigue(destino):
    servidor = Servidor()
    servidor.cambios["sesion.validar.ses"] = httpx.Response(302, headers={"location": destino})
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacClientError): autenticar(cliente)
        assert not cliente.autenticada and len(servidor.llamadas) == 2


@pytest.mark.parametrize("cookie", [None, "JSESSIONID=FICTICIO; Domain=ajeno.invalid; Path=/",
    "OTRA=FICTICIO; Path=/sigac/", "JSESSIONID=; Path=/sigac/",
    "JSESSIONID=FICTICIO; Max-Age=0; Path=/sigac/", "JSESSIONID=FICTICIO; Path=/otra/"])
def test_302_sin_cookie_aplicable_no_autentica(cookie):
    servidor = Servidor()
    cabeceras = {"location": "general.formCambiarTipoUsuario.con"}
    if cookie: cabeceras["set-cookie"] = cookie
    servidor.cambios["sesion.validar.ses"] = httpx.Response(302, headers=cabeceras)
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacSessionExpired) as error: autenticar(cliente)
        assert error.value.codigo is CodigoHistorial.SESION_NO_CONFIRMADA
        assert error.value.etapa is EtapaSigac.SESION
        assert not cliente.autenticada and len(servidor.llamadas) == 2


@pytest.mark.parametrize("ruta", ["index.jsp", "sesion.validar.ses", "general.formCambiarTipoUsuario.con",
    "sesion.cambiar.ses", "general.principal.con", "casos.seleccionarCasos.con"])
@pytest.mark.parametrize("estado", [401, 403, 500])
def test_errores_en_cada_etapa_no_autentican(ruta, estado):
    servidor = Servidor()
    servidor.cambios[ruta] = httpx.Response(estado, text=CLAVE + COOKIE)
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacClientError) as error: autenticar(cliente)
        assert not cliente.autenticada and not cliente.http.cookies
        texto = ''.join(traceback.format_exception(error.value))
        assert CLAVE not in texto and COOKIE not in texto


@pytest.mark.parametrize("formulario", [
    ACCESO.replace('name="txtClave"', 'name="CAMPO_NO_CONFIRMADO"'),
    ACCESO.replace('</form>', '<input name="csrf" value="TOKEN_FICTICIO"></form>'),
    ACCESO.replace('method="post"', 'method="get"'),
    ACCESO.replace('value="INGRESO_FICTICIO"', ''),
    ACCESO.replace('</form>', '<input name="txtUsuario"></form>'),
    ACCESO.replace('action="sesion.validar.ses"', 'action="https://ajeno.invalid/"'),
    ACCESO.removesuffix('</body></html>'),
])
def test_formulario_distinto_no_envia_credenciales(formulario):
    servidor = Servidor()
    servidor.cambios["index.jsp"] = html(formulario)
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacClientError): autenticar(cliente)
        assert len(servidor.llamadas) == 1


def test_tipo_no_observado_no_se_prueba():
    with cliente_servidor() as (cliente, servidor):
        with pytest.raises(SigacClientError):
            cliente.autenticar(USUARIO, CLAVE, tipo="NO_OBSERVADO", total_casos_esperado=2)
        assert len(servidor.llamadas) == 1


@pytest.mark.parametrize("formulario", [ROLES.replace('value="ESTUDIANTE"', 'value="OTRO_ROL"'),
    ROLES.replace('value="Aceptar"', 'value="OTRA_ACCION"'),
    ROLES.replace('</form>', '<input name="campo_nuevo" value="FICTICIO"></form>')])
def test_selector_no_confirmado_no_envia_cambio_de_rol(formulario):
    servidor = Servidor()
    servidor.cambios["general.formCambiarTipoUsuario.con"] = html(formulario)
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacClientError): autenticar(cliente)
        assert len(servidor.llamadas) == 3 and not cliente.autenticada


@pytest.mark.parametrize("ruta", ["general.formCambiarTipoUsuario.con", "general.principal.con",
    "casos.seleccionarCasos.con"])
def test_200_con_login_en_cualquier_etapa_no_autentica(ruta):
    servidor = Servidor()
    servidor.cambios[ruta] = html(ACCESO)
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacClientError): autenticar(cliente)
        assert not cliente.autenticada


@pytest.mark.parametrize("cuerpo", [
    LISTADO.replace('abrir(202)', 'abrir(999)'),
    LISTADO.replace('class="fila_enlace"', 'class="desconocida"', 1),
    LISTADO.replace(fila_caso(202), ''),
    LISTADO.replace(fila_caso(202), fila_caso(101)),
    LISTADO.replace('</table>', '<tr><td>FILA_INCOMPLETA</td></tr></table>'),
    LISTADO.replace('</body>', '<table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr></table></body>'),
])
def test_listado_parcial_no_autentica(cuerpo):
    servidor = Servidor()
    servidor.cambios["casos.seleccionarCasos.con"] = html(cuerpo)
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacClientError): autenticar(cliente)
        assert not cliente.autenticada


@pytest.mark.parametrize("respuesta", [httpx.Response(401), httpx.Response(403),
    httpx.Response(302, headers={"location": "index.jsp"}), html(ACCESO), html(ROLES)])
@pytest.mark.parametrize("total", [1, None])
def test_sesion_vencida_en_historial_no_devuelve_observaciones(respuesta, total):
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios["casos.formCaso.con"] = respuesta
        with pytest.raises(SigacSessionExpired): cliente.consultar_historial(101, total_esperado=total)
        assert not cliente.autenticada


@pytest.mark.parametrize("respuesta", [html(''), html(historial().replace('</html>', '')),
    html(historial().replace('2020-01-01 10:00:00', 'FECHA_ILEGIBLE')),
    html(pagina('SIN_HISTORIAL')), httpx.Response(200, content=b'{}', headers={"content-type": "application/json"}),
    httpx.Response(500, text=CLAVE),
    httpx.Response(200, content=b'<html>', headers={"content-type": "text/html", "content-length": "1000"}),
])
@pytest.mark.parametrize("total", [1, None])
def test_historial_incompleto_o_error_no_se_acepta(respuesta, total):
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios["casos.formCaso.con"] = respuesta
        with pytest.raises(SigacClientError): cliente.consultar_historial(101, total_esperado=total)


def test_no_se_consultan_expedientes_ajenos_al_listado():
    with cliente_servidor() as (cliente, servidor):
        with pytest.raises(SigacSessionExpired): cliente.consultar_historial(101, total_esperado=1)
        autenticar(cliente)
        cantidad = len(servidor.llamadas)
        with pytest.raises(SigacClientError): cliente.consultar_historial(999, total_esperado=1)
        assert len(servidor.llamadas) == cantidad


def test_listado_refrescado_incompleto_revoca_pertenencia():
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios["casos.seleccionarCasos.con"] = html(LISTADO.replace(fila_caso(202), ''))
        with pytest.raises(SigacClientError): cliente.listar_casos(total_esperado=2)
        with pytest.raises(SigacSessionExpired): cliente.consultar_historial(101, total_esperado=1)
        assert not cliente._casos and not cliente.http.cookies


def test_cookies_aisladas_entre_instancias():
    with cliente_servidor() as (primero, _), cliente_servidor() as (segundo, _):
        autenticar(primero)
        assert not segundo.http.cookies and not segundo.autenticada
        autenticar(segundo)
        primero.cerrar()
        assert segundo.autenticada and not primero.autenticada


def test_limite_de_respuesta_rechaza_sin_truncar(monkeypatch):
    import tinotify.integrations.sigac.sigac_client as modulo
    with cliente_servidor() as (cliente, _):
        autenticar(cliente)
        monkeypatch.setattr(modulo, 'MAX_HTML_BYTES', 10)
        with pytest.raises(SigacClientError): cliente.consultar_historial(101, total_esperado=1)


def test_timeout_al_repetir_no_produce_informe_estable():
    servidor = Servidor()
    llamadas = []
    def respuesta(request):
        llamadas.append(1)
        if len(llamadas) == 2:
            raise httpx.ReadTimeout('FALLO_FICTICIO', request=request)
        return html(historial())
    servidor.cambios['casos.formCaso.con'] = respuesta
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacClientError):
            ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo=TIPO, total_casos=2, total_actuaciones=1)
    assert len(llamadas) == 2


def test_timeout_no_filtra_datos_ni_reintenta(caplog):
    caplog.set_level(logging.DEBUG)
    servidor = Servidor()
    def fallo(request):
        raise httpx.ReadTimeout(CLAVE + COOKIE, request=request)
    servidor.cambios["sesion.validar.ses"] = fallo
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacClientError) as error: autenticar(cliente)
        texto = ''.join(traceback.format_exception(error.value)) + caplog.text
        assert all(valor not in texto for valor in (USUARIO, CLAVE, COOKIE))
        assert len(servidor.llamadas) == 2


def test_cambio_observado_no_se_declara_estable():
    servidor = Servidor()
    respuestas = iter([historial(), historial('CONTENIDO_MODIFICADO_FICTICIO')])
    servidor.cambios["casos.formCaso.con"] = lambda _: html(next(respuestas))
    with cliente_servidor(servidor) as (cliente, _):
        resumen = ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo=TIPO, total_casos=2, total_actuaciones=1)
        assert resumen["resultado"] == "cambios_observados"
        assert resumen["eventos_baseline"] == 0 and resumen["eventos_posteriores"] == 1


def test_resumen_informa_solo_cantidades_de_regiones_interactivas_excluidas(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    region = ('<tr><td colspan="2"><div id="tabs"><div id="tabs-1"><textarea></textarea>'
              '<button>Guardar</button></div></div></td></tr>')
    cuerpo = ('<table><tr><td colspan="2"><hr></td></tr>'
              '<tr><td>2020-01-01 10:00:00</td><td>RESPONSABLE_FICTICIO</td></tr>'
              '<tr><td>Reparto :</td><td>CONTENIDO_FICTICIO</td></tr>'
              '<tr><td colspan="2"><hr></td></tr>' + region + '</table>')
    servidor = Servidor()
    servidor.cambios["casos.formCaso.con"] = html(detalle(cuerpo))
    with cliente_servidor(servidor) as (cliente, _):
        resumen = ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo=TIPO, total_casos=2)
    assert resumen["actuaciones_por_consulta"] == [1, 1] and resumen["resultado"] == "estable"
    assert resumen["regiones_interactivas_excluidas_por_consulta"] == [1, 1]
    assert resumen["filas_interactivas_excluidas_por_consulta"] == [1, 1]
    assert "CONTENIDO_FICTICIO" not in str(resumen) and "tabs" not in str(resumen)


def test_exploracion_15_procesos_sin_conteo_no_afirma_completitud(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    servidor = Servidor()
    servidor.cambios['casos.seleccionarCasos.con'] = html(pagina(
        '<table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr>'
        + ''.join(fila_caso(n) for n in range(101, 116)) + '</table>'))
    with cliente_servidor(servidor) as (cliente, _):
        resumen = ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo=TIPO, total_casos=15,
                                  indice_caso=1, repeticiones=2)
    assert resumen['lectura_funcional'] is True
    assert resumen['completitud'] == 'completitud_no_verificada'
    assert resumen['resultado'] == 'estable' and resumen['casos'] == 15
    assert resumen['actuaciones_por_consulta'] == [1, 1]
    assert resumen['eventos_baseline'] == resumen['eventos_posteriores'] == 0
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('modo', ['edicion', 'duplicado', 'ausencia'])
def test_exploracion_reporta_diferencias_sin_identificar_actuaciones(modo):
    simple = historial()
    doble = simple.replace('</table>', simple.split('<table>', 1)[1].split('</table>', 1)[0] + '</table>')
    pares = {'edicion': [simple, historial('CAMBIO_FICTICIO_PRIVADO')],
             'duplicado': [simple, doble], 'ausencia': [doble, simple]}
    servidor = Servidor()
    respuestas = iter(pares[modo])
    servidor.cambios['casos.formCaso.con'] = lambda _: html(next(respuestas))
    with cliente_servidor(servidor) as (cliente, _):
        resumen = ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo=TIPO, total_casos=2)
    assert resumen['resultado'] == 'cambios_observados'
    assert resumen['completitud'] == 'completitud_no_verificada'
    comparacion = resumen['comparaciones'][0]
    assert comparacion['sin_cambios'] is False
    assert comparacion['ocurrencias_no_presentes_en_base'] == (0 if modo == 'ausencia' else 1)
    assert comparacion['ocurrencias_no_observadas'] == (0 if modo == 'duplicado' else 1)
    salida = json.dumps(resumen)
    assert all(v not in salida for v in (USUARIO, CLAVE, COOKIE, 'CAMBIO_FICTICIO_PRIVADO',
                                        'CONTENIDO_FICTICIO', 'CLIENTE FICTICIO', 'RESPONSABLE_FICTICIO'))


def test_totales_y_contenedor_no_coincidentes_rechazan():
    with cliente_servidor() as (cliente, _):
        autenticar(cliente)
        with pytest.raises(SigacClientError): cliente.consultar_historial(101, total_esperado=2)
        with pytest.raises(SigacClientError):
            cliente.consultar_historial(101, total_esperado=1, contenedor_id="NO_EXISTE")


def test_legacy_listado_conserva_comportamiento_pero_flujo_estricto_rechaza():
    parcial = LISTADO.replace('abrir(202)', 'abrir(999)')
    assert len(extraer_casos(parcial)) == 1
    with pytest.raises(ValueError): extraer_casos(parcial, estricto=True, total_esperado=2)


def cargar_entrada():
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "ensayo_sigac.py"
    spec = importlib.util.spec_from_file_location("entrada_ensayo", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_script_sin_autorizacion_no_pide_credenciales_ni_conecta(monkeypatch):
    modulo = cargar_entrada()
    monkeypatch.setattr(modulo.getpass, "getpass", lambda _: pytest.fail("No debe pedir datos"))
    with pytest.raises(SystemExit): modulo.main(['--tipo', TIPO, '--total-casos', '2', '--total-actuaciones', '1'])


@pytest.mark.parametrize("total", [[], ['--total-actuaciones', '1']])
def test_script_con_mock_salida_solo_resumen(monkeypatch, capsys, caplog, total):
    modulo = cargar_entrada()
    servidor = Servidor()
    caplog.set_level(logging.DEBUG)
    def respuesta_con_traza(_):
        logging.getLogger('httpcore.http11').critical(CLAVE + COOKIE)
        return html(historial())
    servidor.cambios['casos.formCaso.con'] = respuesta_con_traza
    with cliente_servidor(servidor) as (cliente, _):
        monkeypatch.setattr(modulo, "SigacClient", lambda: cliente)
        monkeypatch.setattr(modulo.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr('builtins.input', lambda _: 'SIGAC-LECTURA')
        credenciales = iter([USUARIO, CLAVE])
        monkeypatch.setattr(modulo.getpass, "getpass", lambda _: next(credenciales))
        nivel_anterior = logging.root.manager.disable
        try:
            assert modulo.main(['--autorizar-sigac-real', '--tipo', TIPO,
                                '--total-casos', '2', '--indice-caso', '1', '--consultas', '2', *total]) == 0
            assert logging.root.manager.disable == logging.CRITICAL
        finally:
            logging.disable(nivel_anterior)
    salida = capsys.readouterr().out
    assert json.loads(salida)["resultado"] == "estable"
    assert json.loads(salida)["completitud"] == ('total_contrastado' if total else 'completitud_no_verificada')
    assert all(valor not in salida for valor in (USUARIO, CLAVE, COOKIE, 'CLIENTE FICTICIO', '101'))
    assert CLAVE not in caplog.text and COOKIE not in caplog.text


@pytest.mark.parametrize('cuerpo,codigo', [
    (historial().replace('</html>', ''), CodigoHistorial.DOCUMENTO_INCOMPLETO),
    (historial().replace('</body>', '<table><tr><td>AJENO_O_ROTO_FICTICIO</td></tr></table></body>'),
     CodigoHistorial.AMBITO_NO_VERIFICADO),
    (historial().replace('2020-01-01 10:00:00', 'FECHA_ILEGIBLE_FICTICIA'), CodigoHistorial.CABECERA_INVALIDA),
    (detalle('SIN_HISTORIAL_FICTICIO'), CodigoHistorial.SIN_ACTUACIONES),
])
def test_cliente_distingue_respuesta_y_parser_sin_revelar_contenido(cuerpo, codigo):
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios['casos.formCaso.con'] = html(cuerpo)
        for diagnostico in (False, True):
            with pytest.raises(SigacClientError) as error:
                cliente.consultar_historial(101, diagnostico=diagnostico)
            assert str(error.value) == 'Historial incompleto, ambiguo o de estructura no confirmada.'
            assert error.value.codigo is codigo
            if diagnostico:
                datos = error.value.diagnostico
                assert datos['categoria'] == codigo.value
                assert 'tablas_documento' in datos['estadisticas_estructurales']
                salida = json.dumps(datos)
                assert all(v not in salida for v in (USUARIO, CLAVE, COOKIE, cuerpo, 'FECHA_ILEGIBLE_FICTICIA'))
            else:
                assert error.value.diagnostico is None


def test_total_discordante_diagnostico_distingue_validacion_final():
    with cliente_servidor() as (cliente, _):
        autenticar(cliente)
        with pytest.raises(SigacClientError) as error:
            cliente.consultar_historial(101, total_esperado=2, diagnostico=True)
        assert error.value.codigo is CodigoHistorial.TOTAL_DISCORDANTE
        assert error.value.diagnostico['estadisticas_estructurales']['bloques_validos'] == 1


def advertencia_privada_ficticia(_):
    warnings.warn(CLAVE + COOKIE)
    return html(historial())


def fallo_privado_ficticio(_):
    raise RuntimeError(CLAVE + COOKIE)


@pytest.mark.parametrize('respuesta,codigo', [
    (httpx.Response(500, text=CLAVE + COOKIE), CodigoHistorial.HTTP_INVALIDO),
    (httpx.Response(403), CodigoHistorial.SESION_NO_CONFIRMADA),
    (html(historial().replace('</body>', '<table><tr><td>SECCION_FICTICIA</td></tr></table></body>')),
     CodigoHistorial.AMBITO_NO_VERIFICADO),
    (advertencia_privada_ficticia, CodigoHistorial.ADVERTENCIA_BIBLIOTECA),
    (fallo_privado_ficticio, CodigoHistorial.ERROR_INTERNO),
])
def test_cli_diagnostico_solo_categoria_y_conteos(monkeypatch, capsys, respuesta, codigo, tmp_path):
    modulo = cargar_entrada()
    monkeypatch.chdir(tmp_path)
    with cliente_servidor() as (cliente, servidor):
        servidor.cambios['casos.formCaso.con'] = respuesta
        monkeypatch.setattr(modulo, 'SigacClient', lambda: cliente)
        monkeypatch.setattr(modulo.sys.stdin, 'isatty', lambda: True)
        monkeypatch.setattr('builtins.input', lambda _: 'SIGAC-LECTURA')
        valores = iter([USUARIO, CLAVE])
        monkeypatch.setattr(modulo.getpass, 'getpass', lambda _: next(valores))
        nivel_anterior = logging.root.manager.disable
        try:
            assert modulo.main(['--autorizar-sigac-real', '--diagnostico', '--tipo', TIPO,
                                '--total-casos', '2', '--indice-caso', '1', '--consultas', '2']) == 1
        finally:
            logging.disable(nivel_anterior)
    captura = capsys.readouterr()
    salida = captura.out
    datos = json.loads(salida)
    assert datos['categoria'] == codigo.value
    assert datos == diagnostico_seguro(codigo, datos['estadisticas_estructurales'], etapa=EtapaSigac.HISTORIAL_INICIAL)
    assert all(v not in salida for v in (USUARIO, CLAVE, COOKIE, 'SECCION_FICTICIA',
                                        'CONTENIDO_FICTICIO', '2020-01-01', '101'))
    assert captura.err == ''
    assert not list(tmp_path.iterdir())


ESCENARIOS_V2 = [
    ('control', EtapaSigac.FINALIZADO, CodigoHistorial.LECTURA_ESTABLE, 9, 0),
    ('creacion_cliente', EtapaSigac.CREACION_CLIENTE, CodigoHistorial.ERROR_INTERNO, 0, 1),
    ('submit_sin_value', EtapaSigac.FORMULARIO, CodigoHistorial.FORMULARIO_SUBMIT_SIN_VALOR, 1, 1),
    ('campo_deshabilitado', EtapaSigac.FORMULARIO, CodigoHistorial.FORMULARIO_CAMPOS_INVALIDOS, 1, 1),
    ('documento_incompleto', EtapaSigac.FORMULARIO, CodigoHistorial.DOCUMENTO_INCOMPLETO, 1, 1),
    ('selector_sin_estudiante', EtapaSigac.SELECTOR_ROL, CodigoHistorial.ROL_NO_OFRECIDO, 3, 1),
    ('redireccion_rol', EtapaSigac.REDIRECCION_ROL, CodigoHistorial.REDIRECCION_NO_CONFIRMADA, 4, 1),
    ('listado_invalido', EtapaSigac.LISTADO_INICIAL, CodigoHistorial.LISTADO_NO_CONFIRMADO, 6, 1),
    ('advertencia_historial', EtapaSigac.HISTORIAL_INICIAL, CodigoHistorial.ADVERTENCIA_BIBLIOTECA, 7, 1),
    ('anidacion_profunda', EtapaSigac.HISTORIAL_INICIAL, CodigoHistorial.ERROR_INTERNO, 7, 1),
    ('listado_cambiado', EtapaSigac.LISTADO_REPETIDO, CodigoHistorial.LISTADO_CAMBIADO, 8, 1),
]


@pytest.mark.parametrize('escenario,etapa,categoria,peticiones,salida_esperada', ESCENARIOS_V2,
                         ids=[e[0] for e in ESCENARIOS_V2])
def test_diagnostico_v2_once_escenarios(escenario, etapa, categoria, peticiones, salida_esperada,
                                      monkeypatch, capsys, caplog, tmp_path):
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.DEBUG)
    globales = Servidor.__call__.__globals__
    acceso = ACCESO.replace(TIPO, '1')
    listado = pagina('<table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr>'
                     + ''.join(fila_caso(n) for n in range(101, 116)) + '</table>')
    monkeypatch.setitem(globales, 'TIPO', '1')
    monkeypatch.setitem(globales, 'ACCESO', acceso)
    monkeypatch.setitem(globales, 'LISTADO', listado)
    servidor = Servidor()
    if escenario == 'submit_sin_value':
        servidor.cambios['index.jsp'] = html(acceso.replace('value="INGRESO_FICTICIO"', ''))
    elif escenario == 'campo_deshabilitado':
        servidor.cambios['index.jsp'] = html(acceso.replace('name="txtCaso"', 'name="txtCaso" disabled'))
    elif escenario == 'documento_incompleto':
        servidor.cambios['index.jsp'] = html(acceso.removesuffix('</body></html>'))
    elif escenario == 'selector_sin_estudiante':
        servidor.cambios['general.formCambiarTipoUsuario.con'] = html(ROLES.replace('ESTUDIANTE', 'OTRO_FICTICIO'))
    elif escenario == 'redireccion_rol':
        servidor.cambios['sesion.cambiar.ses'] = httpx.Response(302, headers={'location': 'DESTINO_FICTICIO'})
    elif escenario == 'listado_invalido':
        servidor.cambios['casos.seleccionarCasos.con'] = html(listado.replace('class="fila_enlace"', 'class="OTRA_FICTICIA"', 1))
    elif escenario == 'advertencia_historial':
        servidor.cambios['casos.formCaso.con'] = advertencia_privada_ficticia
    elif escenario == 'anidacion_profunda':
        servidor.cambios['casos.formCaso.con'] = html(historial('<span>' * 1200 + 'CONTENIDO_FICTICIO' + '</span>' * 1200))
    elif escenario == 'listado_cambiado':
        respuestas = iter([listado, listado.replace(fila_caso(115), fila_caso(116))])
        servidor.cambios['casos.seleccionarCasos.con'] = lambda _: html(next(respuestas))
    modulo = cargar_entrada()
    with cliente_servidor(servidor) as (cliente, _):
        def fabrica():
            if escenario == 'creacion_cliente':
                raise RuntimeError(CLAVE + COOKIE)
            return cliente
        monkeypatch.setattr(modulo, 'SigacClient', fabrica)
        monkeypatch.setattr(modulo.sys.stdin, 'isatty', lambda: True)
        monkeypatch.setattr('builtins.input', lambda _: 'SIGAC-LECTURA')
        valores = iter([USUARIO, CLAVE])
        monkeypatch.setattr(modulo.getpass, 'getpass', lambda _: next(valores))
        nivel_anterior = logging.root.manager.disable
        try:
            assert modulo.main(['--autorizar-sigac-real', '--diagnostico', '--tipo', '1',
                                '--total-casos', '15', '--indice-caso', '1', '--consultas', '2']) == salida_esperada
        finally:
            logging.disable(nivel_anterior)
    captura = capsys.readouterr()
    datos = json.loads(captura.out)
    assert datos['diagnostico_version'] == 2
    assert datos['etapa'] == etapa.value and datos['categoria'] == categoria.value
    assert len(servidor.llamadas) == peticiones
    if salida_esperada == 0:
        assert datos['resultado'] == 'estable' and datos['completitud'] == 'completitud_no_verificada'
        assert datos['consultas_historial'] == 2 and datos['actuaciones_por_consulta'] == [1, 1]
        assert datos['eventos_baseline'] == datos['eventos_posteriores'] == 0
        assert sum(p.url.path.endswith('casos.formCaso.con') for p in servidor.llamadas) == 2
    else:
        assert set(datos) == {'diagnostico_version', 'etapa', 'categoria', 'estadisticas_estructurales'}
        assert datos.get('lectura_funcional') is not True
    texto = captura.out + captura.err + caplog.text
    assert captura.err == ''
    assert all(s not in texto for s in (USUARIO, CLAVE, COOKIE, 'CONTENIDO_FICTICIO',
                                       'RESPONSABLE_FICTICIO', '2020-01-01', 'DESTINO_FICTICIO',
                                       'sigac.udea.edu.co', 'Traceback', '<html>'))
    assert not list(tmp_path.iterdir())


def test_etapas_y_categorias_no_aceptan_texto_arbitrario():
    contexto = ContextoDiagnostico()
    contexto.marcar(CLAVE)
    assert contexto.etapa is EtapaSigac.NO_DETERMINADA
    datos = diagnostico_seguro(CLAVE, {COOKIE: CLAVE}, etapa=COOKIE)
    assert datos == {'diagnostico_version': 2, 'etapa': 'no_determinada',
                     'categoria': 'fallo_no_clasificado', 'estadisticas_estructurales': {}}


def test_codigo_documento_incompleto_preservado_en_listado_y_clasificacion():
    from tinotify.services.monitor_local import clasificar
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios['casos.seleccionarCasos.con'] = html(LISTADO.removesuffix('</body></html>'))
        with pytest.raises(SigacClientError) as error:
            cliente.listar_casos(total_esperado=2)
        assert error.value.codigo is CodigoHistorial.DOCUMENTO_INCOMPLETO
        assert error.value.etapa is EtapaSigac.LISTADO_REPETIDO
        assert clasificar(error.value) == 'acceso'
        assert not cliente.autenticada


DESTINO_LOGIN = 'general.formCambiarTipoUsuario.con'
REDIRECCIONES_LOGIN = [
    ('ausente', [], CodigoHistorial.LOCATION_AUSENTE),
    ('vacio', [('location', '')], CodigoHistorial.LOCATION_AUSENTE),
    ('duplicado_igual', [('location', DESTINO_LOGIN)] * 2, CodigoHistorial.LOCATION_MULTIPLE),
    ('duplicado_distinto', [('Location', DESTINO_LOGIN), ('LOCATION', 'index.jsp')], CodigoHistorial.LOCATION_MULTIPLE),
    ('duplicado_vacio', [('location', ''), ('location', DESTINO_LOGIN)], CodigoHistorial.LOCATION_MULTIPLE),
    ('espacio', [('location', ' ' + DESTINO_LOGIN)], CodigoHistorial.REDIRECCION_FORMATO),
    ('url_malformada', [('location', 'https://[no-valido/')], CodigoHistorial.REDIRECCION_FORMATO),
    ('esquema_sin_host', [('location', 'https:/' + DESTINO_LOGIN)], CodigoHistorial.REDIRECCION_FORMATO),
    ('query', [('location', DESTINO_LOGIN + '?token=TOKEN_PRIVADO_FICTICIO')], CodigoHistorial.REDIRECCION_FORMATO),
    ('fragmento', [('location', DESTINO_LOGIN + '#FRAGMENTO_PRIVADO_FICTICIO')], CodigoHistorial.REDIRECCION_FORMATO),
    ('escape', [('location', DESTINO_LOGIN + '%20')], CodigoHistorial.REDIRECCION_FORMATO),
    ('barra_invertida', [('location', DESTINO_LOGIN + '\\')], CodigoHistorial.REDIRECCION_FORMATO),
    ('externo', [('location', 'https://ajeno.invalid/' + DESTINO_LOGIN)], CodigoHistorial.REDIRECCION_ORIGEN),
    ('http', [('location', BASE_URL.replace('https:', 'http:') + DESTINO_LOGIN)], CodigoHistorial.REDIRECCION_ORIGEN),
    ('sin_esquema', [('location', BASE_URL.removeprefix('https:') + DESTINO_LOGIN)], CodigoHistorial.REDIRECCION_ORIGEN),
    ('puerto_explicito', [('location', BASE_URL.replace('/sigac/', ':443/sigac/') + DESTINO_LOGIN)], CodigoHistorial.REDIRECCION_ORIGEN),
    ('host_mayusculas', [('location', BASE_URL.replace('sigac.udea.edu.co', 'SIGAC.UDEA.EDU.CO') + DESTINO_LOGIN)], CodigoHistorial.REDIRECCION_ORIGEN),
    ('acceso_relativo', [('location', 'index.jsp')], CodigoHistorial.REDIRECCION_ACCESO),
    ('acceso_raiz', [('location', '/sigac/index.jsp')], CodigoHistorial.REDIRECCION_ACCESO),
    ('acceso_absoluto', [('location', BASE_URL + 'index.jsp')], CodigoHistorial.REDIRECCION_ACCESO),
    ('otro_destino', [('location', 'DESTINO_PRIVADO_FICTICIO')], CodigoHistorial.REDIRECCION_DESTINO),
    ('prefijo_punto', [('location', './' + DESTINO_LOGIN)], CodigoHistorial.REDIRECCION_DESTINO),
    ('parametro_ruta', [('location', DESTINO_LOGIN + ';sesion=SESION_PRIVADA_FICTICIA')], CodigoHistorial.REDIRECCION_DESTINO),
]


def ejecutar_cli_login_simulado(monkeypatch, cliente):
    modulo = cargar_entrada()
    monkeypatch.setattr(modulo, 'SigacClient', lambda: cliente)
    monkeypatch.setattr(modulo.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda _: 'SIGAC-LECTURA')
    valores = iter([USUARIO, CLAVE])
    monkeypatch.setattr(modulo.getpass, 'getpass', lambda _: next(valores))
    nivel_anterior = logging.root.manager.disable
    try:
        return modulo.main(['--autorizar-sigac-real', '--diagnostico', '--tipo', TIPO,
                            '--total-casos', '2', '--indice-caso', '1', '--consultas', '2'])
    finally:
        logging.disable(nivel_anterior)


def comprobar_rechazo_login(monkeypatch, capsys, caplog, tmp_path, respuesta, codigo, etapa, conteos=None):
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.DEBUG)
    with cliente_servidor() as (cliente, servidor):
        servidor.cambios['sesion.validar.ses'] = respuesta
        assert ejecutar_cli_login_simulado(monkeypatch, cliente) == 1
        assert not cliente.autenticada and not cliente.http.cookies
        assert len(servidor.llamadas) == 2
    captura = capsys.readouterr()
    assert json.loads(captura.out) == diagnostico_seguro(codigo, conteos, etapa=etapa)
    assert captura.err == ''
    texto = captura.out + captura.err + caplog.text
    assert all(s not in texto for s in (
        USUARIO, CLAVE, COOKIE, 'TOKEN_PRIVADO_FICTICIO', 'FRAGMENTO_PRIVADO_FICTICIO',
        'DESTINO_PRIVADO_FICTICIO', 'SESION_PRIVADA_FICTICIA', 'sigac.udea.edu.co',
        'ajeno.invalid', 'Traceback', '<html>', 'Retry-After', DESTINO_LOGIN, 'index.jsp',
    ))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('nombre,cabeceras,codigo', REDIRECCIONES_LOGIN,
                         ids=[e[0] for e in REDIRECCIONES_LOGIN])
def test_causas_redireccion_login_v2(nombre, cabeceras, codigo, monkeypatch, capsys, caplog, tmp_path):
    # Una cookie presente no convierte un destino rechazado en acceso confirmado.
    respuesta = httpx.Response(302, headers=[*cabeceras,
        ('set-cookie', f'JSESSIONID={COOKIE}; Path=/sigac/; Secure; HttpOnly')], text=CLAVE + COOKIE)
    comprobar_rechazo_login(monkeypatch, capsys, caplog, tmp_path, respuesta,
                            codigo, EtapaSigac.REDIRECCION_LOGIN)


@pytest.mark.parametrize('estado', [201, 204, 301, 303, 307, 308, 400, 404, 429, 500, 502, 503, 504, 599])
def test_http_inesperado_login_no_reintenta(estado, monkeypatch, capsys, caplog, tmp_path):
    respuesta = httpx.Response(estado, headers={'location': DESTINO_LOGIN, 'retry-after': CLAVE}, text=CLAVE + COOKIE)
    comprobar_rechazo_login(monkeypatch, capsys, caplog, tmp_path, respuesta,
                            CodigoHistorial.HTTP_INESPERADO, EtapaSigac.LOGIN, {'http_estado': estado})


@pytest.mark.parametrize('estado', [200, 401, 403])
def test_login_no_confirmado_conserva_categoria(estado, monkeypatch, capsys, caplog, tmp_path):
    comprobar_rechazo_login(monkeypatch, capsys, caplog, tmp_path,
                            httpx.Response(estado, text=CLAVE + COOKIE),
                            CodigoHistorial.AUTENTICACION_NO_CONFIRMADA, EtapaSigac.LOGIN)


@pytest.mark.parametrize('destino', [DESTINO_LOGIN, '/sigac/' + DESTINO_LOGIN,
                                    BASE_URL + DESTINO_LOGIN, DESTINO_LOGIN + '?', DESTINO_LOGIN + '#',
                                    'general.principal.con', '/sigac/general.principal.con',
                                    BASE_URL + 'general.principal.con'],
                         ids=['relativo', 'raiz', 'absoluto', 'query_vacia', 'fragmento_vacio',
                              'principal_relativa', 'principal_raiz', 'principal_absoluta'])
def test_destinos_admitidos_conservan_recorrido_nueve_solicitudes(destino, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    with cliente_servidor() as (cliente, servidor):
        servidor.cambios['sesion.validar.ses'] = httpx.Response(302, headers={
            'Location': destino, 'set-cookie': f'JSESSIONID={COOKIE}; Path=/sigac/; Secure; HttpOnly'})
        assert ejecutar_cli_login_simulado(monkeypatch, cliente) == 0
        # El CLI cierra el cliente y borra las cookies incluso tras el éxito.
        assert not cliente.autenticada and not cliente.http.cookies
        assert cliente.rol_activo_confirmado is False
        assert len(servidor.llamadas) == 9
        assert sum(p.url.path.endswith('casos.formCaso.con') for p in servidor.llamadas) == 2
    datos = json.loads(capsys.readouterr().out)
    assert datos['diagnostico_version'] == 2 and datos['categoria'] == 'lectura_estable'
    assert datos['consultas_historial'] == 2 and datos['completitud'] == 'completitud_no_verificada'
    assert datos['eventos_baseline'] == datos['eventos_posteriores'] == 0
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('valor', [True, False, '429', -1, 0, 99, 600, 999999999, None])
def test_http_estado_solo_admite_entero_en_rango(valor):
    assert diagnostico_seguro(CodigoHistorial.HTTP_INESPERADO, {'http_estado': valor})['estadisticas_estructurales'] == {}


@pytest.mark.parametrize('estado', [100, 429, 500, 599])
def test_http_estado_pertenece_al_catalogo_cerrado(estado):
    from tinotify.parsers.diagnostico_historial import CLAVES_CONTEOS
    datos = diagnostico_seguro(CodigoHistorial.HTTP_INESPERADO, {'http_estado': estado, COOKIE: CLAVE})
    assert datos['estadisticas_estructurales'] == {'http_estado': estado}
    assert set(datos['estadisticas_estructurales']) <= set(CLAVES_CONTEOS)


@pytest.mark.parametrize('control', ['\r', '\n', '\r\n', '\x00', '\t'])
def test_controles_location_rechazados_por_validador(control):
    # HTTPX puede rechazar estos bytes antes de entregar la respuesta al cliente:
    # en ese caso se conserva fallo_transporte_o_codificacion / envio_login.
    from tinotify.integrations.sigac.sigac_respuestas import RespuestaIncompleta, destino_login_confirmado
    with pytest.raises(RespuestaIncompleta) as error:
        destino_login_confirmado(httpx.Headers({'location': DESTINO_LOGIN + control}))
    assert error.value.codigo is CodigoHistorial.REDIRECCION_FORMATO


@pytest.mark.parametrize('nombre,cabeceras,codigo', REDIRECCIONES_LOGIN,
                         ids=[e[0] for e in REDIRECCIONES_LOGIN])
def test_diagnostico_login_no_amplia_aceptacion(nombre, cabeceras, codigo):
    from tinotify.integrations.sigac.sigac_respuestas import (
        RespuestaIncompleta, destino_confirmado, destino_login_confirmado,
    )
    headers = httpx.Headers(cabeceras)
    with pytest.raises(RespuestaIncompleta) as anterior:
        destino_confirmado(headers.get('location', ''), {DESTINO_LOGIN})
    assert anterior.value.codigo is CodigoHistorial.REDIRECCION_NO_CONFIRMADA
    with pytest.raises(RespuestaIncompleta) as nuevo:
        destino_login_confirmado(headers)
    assert nuevo.value.codigo is codigo


@pytest.fixture(params=[DESTINO_LOGIN, 'general.principal.con'], ids=['login_selector', 'login_principal'])
def doble_recorrido(request):
    servidor = Servidor()
    servidor.cambios['sesion.validar.ses'] = httpx.Response(302, headers={
        'location': request.param, 'set-cookie': f'JSESSIONID={COOKIE}; Path=/sigac/; Secure; HttpOnly'})
    with cliente_servidor(servidor) as (cliente, _):
        yield cliente, servidor


def test_ambos_logins_convergen_en_seis_solicitudes(doble_recorrido, monkeypatch):
    cliente, servidor = doble_recorrido
    original = cliente._solicitar
    def solicitar(*args, **kwargs):
        assert not cliente.autenticada and not cliente._confirmada
        assert cliente.rol_activo_confirmado is False
        return original(*args, **kwargs)
    monkeypatch.setattr(cliente, '_solicitar', solicitar)
    casos = autenticar(cliente)
    assert len(casos) == 2 and cliente.autenticada
    assert cliente.rol_activo_confirmado is False
    assert [(p.method, p.url.path.removeprefix('/sigac/')) for p in servidor.llamadas] == [
        ('GET', 'index.jsp'), ('POST', 'sesion.validar.ses'),
        ('GET', DESTINO_LOGIN), ('POST', 'sesion.cambiar.ses'),
        ('GET', 'general.principal.con'), ('GET', 'casos.seleccionarCasos.con'),
    ]
    assert servidor.llamadas[3].content == b'chkTipoUsuario=ESTUDIANTE&cmdAceptar=Aceptar'


FALLOS_DOBLE_RECORRIDO = [
    ('selector_sin_estudiante', DESTINO_LOGIN, html(ROLES.replace('ESTUDIANTE', 'ASISTENTE_ASESOR')),
     CodigoHistorial.ROL_NO_OFRECIDO, EtapaSigac.SELECTOR_ROL, 3),
    ('selector_campos_invalidos', DESTINO_LOGIN, html(ROLES.replace('name="cmdAceptar"', 'name="NO_CONFIRMADO"')),
     CodigoHistorial.FORMULARIO_CAMPOS_INVALIDOS, EtapaSigac.SELECTOR_ROL, 3),
    ('selector_metodo_invalido', DESTINO_LOGIN, html(ROLES.replace('method="post"', 'method="get"')),
     CodigoHistorial.FORMULARIO_METODO_INVALIDO, EtapaSigac.SELECTOR_ROL, 3),
    ('selector_redirige_principal', DESTINO_LOGIN, httpx.Response(302, headers={'location': 'general.principal.con'}),
     CodigoHistorial.SESION_NO_CONFIRMADA, EtapaSigac.SELECTOR_ROL, 3),
    ('selector_expirado', DESTINO_LOGIN, html(ACCESO),
     CodigoHistorial.SESION_NO_CONFIRMADA, EtapaSigac.SELECTOR_ROL, 3),
    ('seleccion_rechazada', 'sesion.cambiar.ses', httpx.Response(403, text=CLAVE + COOKIE),
     CodigoHistorial.SESION_NO_CONFIRMADA, EtapaSigac.ENVIO_ROL, 4),
    ('seleccion_error', 'sesion.cambiar.ses', httpx.Response(500, text=CLAVE + COOKIE),
     CodigoHistorial.ROL_RESPUESTA_INVALIDA, EtapaSigac.ENVIO_ROL, 4),
    ('seleccion_sin_redireccion', 'sesion.cambiar.ses', html(ROLES),
     CodigoHistorial.ROL_RESPUESTA_INVALIDA, EtapaSigac.ENVIO_ROL, 4),
    ('seleccion_retorna_selector', 'sesion.cambiar.ses', httpx.Response(302, headers={'location': DESTINO_LOGIN}),
     CodigoHistorial.REDIRECCION_NO_CONFIRMADA, EtapaSigac.REDIRECCION_ROL, 4),
    ('seleccion_externa', 'sesion.cambiar.ses', httpx.Response(302, headers={'location': 'https://ajeno.invalid/'}),
     CodigoHistorial.REDIRECCION_NO_CONFIRMADA, EtapaSigac.REDIRECCION_ROL, 4),
    ('seleccion_duplicada', 'sesion.cambiar.ses', httpx.Response(302, headers=[('location', 'general.principal.con')] * 2),
     CodigoHistorial.REDIRECCION_NO_CONFIRMADA, EtapaSigac.REDIRECCION_ROL, 4),
    ('seleccion_ignorada_visible', 'general.principal.con', html(ROLES),
     CodigoHistorial.SESION_NO_CONFIRMADA, EtapaSigac.PRINCIPAL, 5),
    ('principal_acceso', 'general.principal.con', html(ACCESO),
     CodigoHistorial.SESION_NO_CONFIRMADA, EtapaSigac.PRINCIPAL, 5),
    ('principal_error', 'general.principal.con', httpx.Response(500, text=CLAVE + COOKIE),
     CodigoHistorial.HTTP_INVALIDO, EtapaSigac.PRINCIPAL, 5),
    ('principal_incompleta', 'general.principal.con', html(pagina('FICTICIO').removesuffix('</html>')),
     CodigoHistorial.DOCUMENTO_INCOMPLETO, EtapaSigac.PRINCIPAL, 5),
    ('principal_sesion_expirada', 'general.principal.con', httpx.Response(302, headers={'location': 'index.jsp'}),
     CodigoHistorial.SESION_NO_CONFIRMADA, EtapaSigac.PRINCIPAL, 5),
    ('listado_acceso', 'casos.seleccionarCasos.con', html(ACCESO),
     CodigoHistorial.SESION_NO_CONFIRMADA, EtapaSigac.LISTADO_INICIAL, 6),
    ('listado_rol_no_confirmado', 'casos.seleccionarCasos.con', html(ROLES),
     CodigoHistorial.SESION_NO_CONFIRMADA, EtapaSigac.LISTADO_INICIAL, 6),
    ('listado_error', 'casos.seleccionarCasos.con', httpx.Response(500, text=CLAVE + COOKIE),
     CodigoHistorial.HTTP_INVALIDO, EtapaSigac.LISTADO_INICIAL, 6),
    ('listado_incompleto', 'casos.seleccionarCasos.con', html(LISTADO.removesuffix('</html>')),
     CodigoHistorial.DOCUMENTO_INCOMPLETO, EtapaSigac.LISTADO_INICIAL, 6),
    ('listado_parcial', 'casos.seleccionarCasos.con', html(LISTADO.replace(fila_caso(202), '')),
     CodigoHistorial.LISTADO_NO_CONFIRMADO, EtapaSigac.LISTADO_INICIAL, 6),
]


@pytest.mark.parametrize('nombre,ruta,respuesta,codigo,etapa,peticiones', FALLOS_DOBLE_RECORRIDO,
                         ids=[e[0] for e in FALLOS_DOBLE_RECORRIDO])
def test_fallos_ambos_recorridos_invalidan_sesion(doble_recorrido, nombre, ruta, respuesta, codigo, etapa, peticiones):
    cliente, servidor = doble_recorrido
    servidor.cambios[ruta] = respuesta
    with pytest.raises(SigacClientError) as error:
        autenticar(cliente)
    assert error.value.codigo is codigo and error.value.etapa is etapa
    assert not cliente.autenticada and not cliente.http.cookies and not cliente._casos
    assert cliente.rol_activo_confirmado is False
    assert len(servidor.llamadas) == peticiones <= 6
    texto = ''.join(traceback.format_exception(error.value))
    assert all(v not in texto for v in (USUARIO, CLAVE, COOKIE, 'ajeno.invalid'))


@pytest.mark.parametrize('cookie', [None, 'OTRA=FICTICIO; Path=/sigac/',
    'JSESSIONID=FICTICIO; Domain=ajeno.invalid; Path=/sigac/',
    'JSESSIONID=FICTICIO; Path=/otra/', 'JSESSIONID=FICTICIO; Max-Age=0; Path=/sigac/',
    'JSESSIONID=FICTICIO; Path=/sigac/general.principal.con'])
def test_cookie_login_debe_aplicar_al_selector(doble_recorrido, cookie):
    cliente, servidor = doble_recorrido
    destino = servidor.cambios['sesion.validar.ses'].headers['location']
    cabeceras = {'location': destino}
    if cookie:
        cabeceras['set-cookie'] = cookie
    servidor.cambios['sesion.validar.ses'] = httpx.Response(302, headers=cabeceras)
    with pytest.raises(SigacClientError) as error:
        autenticar(cliente)
    assert error.value.codigo is CodigoHistorial.SESION_NO_CONFIRMADA
    assert error.value.etapa is EtapaSigac.SESION
    assert len(servidor.llamadas) == 2
    assert not cliente.http.cookies and not cliente.autenticada


def test_cookie_expirada_tras_seleccion_impide_listado(doble_recorrido):
    cliente, servidor = doble_recorrido
    def principal(_):
        cliente.http.cookies.clear()
        return html(pagina('PRINCIPAL_FICTICIA'))
    servidor.cambios['general.principal.con'] = principal
    with pytest.raises(SigacClientError):
        autenticar(cliente)
    assert len(servidor.llamadas) == 5
    assert not cliente.http.cookies and not cliente.autenticada and not cliente._casos


@pytest.mark.parametrize('fallo', [RuntimeError(CLAVE + COOKIE), UserWarning(CLAVE + COOKIE), KeyboardInterrupt()])
def test_fallo_interno_limpia_sin_depender_del_cierre(doble_recorrido, fallo):
    cliente, servidor = doble_recorrido
    def principal(_):
        raise fallo
    servidor.cambios['general.principal.con'] = principal
    with pytest.raises(type(fallo)):
        autenticar(cliente)
    assert len(servidor.llamadas) == 5
    assert not cliente.http.cookies and not cliente.autenticada and not cliente._casos


def test_seleccion_ignorada_indistinguible_no_confirma_rol(doble_recorrido):
    # Modelo adverso: el servidor no cambia su rol, pero devuelve exactamente
    # el mismo contrato observable y permite el listado. No hay señal de rol.
    cliente, servidor = doble_recorrido
    rol_servidor = 'ASISTENTE_ASESOR'
    def ignorar_seleccion(_):
        assert rol_servidor == 'ASISTENTE_ASESOR'
        return httpx.Response(302, headers={'location': 'general.principal.con'})
    servidor.cambios['sesion.cambiar.ses'] = ignorar_seleccion
    autenticar(cliente)
    assert cliente.autenticada  # Solo acceso al recurso, nunca prueba del rol.
    assert cliente.rol_activo_confirmado is False
    assert len(servidor.llamadas) == 6


def test_ensayo_completo_ambos_recorridos_nueve_solicitudes(doble_recorrido, monkeypatch, capsys, caplog, tmp_path):
    cliente, servidor = doble_recorrido
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.DEBUG)
    assert ejecutar_cli_login_simulado(monkeypatch, cliente) == 0
    salida = capsys.readouterr()
    datos = json.loads(salida.out)
    assert datos['lectura_funcional'] is True and datos['consultas_historial'] == 2
    assert datos['completitud'] == 'completitud_no_verificada'
    assert datos['eventos_baseline'] == datos['eventos_posteriores'] == 0
    assert len(servidor.llamadas) == 9
    assert sum(p.url.path.endswith('casos.formCaso.con') for p in servidor.llamadas) == 2
    assert salida.err == ''
    assert all(v not in salida.out + caplog.text for v in (USUARIO, CLAVE, COOKIE,
        'sigac.udea.edu.co', 'CONTENIDO_FICTICIO', 'Traceback', '<html>'))
    assert cliente.rol_activo_confirmado is False and not cliente.http.cookies
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('destino', [
    './general.principal.con', 'general.principal.con;dato=FICTICIO',
    'general.principal.con?dato=FICTICIO', 'general.principal.con#FICTICIO',
    'general.principal.con%20', '../general.principal.con',
    'https://ajeno.invalid/general.principal.con',
    BASE_URL.replace('https:', 'http:') + 'general.principal.con',
    BASE_URL.replace('/sigac/', ':443/sigac/') + 'general.principal.con',
])
def test_variantes_principal_no_se_admiten(destino):
    servidor = Servidor()
    servidor.cambios['sesion.validar.ses'] = httpx.Response(302, headers={
        'location': destino, 'set-cookie': f'JSESSIONID={COOKIE}; Path=/sigac/; Secure; HttpOnly'})
    with cliente_servidor(servidor) as (cliente, _):
        with pytest.raises(SigacClientError):
            autenticar(cliente)
        assert len(servidor.llamadas) == 2
        assert not cliente.autenticada and not cliente.http.cookies


@pytest.mark.parametrize('nombre,ruta,respuesta,codigo,etapa,peticiones', [
    caso for caso in FALLOS_DOBLE_RECORRIDO if caso[0] in (
        'selector_sin_estudiante', 'selector_campos_invalidos', 'seleccion_rechazada',
        'seleccion_ignorada_visible', 'principal_error', 'listado_acceso', 'listado_incompleto',
    )
], ids=lambda valor: valor if isinstance(valor, str) else None)
def test_cli_fallos_ambos_recorridos_sin_filtraciones(doble_recorrido, nombre, ruta, respuesta, codigo,
                                                     etapa, peticiones, monkeypatch, capsys, caplog, tmp_path):
    cliente, servidor = doble_recorrido
    servidor.cambios[ruta] = respuesta
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.DEBUG)
    assert ejecutar_cli_login_simulado(monkeypatch, cliente) == 1
    captura = capsys.readouterr()
    datos = json.loads(captura.out)
    assert datos['diagnostico_version'] == 2 and datos['categoria'] == codigo.value
    assert datos['etapa'] == etapa.value and datos.get('lectura_funcional') is not True
    assert datos.get('rol_activo_confirmado') is not True
    assert len(servidor.llamadas) == peticiones <= 6
    assert not cliente.http.cookies and not cliente.autenticada
    assert captura.err == ''
    assert all(v not in captura.out + caplog.text for v in (USUARIO, CLAVE, COOKIE,
        'sigac.udea.edu.co', 'CONTENIDO_FICTICIO', 'RESPONSABLE_FICTICIO', 'Traceback', '<html>'))
    assert not list(tmp_path.iterdir())
