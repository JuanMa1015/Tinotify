"""Únicamente HTTP simulado y datos sintéticos; bloquea sockets reales."""

import importlib.util
import json
import logging
from pathlib import Path
import socket
from urllib.parse import parse_qs
import warnings

import httpx
import pytest

from tinotify.integrations.sigac.sigac_client import BASE_URL
from tinotify.services.continuidad_expedientes_sigac import (
    _ClienteContinuidad, _NumeroObservado, _representaciones, ejecutar_continuidad,
)


USUARIO = "USUARIO_SINTETICO_NO_REAL"
CLAVE = "CLAVE_SINTETICA_NO_REAL"
COOKIE = "COOKIE_SINTETICA_NO_REAL"
NOMBRE = "NOMBRE_SINTETICO_NO_REAL"


def pagina(texto):
    return f"<html><body>{texto}</body></html>"


ACCESO = pagina('''<form action="sesion.validar.ses" method="post">
<select name="cboTipo"><option value="2">Consultorio</option></select>
<input name="txtUsuario"><input name="txtCaso" value="">
<input type="password" name="txtClave"><input type="submit" name="cmdIngresar" value="Ingresar">
</form>''')
SELECTOR = pagina('''<form action="sesion.cambiar.ses" method="post">
<input type="radio" name="chkTipoUsuario" value="ESTUDIANTE">
<input type="submit" name="cmdAceptar" value="Aceptar"></form>''')


def fila(numero="101", argumento=None):
    argumento = numero if argumento is None else argumento
    return (f'<tr class="fila_enlace" onclick="abrir({argumento})"><td>{numero}</td>'
            f'<td>{NOMBRE}</td><td>ESTADO SINTETICO</td></tr>')


def listado(*filas):
    return pagina('<table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr>' + ''.join(filas) + '</table>')


NORMAL = listado(fila(), fila("202"))


def html(texto):
    return httpx.Response(200, text=texto, headers={"content-type": "text/html; charset=utf-8"})


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("No se permite red real")
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket.socket, "connect", prohibido)


class FabricaSimulada:
    def __init__(self, respuestas=None, fallo=None, sesion_fallida=1, destino="general.principal.con"):
        self.respuestas = respuestas or [NORMAL, NORMAL]
        self.fallo = fallo
        self.sesion_fallida = sesion_fallida
        self.destino = destino
        self.clientes = []
        self.solicitudes = []

    def __call__(self):
        # La segunda sesión solo puede nacer tras cerrar y limpiar la primera.
        self.comprobar_cierre()
        indice = len(self.clientes)
        cookie = f"{COOKIE}_{indice}"

        def responder(peticion):
            self.solicitudes.append((indice, peticion))
            ruta = peticion.url.path.removeprefix("/sigac/")
            if ruta == "index.jsp":
                assert "cookie" not in peticion.headers
                return html(ACCESO)
            if ruta == "sesion.validar.ses":
                assert "cookie" not in peticion.headers
                datos = parse_qs(peticion.content.decode(), keep_blank_values=True)
                assert datos == {"cboTipo": ["2"], "txtUsuario": [USUARIO], "txtClave": [CLAVE],
                                 "txtCaso": [""], "cmdIngresar": ["Ingresar"]}
                if self.fallo == "autenticacion" and indice == self.sesion_fallida:
                    return httpx.Response(401, text=CLAVE)
                return httpx.Response(302, headers={"location": self.destino,
                    "set-cookie": f"JSESSIONID={cookie}; Path=/sigac/; Secure; HttpOnly"})
            assert peticion.headers.get("cookie") == f"JSESSIONID={cookie}"
            if ruta == "general.formCambiarTipoUsuario.con":
                return html(SELECTOR)
            if ruta == "sesion.cambiar.ses":
                assert peticion.content == b"chkTipoUsuario=ESTUDIANTE&cmdAceptar=Aceptar"
                return httpx.Response(302, headers={"location": "general.principal.con"})
            if ruta == "general.principal.con":
                return html(pagina("PRINCIPAL SINTETICA"))
            if ruta == "casos.seleccionarCasos.con":
                assert peticion.method == "GET"
                assert peticion.url.query == b"motivo=ACTUAR_ESTUDIANTE"
                if indice == self.sesion_fallida:
                    if self.fallo == "sesion":
                        return httpx.Response(302, headers={"location": "index.jsp"})
                    if self.fallo == "red":
                        raise httpx.ConnectError(CLAVE, request=peticion)
                    if self.fallo == "http":
                        return httpx.Response(503, text=CLAVE)
                return html(self.respuestas[indice])
            pytest.fail("Solicitud ajena al ensayo: no admite historiales ni descargas")

        http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(responder), follow_redirects=False)
        cliente = _ClienteContinuidad(2, http)
        self.clientes.append(cliente)
        return cliente

    def comprobar_cierre(self):
        for cliente in self.clientes:
            assert cliente.http.is_closed
            assert not cliente.http.cookies
            assert not cliente.autenticada and not cliente._casos
            assert cliente.observados is None


def ejecutar(fabrica):
    resultado = ejecutar_continuidad(USUARIO, CLAVE, total_casos=2, fabrica=fabrica)
    fabrica.comprobar_cierre()
    assert all("casos.formCaso.con" not in str(p.url) and "descargarAnexo" not in str(p.url)
               for _, p in fabrica.solicitudes)
    assert len(fabrica.solicitudes) <= 12
    return resultado


@pytest.mark.parametrize("destino", ["general.principal.con", "general.formCambiarTipoUsuario.con"])
@pytest.mark.parametrize("segunda", [NORMAL, listado(fila("202"), fila()), NORMAL.replace(NOMBRE, "OTRA ETIQUETA")])
def test_continuidad_dos_sesiones_independientes_sin_historial(segunda, destino):
    fabrica = FabricaSimulada([NORMAL, segunda], destino=destino)
    resultado = ejecutar(fabrica)
    assert resultado == {
        "sesiones": [{"autenticacion": True, "cantidad_expedientes": 2, "identificadores_unicos": True}] * 2,
        "igualdad_conjuntos": True, "identificadores_anadidos": 0, "identificadores_ausentes": 0,
        "diferencias_representacion": False, "clasificacion": "continuidad_observada",
    }
    assert [i for i, _ in fabrica.solicitudes] == [0] * 6 + [1] * 6
    assert len({id(c.http) for c in fabrica.clientes}) == 2


@pytest.mark.parametrize("segunda", [
    listado(fila("00101", "101"), fila("202")),
    listado(fila("101", "00101"), fila("202")),
    listado(fila("00101"), fila("202")),
    listado(fila(" 101 ", "101"), fila("202")),
])
def test_ceros_o_espacios_distintos_no_demuestran_representacion_continua(segunda):
    resultado = ejecutar(FabricaSimulada([NORMAL, segunda]))
    assert resultado["clasificacion"] == "inconcluso"
    assert resultado["igualdad_conjuntos"] is True
    assert resultado["diferencias_representacion"] is True
    assert resultado["identificadores_anadidos"] == resultado["identificadores_ausentes"] == 0


def test_cambio_conjunto_no_empareja_por_nombre():
    resultado = ejecutar(FabricaSimulada([NORMAL, listado(fila(), fila("303"))]))
    assert resultado["clasificacion"] == "inconcluso"
    assert resultado["igualdad_conjuntos"] is False
    assert resultado["identificadores_anadidos"] == resultado["identificadores_ausentes"] == 1
    assert resultado["diferencias_representacion"] is False


@pytest.mark.parametrize("sesion", [0, 1])
@pytest.mark.parametrize("invalido", [
    listado(fila(), fila()),
    listado(fila("101"), fila("00101")),
    listado(fila(), fila("", "202")),
    listado(fila()),
    listado(fila(), fila("202", "303")),
    NORMAL.replace("</body>", "<table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr></table></body>"),
    NORMAL.removesuffix("</html>"),
])
def test_listados_invalidos_abortan_sin_comparacion(sesion, invalido):
    respuestas = [NORMAL, NORMAL]
    respuestas[sesion] = invalido
    fabrica = FabricaSimulada(respuestas)
    resultado = ejecutar(fabrica)
    assert resultado["clasificacion"] == "error"
    assert resultado["igualdad_conjuntos"] is None
    assert resultado["identificadores_anadidos"] is None
    assert resultado["sesiones"][sesion]["autenticacion"] is False
    assert len(fabrica.clientes) == sesion + 1
    if sesion == 0:
        assert resultado["sesiones"][1]["autenticacion"] is None


@pytest.mark.parametrize("fallo", ["autenticacion", "sesion", "red", "http"])
@pytest.mark.parametrize("sesion", [0, 1])
def test_fallos_de_sesion_o_transporte_no_reintentan(fallo, sesion):
    fabrica = FabricaSimulada(fallo=fallo, sesion_fallida=sesion)
    resultado = ejecutar(fabrica)
    assert resultado["clasificacion"] == "error" and resultado["igualdad_conjuntos"] is None
    assert len(fabrica.clientes) == sesion + 1
    assert len(fabrica.solicitudes) == sesion * 6 + (2 if fallo == "autenticacion" else 6)


def test_representacion_original_solo_en_memoria_no_repr():
    observados = _representaciones(listado(fila(" 00101 ", "00101"), fila("202")), 2)
    assert observados[0].numero == 101
    assert observados[0].texto == " 00101 " and observados[0].argumento == "00101"
    assert repr(_NumeroObservado(101, "00101", "00101")) == "_NumeroObservado()"


def test_bloqueo_de_solicitudes_adicionales_antes_del_transporte():
    fabrica = FabricaSimulada()
    with fabrica() as cliente:
        cliente.autenticar(USUARIO, CLAVE, tipo="2", total_casos_esperado=2)
        for metodo, ruta in [("GET", "casos.formCaso.con"), ("GET", "general.descargarAnexo.con"),
                             ("GET", "index.jsp")]:
            with pytest.raises(ValueError):
                cliente._solicitar(metodo, ruta)
        assert len(fabrica.solicitudes) == 6
    fabrica.comprobar_cierre()


def cargar_script():
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "continuidad_expedientes_sigac.py"
    spec = importlib.util.spec_from_file_location("entrada_continuidad", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def preparar_cli(monkeypatch, fabrica):
    modulo = cargar_script()
    monkeypatch.setattr(modulo.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "SIGAC-CONTINUIDAD")
    entradas = iter([USUARIO, CLAVE])
    monkeypatch.setattr(modulo.getpass, "getpass", lambda _: next(entradas))
    monkeypatch.setattr(modulo, "ejecutar_continuidad", lambda *a, **kw: ejecutar_continuidad(*a, **kw, fabrica=fabrica))
    return modulo


ARGS = ["--autorizar-sigac-real", "--tipo", "2", "--total-casos", "2"]


@pytest.mark.parametrize("fallo", [None, "autenticacion", "sesion", "red", "http"])
def test_salida_logs_y_disco_no_contienen_datos(monkeypatch, capsys, caplog, tmp_path, fallo):
    monkeypatch.chdir(tmp_path)
    fabrica = FabricaSimulada(fallo=fallo)
    modulo = preparar_cli(monkeypatch, fabrica)
    with caplog.at_level(logging.DEBUG):
        assert modulo.main(ARGS) == (0 if fallo is None else 1)
    salida = capsys.readouterr()
    datos = json.loads(salida.out)
    assert datos["clasificacion"] == ("continuidad_observada" if fallo is None else "error")
    for secreto in (USUARIO, CLAVE, COOKIE, NOMBRE, "101", "202", "https://", "JSESSIONID", "<html>"):
        assert secreto not in salida.out + salida.err + caplog.text
    assert list(tmp_path.iterdir()) == []
    fabrica.comprobar_cierre()


@pytest.mark.parametrize("modo", ["sin_flag", "cancelar", "sin_tty", "sin_eco", "tipo_invalido"])
def test_guardas_no_conectan(monkeypatch, capsys, modo):
    fabrica = FabricaSimulada()
    modulo = preparar_cli(monkeypatch, fabrica)
    argumentos = ARGS.copy()
    if modo == "sin_flag":
        argumentos = argumentos[1:]
    elif modo == "cancelar":
        monkeypatch.setattr("builtins.input", lambda _: "NO")
    elif modo == "sin_tty":
        monkeypatch.setattr(modulo.sys.stdin, "isatty", lambda: False)
    elif modo == "tipo_invalido":
        argumentos[2] = "1"
    else:
        def aviso(_):
            warnings.warn(CLAVE, modulo.getpass.GetPassWarning)
        monkeypatch.setattr(modulo.getpass, "getpass", aviso)
    if modo in ("sin_flag", "sin_tty", "tipo_invalido"):
        with pytest.raises(SystemExit):
            modulo.main(argumentos)
    else:
        assert modulo.main(argumentos) == (2 if modo == "cancelar" else 1)
    assert not fabrica.clientes and not fabrica.solicitudes
    assert CLAVE not in str(capsys.readouterr())
