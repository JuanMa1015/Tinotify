"""Observación aislada con solicitudes, credenciales y respuestas ficticias."""

from contextlib import contextmanager
import importlib.util
import json
import logging
from pathlib import Path
import socket
import sqlite3
from urllib.parse import parse_qs
import warnings

import httpx
import pytest

from tinotify.integrations.sigac.sigac_client import BASE_URL, SigacClient, SigacClientError
from tinotify.integrations.sigac.observacion_login import TipoDestinoLogin
from tinotify.parsers.diagnostico_historial import CodigoHistorial, EtapaSigac


USUARIO = 'USUARIO_OBSERVACION_FICTICIO'
CLAVE = 'CLAVE_OBSERVACION_FICTICIA'
COOKIE = 'COOKIE_OBSERVACION_FICTICIA'
PRIVADO = 'CONTENIDO_PRIVADO_FICTICIO'
SELECTOR = 'general.formCambiarTipoUsuario.con'
ACCESO = '''<html><body><form action="sesion.validar.ses" method="post">
<select name="cboTipo"><option value="1">FICTICIO</option></select>
<input name="txtUsuario"><input name="txtCaso" value="CASO_FORMULARIO_FICTICIO">
<input type="password" name="txtClave"><input name="cmdIngresar" value="BOTON_FICTICIO">
</form></body></html>'''


@pytest.fixture(autouse=True)
def aislado(monkeypatch, tmp_path):
    def prohibido(*args, **kwargs):
        pytest.fail('Red y persistencia prohibidas en observación simulada')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket, 'getaddrinfo', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)
    monkeypatch.setattr(sqlite3, 'connect', prohibido)
    monkeypatch.chdir(tmp_path)
    yield
    assert not list(tmp_path.iterdir())


@contextmanager
def escenario(respuesta, *, fallo=None, cookie=True, formulario=ACCESO):
    llamadas = []
    cliente = None

    def servidor(peticion):
        assert not cliente._confirmada
        llamadas.append((peticion.method, peticion.url.path))
        assert len(llamadas) <= 2
        logging.getLogger('httpcore.prueba').debug(PRIVADO + COOKIE)
        if fallo and len(llamadas) == fallo[0]:
            if isinstance(fallo[1], Warning):
                warnings.warn(fallo[1])
            else:
                raise fallo[1]
        if len(llamadas) == 1:
            assert llamadas[-1] == ('GET', '/sigac/index.jsp')
            assert 'cookie' not in peticion.headers
            cabeceras = {'content-type': 'text/html'}
            if cookie:
                cabeceras['set-cookie'] = f'JSESSIONID={COOKIE}; Path=/sigac/; Secure; HttpOnly'
            return httpx.Response(200, text=formulario, headers=cabeceras)
        assert llamadas[-1] == ('POST', '/sigac/sesion.validar.ses')
        assert peticion.headers['content-type'] == 'application/x-www-form-urlencoded'
        assert parse_qs(peticion.content.decode()) == {
            'cboTipo': ['1'], 'txtUsuario': [USUARIO], 'txtClave': [CLAVE],
            'txtCaso': ['CASO_FORMULARIO_FICTICIO'], 'cmdIngresar': ['BOTON_FICTICIO'],
        }
        return respuesta

    # Incluso con seguimiento habilitado en el cliente inyectado, el flujo
    # existente impone follow_redirects=False a cada solicitud.
    with httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(servidor), follow_redirects=True) as http:
        cliente = SigacClient(http)
        http.cookies.set('JSESSIONID', 'COOKIE_ANTERIOR_FICTICIA', domain='sigac.udea.edu.co', path='/sigac/')
        try:
            yield cliente, llamadas
        finally:
            assert not cliente.autenticada and not cliente._confirmada
            assert not cliente._casos and not http.cookies
            cliente.cerrar()


def observar(cliente):
    return cliente.observar_redireccion_login(USUARIO, CLAVE, tipo='1')


def respuesta_login(destino):
    return httpx.Response(302, headers={'location': destino,
        'set-cookie': f'JSESSIONID={COOKIE}; Path=/sigac/; Secure; HttpOnly'}, text=PRIVADO)


@pytest.mark.parametrize('ruta,categoria', [
    ('index.jsp', TipoDestinoLogin.ACCESO), (SELECTOR, TipoDestinoLogin.SELECTOR),
    ('general.principal.con', TipoDestinoLogin.PRINCIPAL), ('general.menu.con', TipoDestinoLogin.MENU),
])
@pytest.mark.parametrize('prefijo', ['', '/sigac/', BASE_URL], ids=['relativo', 'raiz', 'absoluto'])
def test_destinos_conocidos_sin_seguimiento(ruta, categoria, prefijo):
    with escenario(respuesta_login(prefijo + ruta)) as (cliente, llamadas):
        datos = observar(cliente)
        assert datos == {
            'diagnostico_version': 2, 'etapa': 'redireccion_login', 'categoria': categoria.value,
            'indicadores': {'prefijo_punto': False, 'parametros_en_ruta': False,
                            'ruta_fuera_ambito_esperado': False, 'variante_conocida': False},
            'autenticacion_confirmada': False, 'redireccion_seguida': False,
        }
        assert len(llamadas) == 2


@pytest.mark.parametrize('ruta,categoria,indicadores', [
    ('./' + SELECTOR, TipoDestinoLogin.SELECTOR, (True, False, False, True)),
    (SELECTOR + ';sesion=' + PRIVADO, TipoDestinoLogin.SELECTOR, (False, True, False, True)),
    ('./index.jsp;dato=' + PRIVADO, TipoDestinoLogin.ACCESO, (True, True, False, True)),
    ('DESTINO_' + PRIVADO, TipoDestinoLogin.DESCONOCIDO, (False, False, False, False)),
    ('/otro/index.jsp', TipoDestinoLogin.DESCONOCIDO, (False, False, True, False)),
    ('../index.jsp', TipoDestinoLogin.DESCONOCIDO, (False, False, True, False)),
    ('././index.jsp', TipoDestinoLogin.DESCONOCIDO, (True, False, False, False)),
    (SELECTOR + ';dato/otro', TipoDestinoLogin.DESCONOCIDO, (False, True, False, False)),
])
def test_variantes_solo_comparacion_lexica(ruta, categoria, indicadores):
    with escenario(respuesta_login(ruta)) as (cliente, llamadas):
        datos = observar(cliente)
        assert datos['categoria'] == categoria.value
        assert tuple(datos['indicadores'].values()) == indicadores
        assert len(llamadas) == 2
        assert PRIVADO not in json.dumps(datos)


@pytest.mark.parametrize('sufijo', ['?', '#'])
def test_delimitadores_vacios_conservan_comportamiento(sufijo):
    with escenario(respuesta_login(SELECTOR + sufijo)) as (cliente, llamadas):
        assert observar(cliente)['categoria'] == TipoDestinoLogin.SELECTOR.value
        assert len(llamadas) == 2


@pytest.mark.parametrize('cabeceras,codigo', [
    ([], CodigoHistorial.LOCATION_AUSENTE),
    ([('location', '')], CodigoHistorial.LOCATION_AUSENTE),
    ([('location', SELECTOR)] * 2, CodigoHistorial.LOCATION_MULTIPLE),
    ([('location', 'https://ajeno.invalid/' + PRIVADO)], CodigoHistorial.REDIRECCION_ORIGEN),
    ([('location', BASE_URL.replace('https:', 'http:') + SELECTOR)], CodigoHistorial.REDIRECCION_ORIGEN),
    ([('location', BASE_URL.removeprefix('https:') + SELECTOR)], CodigoHistorial.REDIRECCION_ORIGEN),
    ([('location', SELECTOR + '?dato=' + PRIVADO)], CodigoHistorial.REDIRECCION_FORMATO),
    ([('location', SELECTOR + '#' + PRIVADO)], CodigoHistorial.REDIRECCION_FORMATO),
    ([('location', SELECTOR + '%20')], CodigoHistorial.REDIRECCION_FORMATO),
    ([('location', ' ' + SELECTOR)], CodigoHistorial.REDIRECCION_FORMATO),
])
def test_rechazos_limpian_cookies(cabeceras, codigo):
    with escenario(httpx.Response(302, headers=cabeceras)) as (cliente, llamadas):
        with pytest.raises(SigacClientError) as error:
            observar(cliente)
        assert error.value.codigo is codigo
        assert error.value.etapa is EtapaSigac.REDIRECCION_LOGIN
        assert len(llamadas) == 2


@pytest.mark.parametrize('estado', [200, 301, 303, 307, 308, 401, 403, 429, 500, 503])
def test_no_302_no_clasifica_destino_ni_reintenta(estado):
    with escenario(httpx.Response(estado, headers={'location': SELECTOR})) as (cliente, llamadas):
        with pytest.raises(SigacClientError) as error:
            observar(cliente)
        esperado = CodigoHistorial.AUTENTICACION_NO_CONFIRMADA if estado in (200, 401, 403) else CodigoHistorial.HTTP_INESPERADO
        assert error.value.codigo is esperado and error.value.etapa is EtapaSigac.LOGIN
        assert len(llamadas) == 2


@pytest.mark.parametrize('cookie', [True, False])
def test_observar_no_requiere_cookie_ni_confirma_sesion(cookie):
    with escenario(httpx.Response(302, headers={'location': SELECTOR}), cookie=cookie) as (cliente, llamadas):
        assert observar(cliente)['autenticacion_confirmada'] is False
        assert len(llamadas) == 2


def test_observacion_invalida_confirmacion_previa():
    with escenario(respuesta_login(SELECTOR)) as (cliente, llamadas):
        cliente._confirmada = True
        cliente._casos = {'CASO_PREVIO_FICTICIO'}
        assert observar(cliente)['autenticacion_confirmada'] is False
        assert len(llamadas) == 2


@pytest.mark.parametrize('formulario,codigo', [
    (ACCESO.removesuffix('</body></html>'), CodigoHistorial.DOCUMENTO_INCOMPLETO),
    (ACCESO.replace('value="1"', 'value="OPCION_DISTINTA"'), CodigoHistorial.TIPO_NO_OFRECIDO),
    (ACCESO.replace('method="post"', 'method="get"'), CodigoHistorial.FORMULARIO_METODO_INVALIDO),
    (ACCESO.replace('name="txtClave"', 'name="NO_CONFIRMADO"'), CodigoHistorial.FORMULARIO_CAMPOS_INVALIDOS),
])
def test_formulario_no_confirmado_impide_post(formulario, codigo):
    with escenario(respuesta_login(SELECTOR), formulario=formulario) as (cliente, llamadas):
        with pytest.raises(SigacClientError) as error:
            observar(cliente)
        assert error.value.codigo is codigo and error.value.etapa is EtapaSigac.FORMULARIO
        assert len(llamadas) == 1


@pytest.mark.parametrize('campo', ['usuario', 'clave', 'tipo'])
def test_entradas_vacias_no_abren_solicitudes(campo):
    with escenario(respuesta_login(SELECTOR)) as (cliente, llamadas):
        datos = {'usuario': USUARIO, 'clave': CLAVE, 'tipo': '1'}
        datos[campo] = ''
        with pytest.raises(SigacClientError) as error:
            cliente.observar_redireccion_login(**datos)
        assert error.value.codigo is CodigoHistorial.ACCESO_INCOMPLETO
        assert error.value.etapa is EtapaSigac.PREPARACION
        assert not llamadas


@pytest.mark.parametrize('ruta,codigo', [
    ('general.menu.con', CodigoHistorial.REDIRECCION_DESTINO),
    ('./' + SELECTOR, CodigoHistorial.REDIRECCION_DESTINO),
    (SELECTOR + ';dato=' + PRIVADO, CodigoHistorial.REDIRECCION_DESTINO),
    ('DESCONOCIDO_' + PRIVADO, CodigoHistorial.REDIRECCION_DESTINO),
    ('index.jsp', CodigoHistorial.REDIRECCION_ACCESO),
])
def test_catalogo_observado_no_amplia_autenticacion(ruta, codigo):
    with escenario(respuesta_login(ruta)) as (cliente, llamadas):
        with pytest.raises(SigacClientError) as error:
            cliente.autenticar(USUARIO, CLAVE, tipo='1', total_casos_esperado=15)
        assert error.value.codigo is codigo and error.value.etapa is EtapaSigac.REDIRECCION_LOGIN
        assert len(llamadas) == 2


def cargar_entrada():
    ruta = Path(__file__).resolve().parents[1] / 'scripts' / 'observar_login_sigac.py'
    spec = importlib.util.spec_from_file_location('entrada_observacion', ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def ejecutar_cli(monkeypatch, cliente):
    modulo = cargar_entrada()
    monkeypatch.setattr(modulo, 'SigacClient', lambda: cliente)
    monkeypatch.setattr(modulo.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda _: 'SIGAC-OBSERVAR-LOGIN')
    entradas = iter([USUARIO, CLAVE])
    monkeypatch.setattr(modulo.getpass, 'getpass', lambda _: next(entradas))
    return modulo.main(['--autorizar-sigac-real', '--tipo', '1'])


@pytest.mark.parametrize('destino,categoria', [
    ('index.jsp', 'retorno_acceso'), (SELECTOR, 'selector_rol'),
    ('general.principal.con', 'principal_conocida_fuera_de_etapa'),
    ('general.menu.con', 'menu_conocido_fuera_de_etapa'),
    ('DESCONOCIDO_' + PRIVADO, 'destino_desconocido'),
    ('./index.jsp;dato=' + PRIVADO, 'retorno_acceso'),
])
def test_cli_clasifica_sin_filtraciones(destino, categoria, monkeypatch, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    nivel_anterior = logging.root.manager.disable
    with escenario(respuesta_login(destino)) as (cliente, llamadas):
        assert ejecutar_cli(monkeypatch, cliente) == 0
        assert len(llamadas) == 2
    salida = capsys.readouterr()
    datos = json.loads(salida.out)
    assert datos['categoria'] == categoria
    assert datos['autenticacion_confirmada'] is False and datos['redireccion_seguida'] is False
    assert salida.err == ''
    texto = salida.out + salida.err + caplog.text
    assert all(v not in texto for v in (USUARIO, CLAVE, COOKIE, PRIVADO, SELECTOR,
                                       'index.jsp', 'sigac.udea.edu.co', 'http', '<html', 'Traceback'))
    assert logging.root.manager.disable == nivel_anterior


@pytest.mark.parametrize('respuesta,categoria', [
    (httpx.Response(302), 'location_ausente'),
    (httpx.Response(302, headers=[('location', SELECTOR)] * 2), 'location_multiple'),
    (respuesta_login('https://ajeno.invalid/' + PRIVADO), 'redireccion_origen_no_admitido'),
    (respuesta_login(SELECTOR + '?dato=' + PRIVADO), 'redireccion_formato_no_admitido'),
    (httpx.Response(429, headers={'retry-after': PRIVADO}, text=PRIVADO), 'respuesta_http_inesperada'),
    (httpx.Response(503, text=PRIVADO), 'respuesta_http_inesperada'),
    (httpx.Response(401, text=PRIVADO), 'autenticacion_no_confirmada'),
])
def test_cli_rechazos_sin_filtraciones(respuesta, categoria, monkeypatch, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    with escenario(respuesta) as (cliente, llamadas):
        assert ejecutar_cli(monkeypatch, cliente) == 1
        assert len(llamadas) == 2
    captura = capsys.readouterr()
    datos = json.loads(captura.out)
    assert datos['categoria'] == categoria and datos['diagnostico_version'] == 2
    assert datos['etapa'] == ('redireccion_login' if respuesta.status_code == 302 else 'envio_login')
    assert captura.err == ''
    texto = captura.out + caplog.text
    assert all(v not in texto for v in (USUARIO, CLAVE, COOKIE, PRIVADO, SELECTOR,
                                       'ajeno.invalid', 'sigac.udea.edu.co', 'https://', '<html', 'Traceback'))


@pytest.mark.parametrize('paso', [1, 2])
@pytest.mark.parametrize('error,categoria,salida', [
    (httpx.ConnectError(PRIVADO), 'fallo_transporte_o_codificacion', 1),
    (RuntimeError(PRIVADO), 'error_interno', 1),
    (UserWarning(PRIVADO), 'advertencia_biblioteca', 1),
    (KeyboardInterrupt(PRIVADO), 'entrada_ensayo_invalida', 130),
])
def test_cli_fallos_e_interrupciones_limpian(paso, error, categoria, salida, monkeypatch, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    with escenario(respuesta_login(SELECTOR), fallo=(paso, error)) as (cliente, llamadas):
        assert ejecutar_cli(monkeypatch, cliente) == salida
        assert len(llamadas) == paso
    captura = capsys.readouterr()
    datos = json.loads(captura.out)
    assert datos['categoria'] == categoria
    assert datos['etapa'] == ('formulario_acceso' if paso == 1 else 'envio_login')
    assert captura.err == ''
    assert all(v not in captura.out + caplog.text for v in (USUARIO, CLAVE, COOKIE, PRIVADO, 'http', 'Traceback'))


@pytest.mark.parametrize('modo', ['sin_flag', 'sin_terminal', 'cancelado', 'argumento_desconocido'])
def test_cli_sin_autorizacion_no_crea_cliente_ni_pide_credenciales(modo, monkeypatch, capsys):
    modulo = cargar_entrada()
    def prohibido(*args, **kwargs):
        pytest.fail('No se permite crear cliente ni leer credenciales')
    monkeypatch.setattr(modulo, 'SigacClient', prohibido)
    monkeypatch.setattr(modulo.getpass, 'getpass', prohibido)
    monkeypatch.setattr(modulo.sys.stdin, 'isatty', lambda: modo != 'sin_terminal')
    monkeypatch.setattr('builtins.input', lambda _: PRIVADO)
    args = ['--tipo', '1']
    if modo != 'sin_flag':
        args.append('--autorizar-sigac-real')
    if modo == 'argumento_desconocido':
        args.extend(['--desconocido', PRIVADO])
    if modo == 'cancelado':
        assert modulo.main(args) == 2
    else:
        with pytest.raises(SystemExit) as error:
            modulo.main(args)
        assert error.value.code == 2
    captura = capsys.readouterr()
    assert json.loads(captura.out)['categoria'] == 'entrada_ensayo_invalida'
    assert captura.err == '' and PRIVADO not in captura.out
