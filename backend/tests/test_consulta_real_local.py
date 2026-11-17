"""Consulta real autorizada → persistencia local → API protegida.

Todo es sintético: ningún servicio remoto ni credencial real. La fixture sirve
HTML ficticio mediante MockTransport al cliente estricto y obtiene su acreditación.
Se conservan los rechazos de las entradas antiguas y de archivos incompatibles.
"""

from dataclasses import replace
from html import escape
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from tinotify.api.demo import crear_app
from tinotify.api.real_local import AccesoLocal
from tinotify.demo.novedades import (
    INSTANCIA_REAL, ObservacionRechazada, ServicioNovedadesLocal, html_historial_sintetico,
)
from tinotify.demo.push import ExpoPush
from tinotify.demo.servicio import ServicioDemo
from tinotify.domain.actuaciones import Anexo
from tinotify.integrations.sigac.sigac_client import SigacClientError
from tinotify.parsers.parser import parse_actuaciones
from tinotify.persistence.sqlite_local import AlmacenLocalNoDisponible, AlmacenSqliteLocal
from tinotify.services.consulta_real_local import caso_local, consultar_expediente, etiqueta_valida
from tinotify.services.consulta_real_local import IdentidadExpedienteNoVerificada
from tinotify.integrations.sigac.lectura_validada import leer_historial_validado
from backend.tests.helpers.sigac_detalle import detalle
from backend.tests.test_sigac_flujo import cliente_servidor, html, pagina, fila_caso, USUARIO as USUARIO_HTTP, CLAVE as CLAVE_HTTP, COOKIE as COOKIE_HTTP, TIPO
from backend.tests.test_sqlite_local_v2 import snapshot


RAIZ = Path(__file__).resolve().parents[1]
CODIGO = "CODIGO-LOCAL-FICTICIO-" + "x" * 20   # 42 caracteres; no es un secreto real
USUARIO, CLAVE, CASO_LOGIN = "USUARIO_FICTICIO_XYZ", "CLAVE_FICTICIA_NO_REAL_XYZ", "TXTCASO_FICTICIO_XYZ"
NUMERO = 424242


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("Estas pruebas no deben abrir conexiones")
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)


def historial(n):
    return tuple(parse_actuaciones(html_historial_sintetico(n), "CASO_FICTICIO"))


class ClienteFalso:
    """Doble del cliente SIGAC: registra las llamadas y nunca abre red."""

    def __init__(self, *historiales, numeros=(NUMERO, 1, 2)):
        self.historiales, self.numeros, self.llamadas = list(historiales), numeros, []

    def autenticar(self, usuario, clave, *, tipo, total_casos_esperado, caso_login=None):
        self.llamadas.append("autenticar")
        return [SimpleNamespace(numero=n) for n in self.numeros]

    def consultar_historial(self, numero, *, total_esperado=None, contenedor_id=None):
        self.llamadas.append(("historial", numero))
        siguiente = self.historiales.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "real.sqlite3"


def servicio_de(ruta):
    return ServicioNovedadesLocal(AlmacenSqliteLocal(ruta, perfil="real"), instancia=INSTANCIA_REAL)


def consultar(servicio, cliente, **extra):
    """Fixture: atraviesa HTTP estricto y la fábrica real de acreditaciones.

    ClienteFalso es únicamente un guion sintético; nunca se hace pasar por un
    SigacClient ni fabrica la acreditación. El número solicitado es explícito.
    """
    con_lista = '<table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr>'
    con_lista += ''.join(fila_caso(n) for n in cliente.numeros) + '</table>'
    valor = cliente.historiales.pop(0)
    cuerpo = '<table>'
    if not isinstance(valor, Exception):
        for a in valor:
            cuerpo += '<tr><td colspan="2"><hr></td></tr>'
            direccion = a.direccion if a.origen or a.destino else ''
            cuerpo += f'<tr><td>{escape(a.etapa)}</td><td>{escape(direccion)}</td></tr>'
            cuerpo += f'<tr><td>{a.fecha:%Y-%m-%d %H:%M:%S}</td><td>{escape(a.remitente)}</td></tr>'
            filas = (json.loads(a.descripcion.removeprefix('TINOTIFY_FILAS_V1:'))['filas']
                     if a.descripcion.startswith('TINOTIFY_FILAS_V1:') else [('Actuación', a.descripcion)])
            cuerpo += ''.join(f'<tr><td>{escape(e)}:</td><td>{escape(t)}</td></tr>' for e, t in filas)
            if a.anexos:
                cuerpo += '<tr><td>Anexos:</td><td><table id="tablaAnexos">'
                cuerpo += ''.join(f'<tr><td>{escape(x.descripcion)}</td><td><a href="{escape(x.referencia, quote=True)}">'
                                  f'{escape(x.archivo)}</a></td></tr>' for x in a.anexos)
                cuerpo += '</table></td></tr>'
    cuerpo += '</table>'
    with cliente_servidor() as (http, servidor):
        servidor.cambios['casos.seleccionarCasos.con'] = html(pagina(con_lista))
        servidor.cambios['casos.formCaso.con'] = html(detalle(cuerpo, numero=NUMERO))
        http.autenticar(USUARIO_HTTP, CLAVE_HTTP, tipo=TIPO, total_casos_esperado=len(cliente.numeros))
        lectura = leer_historial_validado(http, NUMERO, total_esperado=extra.get('total_actuaciones'))
    return servicio.observar_validada(lectura, clave=uuid4(), generacion_esperada=servicio.generacion(caso_local(NUMERO)))


def instantanea(servicio):
    return snapshot(servicio), servicio.almacen.ruta.read_bytes()


# --- Flujo funcional ---------------------------------------------------------------------------------------

def test_baseline_real_simulado_sin_avisos(ruta):
    s = servicio_de(ruta)
    r = consultar(s, ClienteFalso(historial(3)))
    assert r['baseline'] and r['novedades_nuevas'] == 0
    assert s.observaciones()['observaciones'] == []
    (caso,) = s.listar_casos()
    assert caso['id'] == caso_local(NUMERO) and caso['ocurrencias_observadas'] == 3
    assert caso['cobertura'] == 'desconocida' and caso['entrega_externa'] == 'no_autorizada'
    with pytest.raises(PermissionError):
        s.novedades()


def test_primera_observacion_posterior_es_interna_sin_afirmar_creacion(ruta):
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3)))
    r = consultar(s, ClienteFalso(historial(4)))
    assert not r['baseline'] and r['novedades_nuevas'] == 1
    (n,) = s.observaciones()['observaciones']
    assert n['tipo'] == 'primera_observacion' and n['creacion_reciente_acreditada'] is False
    ocurrencias = s.detalle(caso_local(NUMERO))['ocurrencias']
    assert len(ocurrencias) == 4 and n['local_id'] in {a['local_id'] for a in ocurrencias}
    assert all('nueva' not in a and 'descripcion' not in a for a in ocurrencias)


def test_repeticion_sin_duplicados_y_reinicio_del_proceso(ruta):
    consultar(servicio_de(ruta), ClienteFalso(historial(3)))
    consultar(servicio_de(ruta), ClienteFalso(historial(4)))
    reiniciado = servicio_de(ruta)
    assert consultar(reiniciado, ClienteFalso(historial(4)))['novedades_nuevas'] == 0
    assert consultar(reiniciado, ClienteFalso(historial(4)))['novedades_nuevas'] == 0
    assert len(reiniciado.observaciones()['observaciones']) == 1
    assert reiniciado.listar_casos()[0]['ocurrencias_observadas'] == 4


def test_total_contrastado_no_acredita_cobertura_completa(ruta):
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3)), total_actuaciones=3)
    assert s.observaciones()['cobertura'] == 'desconocida'
    assert s.detalle(caso_local(NUMERO))['referencia'] == 'ocurrencias_observadas'


def test_el_identificador_local_depende_del_expediente_y_no_de_la_posicion(ruta):
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3), numeros=(NUMERO, 1, 2)))
    consultar(s, ClienteFalso(historial(4), numeros=(1, 2, NUMERO)))
    assert [c['id'] for c in s.listar_casos()] == [caso_local(NUMERO)]
    assert len(s.observaciones()['observaciones']) == 1
    assert caso_local(NUMERO) != caso_local(NUMERO + 1)
    with pytest.raises(ValueError):
        caso_local(0)


# --- Extracciones rechazadas, parciales o sospechosas no reemplazan un baseline ------------------------------------

def test_extraccion_rechazada_en_la_primera_consulta_no_crea_baseline(ruta):
    s = servicio_de(ruta)
    antes = instantanea(s)
    with pytest.raises(SigacClientError):
        consultar(s, ClienteFalso(SigacClientError('Historial ficticio incompleto')))
    assert instantanea(s) == antes
    assert s.listar_casos() == [] and s.observaciones()['observaciones'] == []


def test_extraccion_rechazada_posterior_no_cambia_nada(ruta):
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3))), consultar(s, ClienteFalso(historial(4)))
    antes = instantanea(s)
    with pytest.raises(SigacClientError):
        consultar(s, ClienteFalso(SigacClientError("Historial incompleto.")))
    assert instantanea(s) == antes


@pytest.mark.parametrize("variante", ["menos_actuaciones", "actuacion_modificada", "anexo_con_referencia_volatil",
                                      "vacia"])
def test_observacion_sospechosa_no_reemplaza_el_baseline(ruta, variante):
    s = servicio_de(ruta)
    base = historial(3)
    con_anexo = (base[0], base[1], replace(base[2], anexos=(Anexo("D", "a.pdf", "general.descargarAnexo.con?codigo=A1"),)))
    consultar(s, ClienteFalso(con_anexo))
    antes = instantanea(s)
    observacion = {
        "menos_actuaciones": con_anexo[:2],
        "actuacion_modificada": (con_anexo[0], replace(con_anexo[1], descripcion="Texto cambiado."), con_anexo[2]),
        # Mismo contenido pero la referencia del anexo cambió entre sesiones: no se puede identificar.
        "anexo_con_referencia_volatil": (*con_anexo[:2], replace(con_anexo[2], anexos=(
            Anexo("D", "a.pdf", "general.descargarAnexo.con?codigo=B2"),)), historial(4)[3]),
        "vacia": (),
    }[variante]
    esperado = SigacClientError if variante == 'vacia' else ObservacionRechazada
    with pytest.raises(esperado) as error:
        consultar(s, ClienteFalso(observacion))
    assert instantanea(s) == antes
    assert "Texto cambiado" not in str(error.value) and "codigo=" not in str(error.value)


def test_entrada_por_indice_se_rechaza_incluso_con_posicion_valida(ruta):
    cliente = ClienteFalso(historial(3))
    s = servicio_de(ruta)
    antes = instantanea(s)
    for indice in (0, 1, 4, -1):
        with pytest.raises(IdentidadExpedienteNoVerificada):
            consultar_expediente(cliente, USUARIO, CLAVE, tipo='T', total_casos=3, indice_caso=indice, servicio=s)
    assert cliente.llamadas == [] and instantanea(s) == antes


def test_etiqueta_predeterminada_y_no_validas(ruta):
    assert etiqueta_valida(None) == etiqueta_valida('') == 'Expediente SIGAC'
    for etiqueta in ('   ', 'x' * 61, 'con\ncontrol'):
        with pytest.raises(ValueError):
            etiqueta_valida(etiqueta)


def test_texto_multifila_se_conserva_en_memoria_y_no_se_persiste_en_real(ruta):
    html = ('<table><tr><td colspan="2"><hr></td></tr><tr><td>2026-03-01 10:00:00</td><td>REMITENTE_FICTICIO</td></tr>'
            '<tr><td>Reparto :</td><td>VALOR_REPARTO</td></tr><tr><td>Actuación :</td><td>TEXTO_ACTUACION</td></tr></table>')
    actos = tuple(parse_actuaciones(html, 'CASO_FICTICIO'))
    assert 'VALOR_REPARTO' in actos[0].descripcion and 'TEXTO_ACTUACION' in actos[0].descripcion
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(actos))
    detalle = s.detalle(caso_local(NUMERO))
    assert len(detalle['ocurrencias']) == 1 and 'actuaciones' not in detalle
    assert b'VALOR_REPARTO' not in ruta.read_bytes() and b'TEXTO_ACTUACION' not in ruta.read_bytes()


# --- Secretos y HTML ------------------------------------------------------------------------------------------------

def test_credenciales_html_y_cookies_no_llegan_a_la_persistencia_ni_a_las_respuestas(ruta):
    s = servicio_de(ruta)
    resumen = consultar(s, ClienteFalso(historial(3)))
    consultar(s, ClienteFalso(historial(4)))
    with TestClient(crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push(), real=s, acceso_real=AccesoLocal(CODIGO))) as c:
        h = {"Authorization": "Bearer " + CODIGO}
        cuerpos = [json.dumps(resumen), c.get("/real/cases", headers=h).text, c.get("/real/observaciones", headers=h).text,
                   c.get(f"/real/cases/{caso_local(NUMERO)}", headers=h).text]
    contenido = ruta.read_bytes()
    for secreto in (USUARIO, CLAVE, USUARIO_HTTP, CLAVE_HTTP, COOKIE_HTTP, CASO_LOGIN, "JSESSIONID", CODIGO, str(NUMERO)):
        assert secreto.encode() not in contenido
        assert all(secreto not in cuerpo for cuerpo in cuerpos if secreto != CODIGO)
    for marca in (b"<table", b"<form", b"<hr>", b"form1"):
        assert marca not in contenido
    for prohibido in ("huella", "version_hash", "source_id", "descripcion", "remitente", "codigo="):
        assert all(prohibido not in cuerpo for cuerpo in cuerpos)


def _push():
    return ExpoPush(transport=httpx.MockTransport(lambda r: pytest.fail('No se permiten entregas en consultas locales')))


# --- Separación entre datos sintéticos y reales ---------------------------------------------------------------------

def test_un_archivo_no_se_puede_abrir_con_el_perfil_equivocado(tmp_path):
    real, sintetico = tmp_path / "r.sqlite3", tmp_path / "s.sqlite3"
    AlmacenSqliteLocal(real, perfil="real"), AlmacenSqliteLocal(sintetico)
    with pytest.raises(AlmacenLocalNoDisponible):
        AlmacenSqliteLocal(real)
    with pytest.raises(AlmacenLocalNoDisponible):
        AlmacenSqliteLocal(sintetico, perfil="real")
    AlmacenSqliteLocal(real, perfil="real"), AlmacenSqliteLocal(sintetico, perfil="sintetico")  # reabrir sigue bien
    with pytest.raises(ValueError):
        AlmacenSqliteLocal(tmp_path / "x.sqlite3", perfil="otro")


def test_archivo_sin_perfil_se_rechaza_sin_reparacion(tmp_path):
    import sqlite3
    antiguo = tmp_path / 'antiguo.sqlite3'
    AlmacenSqliteLocal(antiguo)
    with sqlite3.connect(antiguo) as c:
        c.execute("DELETE FROM meta WHERE clave='perfil'")
    raw = antiguo.read_bytes()
    for opciones in ({}, {'perfil': 'real'}):
        with pytest.raises(AlmacenLocalNoDisponible):
            AlmacenSqliteLocal(antiguo, **opciones)
        assert antiguo.read_bytes() == raw


def test_el_servicio_real_y_el_sintetico_no_comparten_datos(tmp_path):
    real = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "r.sqlite3", perfil="real"), instancia=INSTANCIA_REAL)
    sintetico = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "s.sqlite3"))
    sintetico.observar_html("00000000-0000-4000-8000-0000000000c1", html_historial_sintetico(3))
    assert real.listar_casos() == [] and real.sintetico is False and sintetico.sintetico is True
    consultar(real, ClienteFalso(historial(3)))
    assert [c["id"] for c in sintetico.listar_casos()] == ["00000000-0000-4000-8000-0000000000c1"]
    assert sintetico.listar_casos()[0]["demo"] is True and real.listar_casos()[0]['cobertura'] == 'desconocida'


def test_las_rutas_abiertas_de_demo_no_exponen_datos_reales(ruta, tmp_path, monkeypatch):
    consultar(servicio_de(ruta), ClienteFalso(historial(3)))
    monkeypatch.setenv("TINOTIFY_LOCAL_DB", str(tmp_path / "sintetica.sqlite3"))
    monkeypatch.setenv("TINOTIFY_REAL_DB", str(ruta))
    monkeypatch.setenv("TINOTIFY_REAL_ACCESS_CODE", CODIGO)
    with TestClient(crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push())) as c:
        assert c.get("/demo/local/cases").json() == [] and c.get("/demo/local/novedades").json() == []
        assert caso_local(NUMERO) not in c.get("/demo/catalog/cases").text
        assert len(c.get("/real/cases", headers={"Authorization": "Bearer " + CODIGO}).json()) == 1


def test_apuntar_la_base_sintetica_al_archivo_real_impide_arrancar(ruta, tmp_path, monkeypatch):
    servicio_de(ruta)
    monkeypatch.setenv("TINOTIFY_LOCAL_DB", str(ruta))
    with pytest.raises(AlmacenLocalNoDisponible):
        crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push())


# --- Acceso protegido a los endpoints reales -------------------------------------------------------------------------

def cliente_real(servicio, acceso=None):
    return TestClient(crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push(), real=servicio,
                                acceso_real=acceso or AccesoLocal(CODIGO)))


RUTAS_REALES = ["/real/cases", f"/real/cases/{caso_local(NUMERO)}", "/real/novedades", "/real/observaciones"]


@pytest.mark.parametrize("ruta_api", RUTAS_REALES)
def test_sin_credencial_o_con_credencial_incorrecta_se_rechaza(ruta, ruta_api):
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3)))
    with cliente_real(s) as c:
        for cabeceras in ({}, {"Authorization": "Bearer incorrecto"}, {"Authorization": "Basic " + CODIGO},
                          {"Authorization": "Bearer " + CODIGO + "x"}, {"Authorization": "Bearer "}):
            r = c.get(ruta_api, headers=cabeceras)
            assert r.status_code == 401 and r.json() == {"detail": "Acceso local requerido"}
            assert r.headers["www-authenticate"] == "Bearer"
            assert caso_local(NUMERO) not in r.text


def test_con_el_codigo_correcto_responde_sin_cache(ruta):
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3))), consultar(s, ClienteFalso(historial(4)))
    with cliente_real(s) as c:
        h = {'Authorization': 'Bearer ' + CODIGO}
        r = c.get('/real/cases', headers=h)
        assert r.status_code == 200 and r.headers['cache-control'] == 'no-store'
        assert r.json()[0]['cobertura'] == 'desconocida'
        d = c.get(f'/real/cases/{caso_local(NUMERO)}', headers=h).json()
        assert d['referencia_establecida'] and d['ocurrencias_observadas'] == 4
        assert all(set(a) == {'local_id', 'generacion'} for a in d['ocurrencias'])
        (n,) = c.get('/real/observaciones', headers=h).json()['observaciones']
        assert n['caso'] == d['id'] and n['creacion_reciente_acreditada'] is False
        retirada = c.get('/real/novedades', headers=h)
        assert retirada.status_code == 410 and retirada.headers['cache-control'] == 'no-store'


def test_consultar_por_la_api_nunca_procesa_avisos(ruta):
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3))), consultar(s, ClienteFalso(historial(4)))
    antes = instantanea(s)
    with cliente_real(s) as c:
        for _ in range(3):
            for ruta_api in RUTAS_REALES:
                c.get(ruta_api, headers={'Authorization': 'Bearer ' + CODIGO})
    assert instantanea(s) == antes
    assert len(servicio_de(ruta).observaciones()['observaciones']) == 1


def test_caso_inexistente_e_identificador_invalido_requieren_acceso_y_son_genericos(ruta):
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3)))
    with cliente_real(s) as c:
        h = {"Authorization": "Bearer " + CODIGO}
        assert c.get(f"/real/cases/{uuid4()}").status_code == 401
        r = c.get(f"/real/cases/{uuid4()}", headers=h)
        assert r.status_code == 404 and r.json() == {"detail": "Proceso no disponible"}
        assert c.get("/real/cases/no-es-uuid", headers=h).status_code == 422


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("ruta_api", RUTAS_REALES)
def test_no_hay_endpoints_de_escritura_ni_de_consulta_real(ruta, metodo, ruta_api):
    with cliente_real(servicio_de(ruta)) as c:
        assert getattr(c, metodo)(ruta_api, headers={"Authorization": "Bearer " + CODIGO}).status_code == 405


def test_limite_de_intentos_fallidos_bloquea_incluso_el_codigo_correcto(ruta):
    reloj = [0.0]
    acceso = AccesoLocal(CODIGO, reloj=lambda: reloj[0], max_fallos=3, ventana=60.0)
    with cliente_real(servicio_de(ruta), acceso) as c:
        for _ in range(3):
            assert c.get("/real/cases", headers={"Authorization": "Bearer mal"}).status_code == 401
        bloqueado = c.get("/real/cases", headers={"Authorization": "Bearer " + CODIGO})
        assert bloqueado.status_code == 429 and bloqueado.json() == {"detail": "Demasiados intentos; espera un minuto"}
        reloj[0] += 61
        assert c.get("/real/cases", headers={"Authorization": "Bearer " + CODIGO}).status_code == 200


def test_el_codigo_de_acceso_exige_longitud_y_configuracion_completa(ruta, tmp_path, monkeypatch):
    for corto in ("", "corto", "x" * 31, " " + "x" * 40):
        with pytest.raises(ValueError):
            AccesoLocal(corto)
    monkeypatch.setenv("TINOTIFY_REAL_DB", str(ruta))
    monkeypatch.delenv("TINOTIFY_REAL_ACCESS_CODE", raising=False)
    with pytest.raises(RuntimeError):
        crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push())
    monkeypatch.delenv("TINOTIFY_REAL_DB")
    monkeypatch.setenv("TINOTIFY_REAL_ACCESS_CODE", CODIGO)
    with pytest.raises(RuntimeError):
        crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push())
    monkeypatch.setenv("TINOTIFY_REAL_DB", str(ruta))
    monkeypatch.setenv("TINOTIFY_REAL_ACCESS_CODE", "corto")
    with pytest.raises(ValueError):
        crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push())


def test_sin_configuracion_las_rutas_reales_no_existen(monkeypatch):
    monkeypatch.delenv("TINOTIFY_REAL_DB", raising=False)
    monkeypatch.delenv("TINOTIFY_REAL_ACCESS_CODE", raising=False)
    with TestClient(crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push())) as c:
        for ruta_api in RUTAS_REALES:
            assert c.get(ruta_api, headers={"Authorization": "Bearer " + CODIGO}).status_code == 404


def test_un_almacen_sintetico_no_puede_servirse_como_real(tmp_path):
    sintetico = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "s.sqlite3"))
    with pytest.raises(ValueError):
        crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push(), real=sintetico, acceso_real=AccesoLocal(CODIGO))
    with pytest.raises(RuntimeError):
        crear_app(ServicioDemo(("A" * 32, "B" * 32)), _push(), real=servicio_de(tmp_path / "r.sqlite3"))


def test_la_api_de_produccion_no_tiene_rutas_demo_ni_reales():
    from tinotify.api import app
    rutas = {r.path for r in app.routes}
    assert not any(p.startswith(("/demo", "/real")) for p in rutas) and "/health" in rutas


def test_la_api_no_importa_el_cliente_sigac_ni_puede_iniciar_consultas_reales():
    codigo = ("import sys, tinotify.api.demo, tinotify.api.real_local;"
              "print('tinotify.integrations.sigac.sigac_client' in sys.modules,"
              "'tinotify.services.consulta_real_local' in sys.modules)")
    salida = subprocess.run([sys.executable, "-B", "-c", codigo], capture_output=True, text=True, timeout=60).stdout
    assert salida.split() == ["False", "False"]
    for modulo in ("api/real_local.py", "api/demo.py"):
        fuente = (RAIZ / "src" / "tinotify" / modulo).read_text(encoding="utf-8")
        assert "SigacClient" not in fuente and "consultar_expediente" not in fuente


# --- Herramienta CLI --------------------------------------------------------------------------------------------------

def cargar_cli():
    spec = importlib.util.spec_from_file_location("sigac_local_cli", RAIZ / "scripts" / "sigac_local.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TerminalFalsa:
    def isatty(self):
        return True


@pytest.fixture
def cli(monkeypatch):
    modulo = cargar_cli()
    monkeypatch.setattr(sys, "stdin", TerminalFalsa())
    construido = []

    class ClienteContexto(ClienteFalso):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fabrica(*historiales):
        cliente = ClienteContexto(*historiales)
        construido.append(cliente)
        return cliente
    return modulo, construido, fabrica


def argumentos(ruta, *extra):
    return ["--db", str(ruta), "consultar", "--autorizar-sigac-real", "--tipo", "TIPO_FICTICIO", "--total-casos", "3",
            "--caso-numero", "101", *extra]


def test_cli_exige_bandera_terminal_y_no_pide_confirmacion_mientras_bloqueado(ruta, cli, monkeypatch, capsys):
    modulo, construido, fabrica = cli
    monkeypatch.setattr(modulo, 'SigacClient', lambda: pytest.fail('No abrir cliente SIGAC'))
    monkeypatch.setattr('builtins.input', lambda _: pytest.fail('No pedir confirmacion mientras esta bloqueado'))
    with pytest.raises(SystemExit) as salida:
        modulo.main(['--db', str(ruta), 'consultar', '--tipo', 'T', '--total-casos', '3'])
    assert salida.value.code == 2
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit) as salida:
        modulo.main(argumentos(ruta))
    assert salida.value.code == 2
    monkeypatch.setattr(sys, 'stdin', TerminalFalsa())
    assert modulo.main(argumentos(ruta)) == 4
    assert 'bloqueada' in capsys.readouterr().out and not ruta.exists() and construido == []


def test_cli_bloqueado_no_pide_credenciales_y_estado_solo_muestra_referencia(ruta, cli, monkeypatch, capsys):
    modulo, construido, fabrica = cli
    monkeypatch.setattr(modulo.getpass, 'getpass', lambda _: pytest.fail('No pedir credenciales'))
    monkeypatch.setattr(modulo, 'SigacClient', lambda: pytest.fail('No abrir cliente'))
    assert modulo.main(argumentos(ruta, '--pedir-caso-login', '--etiqueta', 'Mi expediente')) == 4
    assert not ruta.exists() and construido == []
    capsys.readouterr()
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3)))
    assert modulo.main(['--db', str(ruta), 'estado']) == 0
    salida = capsys.readouterr().out
    estado = json.loads(salida)
    assert estado['cobertura'] == 'desconocida' and estado['observaciones_internas'] == 0
    assert estado['casos'][0]['ocurrencias_observadas'] == 3 and 'id' not in estado['casos'][0]
    assert all(secreto not in salida for secreto in (USUARIO, CLAVE, CASO_LOGIN, str(NUMERO)))


def test_cli_bloqueado_no_consulta_ni_modifica_referencia_existente(ruta, cli, monkeypatch, capsys):
    modulo, construido, fabrica = cli
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3)))
    antes = instantanea(s)
    monkeypatch.setattr(modulo.getpass, 'getpass', lambda _: pytest.fail('No pedir credenciales'))
    monkeypatch.setattr(modulo, 'SigacClient', lambda: fabrica(historial(2)))
    assert modulo.main(argumentos(ruta)) == 4
    salida = capsys.readouterr().out
    assert 'bloqueada' in salida and USUARIO not in salida and CLAVE not in salida
    assert instantanea(s) == antes and construido == []


def test_cli_bloqueado_no_alcanza_excepciones_con_secretos(ruta, cli, monkeypatch, capsys):
    modulo, construido, fabrica = cli
    monkeypatch.setattr(modulo.getpass, 'getpass', lambda _: pytest.fail('No pedir credenciales'))
    monkeypatch.setattr(modulo, 'SigacClient', lambda: fabrica(RuntimeError(f'fallo con {USUARIO} y {CLAVE}')))
    assert modulo.main(argumentos(ruta)) == 4
    salida = capsys.readouterr().out
    assert USUARIO not in salida and CLAVE not in salida and 'bloqueada' in salida
    assert construido == [] and not ruta.exists()


def test_cli_estado_valida_perfil_y_extension_sin_pedir_credenciales(tmp_path, cli, monkeypatch, capsys):
    modulo, construido, fabrica = cli
    sintetica = tmp_path / 'sintetica.sqlite3'
    AlmacenSqliteLocal(sintetica)
    antes = sintetica.read_bytes()
    monkeypatch.setattr(modulo.getpass, 'getpass', lambda _: pytest.fail('No pedir credenciales'))
    monkeypatch.setattr(modulo, 'SigacClient', lambda: pytest.fail('No abrir cliente'))
    assert modulo.main(argumentos(sintetica)) == 4
    assert sintetica.read_bytes() == antes
    assert modulo.main(['--db', str(sintetica), 'estado']) == 1
    assert sintetica.read_bytes() == antes
    assert modulo.main(['--db', str(tmp_path / 'datos.txt'), 'estado']) == 1
    assert '.sqlite3' in capsys.readouterr().out


def test_el_cli_tampoco_funciona_como_subproceso_sin_terminal(ruta):
    r = subprocess.run([sys.executable, "-B", str(RAIZ / "scripts" / "sigac_local.py"), "--db", str(ruta),
                        "consultar", "--autorizar-sigac-real", "--tipo", "T", "--total-casos", "3", "--caso-numero", "101"],
                       capture_output=True, text=True, input="", timeout=60)
    assert r.returncode == 2 and "terminal interactiva" in r.stderr and not ruta.exists()


# --- Compatibilidad con la app Android ------------------------------------------------------------------------------

def test_las_respuestas_reales_coinciden_con_los_tipos_de_la_app(ruta):
    s = servicio_de(ruta)
    consultar(s, ClienteFalso(historial(3))), consultar(s, ClienteFalso(historial(4)))
    with cliente_real(s) as c:
        h = {'Authorization': 'Bearer ' + CODIGO}
        for caso in c.get('/real/cases', headers=h).json():
            assert {type(caso[k]) for k in ('id', 'titulo')} == {str}
            assert all(type(caso[k]) is int for k in ('generacion', 'ocurrencias_observadas', 'eventos_internos'))
            assert caso['cobertura'] == 'desconocida'
        d = c.get(f'/real/cases/{caso_local(NUMERO)}', headers=h).json()
        assert all(type(a['local_id']) is str and type(a['generacion']) is int for a in d['ocurrencias'])
        for n in c.get('/real/observaciones', headers=h).json()['observaciones']:
            assert all(type(n[k]) is str for k in ('id', 'caso', 'tipo', 'local_id'))
            assert n['creacion_reciente_acreditada'] is False
        assert c.get('/real/novedades', headers=h).status_code == 410
        UUID(d['id'])
