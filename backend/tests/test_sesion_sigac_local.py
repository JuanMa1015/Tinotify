"""Acceso local y rechazo del monitor real. Solo guiones y archivos sintéticos.

La precondición de producción no se sustituye. Las carreras se ejercitan con
una entrada de contexto inerte bloqueada, sin autenticar ni consultar SIGAC.
La persistencia de referencia e idempotencia usa lecturas acreditadas simuladas.
"""

import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from tinotify.api.demo import crear_app
from tinotify.api.real_local import AccesoLocal
from tinotify.demo.novedades import INSTANCIA_REAL, ServicioNovedadesLocal, html_historial_sintetico
from tinotify.demo.push import ExpoPush
from tinotify.demo.servicio import ServicioDemo
from tinotify.integrations.sigac.sigac_client import SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.parsers.parser import parse_actuaciones
from tinotify.persistence.sqlite_local import AlmacenSqliteLocal
from tinotify.services.consulta_real_local import caso_local
from tinotify.services.sesion_sigac_local import Estado, GestorSesionSigac
from backend.tests.test_sqlite_local_v2 import snapshot
from backend.tests.test_frontera_persistencia_sigac import leer as lectura_acreditada

CODIGO = "CODIGO-LOCAL-FICTICIO-" + "z" * 20
USUARIO, CLAVE, TXTCASO = "USUARIO_CANARIO_SESION", "CLAVE_CANARIO_SESION_NO_REAL", "TXTCASO_CANARIO_SESION"
NUMERO = 616161
T = CodigoHistorial
H = {"Authorization": "Bearer " + CODIGO}


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("Estas pruebas no deben abrir conexiones")
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)


def historial(n):
    return tuple(parse_actuaciones(html_historial_sintetico(n), "CASO_FICTICIO"))


def esperar(condicion, tiempo=5.0):
    limite = time.monotonic() + tiempo
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return False


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Pausa:
    """Espera simulada: bloquea hasta `liberar()` o hasta que se pida detener; nunca duerme de verdad."""

    def __init__(self, reloj):
        self.reloj, self.llamadas, self._liberar, self.entro = reloj, [], threading.Event(), threading.Event()

    def __call__(self, segundos, parar):
        self.llamadas.append(segundos)
        self.entro.set()
        while not parar.is_set():
            if self._liberar.wait(0.01):
                self._liberar.clear()
                self.reloj.t += segundos
                break
        self.entro.clear()

    def liberar(self):
        self._liberar.set()


class ClienteSimulado:
    def __init__(self, guion):
        self.g, self.cerrado, self.credenciales, self.llamadas = guion, False, None, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cerrado = True
        return False

    def autenticar(self, usuario, clave, *, tipo, total_casos_esperado, caso_login=None):
        self.credenciales = (usuario, clave, caso_login, tipo)
        self.llamadas.append("autenticar")
        if self.g.get("bloquear_login"):
            self.g["bloquear_login"].wait(10)
        if self.g.get("fallar_login"):
            raise self.g["fallar_login"]
        return [SimpleNamespace(numero=NUMERO), SimpleNamespace(numero=1)]

    def listar_casos(self, *, total_esperado):
        self.llamadas.append("listar")
        if self.g.get("listados"):
            siguiente = self.g["listados"].pop(0)
            if isinstance(siguiente, BaseException):
                raise siguiente
        return [SimpleNamespace(numero=NUMERO), SimpleNamespace(numero=1)]

    def consultar_historial(self, numero, *, total_esperado=None, contenedor_id=None):
        self.llamadas.append("historial")
        if self.g.get("en_consulta"):
            self.g["en_consulta"].set()
        if self.g.get("bloquear_consulta"):
            self.g["bloquear_consulta"].wait(10)
        siguiente = self.g["historiales"].pop(0)
        if isinstance(siguiente, BaseException):
            raise siguiente
        return siguiente


class Fabrica:
    def __init__(self, *guiones):
        self.guiones, self.clientes = list(guiones), []

    def __call__(self):
        cliente = ClienteSimulado(self.guiones.pop(0))
        self.clientes.append(cliente)
        return cliente


@pytest.fixture
def servicio(tmp_path):
    return ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "real.sqlite3", perfil="real"), instancia=INSTANCIA_REAL)


def gestor_de(servicio, fabrica, reloj=None, **extra):
    reloj = reloj or Reloj()
    pausa = Pausa(reloj)
    opciones = {"fabrica_cliente": fabrica, "pausa": pausa, "reloj": reloj, "espera_login_s": 5.0, "espera_cierre_s": 5.0}
    return GestorSesionSigac(servicio, **{**opciones, **extra}), pausa, reloj


def push():
    return ExpoPush(transport=httpx.MockTransport(lambda r: pytest.fail('No se permiten entregas en estas pruebas')))


def cliente_http(servicio, gestor, *, host="127.0.0.1", base="http://127.0.0.1:8000", acceso=None, **kw):
    app = crear_app(ServicioDemo(("A" * 32, "B" * 32)), push(), real=servicio, acceso_real=acceso or AccesoLocal(CODIGO),
                    gestor=gestor)
    return TestClient(app, base_url=base, client=(host, 50000), **kw)


def cuerpo(**cambios):
    base = {"usuario": USUARIO, "clave": CLAVE, "tipo": "TIPO_FICTICIO", "total_casos": 2, "indice_caso": 1,
            "intervalo_minutos": 30, "confirmacion": "SIGAC-MONITOR-LOCAL"}
    return {**base, **cambios}


def estado(c):
    return c.get("/real/monitor", headers=H).json()


def comprobar_bloqueo(servicio, gestor, fabrica, cliente, **cambios):
    """El gestor puede existir como objeto; el monitor real no puede arrancar.

    No se sustituye el guard por un stub permisivo ni se fabrica acreditación.
    Las rutas de acceso y transporte siguen ejecutándose en ASGI.
    """
    antes, raw = snapshot(servicio), servicio.almacen.ruta.read_bytes()
    r = cliente.post('/real/sesion', headers=H, json=cuerpo(**cambios))
    assert r.status_code in (200, 202)
    assert esperar(lambda: estado(cliente)['estado'] == 'error')
    s = estado(cliente)
    assert s['requiere_autorizacion'] and s['ciclos_correctos'] == 0 and s['ultimo_ciclo'] is None
    gestor.apagar()
    assert all(c.llamadas == [] and c.credenciales is None and c.cerrado for c in fabrica.clientes)
    assert not gestor._hilo.is_alive()
    assert snapshot(servicio) == antes and servicio.almacen.ruta.read_bytes() == raw
    return r, s


# --- Activación y acceso -----------------------------------------------------------------------------------------

def test_las_rutas_de_sesion_estan_deshabilitadas_por_defecto(servicio, monkeypatch):
    monkeypatch.delenv("TINOTIFY_REAL_SESSION", raising=False)
    app = crear_app(ServicioDemo(("A" * 32, "B" * 32)), push(), real=servicio, acceso_real=AccesoLocal(CODIGO))
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1)) as c:
        assert c.post("/real/sesion", headers=H, json=cuerpo()).status_code == 404
        assert c.get("/real/monitor", headers=H).status_code == 404
        assert c.delete("/real/sesion", headers=H).status_code == 404


def test_la_variable_de_activacion_exige_los_datos_reales_protegidos(servicio, monkeypatch, tmp_path):
    monkeypatch.setenv("TINOTIFY_REAL_SESSION", "1")
    monkeypatch.delenv("TINOTIFY_REAL_DB", raising=False)
    monkeypatch.delenv("TINOTIFY_REAL_ACCESS_CODE", raising=False)
    with pytest.raises(RuntimeError):
        crear_app(ServicioDemo(("A" * 32, "B" * 32)), push())
    monkeypatch.setenv("TINOTIFY_REAL_DB", str(tmp_path / "otro.sqlite3"))
    monkeypatch.setenv("TINOTIFY_REAL_ACCESS_CODE", CODIGO)
    app = crear_app(ServicioDemo(("A" * 32, "B" * 32)), push())
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1)) as c:
        assert c.get("/real/monitor", headers=H).json()["estado"] == "sin_sesion"
    monkeypatch.delenv("TINOTIFY_REAL_DB")
    monkeypatch.delenv("TINOTIFY_REAL_ACCESS_CODE")
    monkeypatch.delenv("TINOTIFY_REAL_SESSION")
    gestor, _, _ = gestor_de(servicio, Fabrica())
    with pytest.raises(RuntimeError):  # un gestor sin datos reales protegidos
        crear_app(ServicioDemo(("A" * 32, "B" * 32)), push(), gestor=gestor)


def test_un_almacen_sintetico_no_admite_sesion(tmp_path):
    sintetico = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "s.sqlite3"))
    with pytest.raises(ValueError):
        GestorSesionSigac(sintetico)


@pytest.mark.parametrize("metodo,ruta", [("post", "/real/sesion"), ("get", "/real/monitor"), ("delete", "/real/sesion")])
def test_sin_codigo_de_acceso_o_con_codigo_incorrecto_se_rechaza_sin_tocar_sigac(servicio, metodo, ruta):
    fabrica = Fabrica({"historiales": [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        for cabeceras in ({}, {"Authorization": "Bearer incorrecto"}, {"Authorization": "Basic " + CODIGO}):
            r = getattr(c, metodo)(ruta, headers=cabeceras, **({"json": cuerpo()} if metodo == "post" else {}))
            assert r.status_code == 401 and r.json() == {"detail": "Acceso local requerido"}
            assert USUARIO not in r.text and CLAVE not in r.text
    assert fabrica.clientes == []


def test_el_codigo_no_se_acepta_por_url_ni_el_cuerpo_invalido_filtra_secretos(servicio):
    fabrica = Fabrica({"historiales": [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        assert c.get("/real/monitor", params={"codigo": CODIGO}).status_code == 401
        assert c.post(f"/real/sesion?codigo={CODIGO}", json=cuerpo()).status_code == 401
        r = c.post("/real/sesion", headers=H, json=cuerpo(intervalo_minutos=9, clave=CLAVE))
        assert r.status_code == 422 and r.json() == {"detail": "Entrada demo no valida"}
        assert USUARIO not in r.text and CLAVE not in r.text
        mal = c.post("/real/sesion", headers={"Authorization": "Bearer incorrecto"}, json=cuerpo(intervalo_minutos=9))
        assert mal.status_code == 401  # el acceso se comprueba antes que el cuerpo
    assert fabrica.clientes == []


@pytest.mark.parametrize("cambios", [
    {"intervalo_minutos": 9}, {"intervalo_minutos": 241}, {"confirmacion": "si"}, {"tipo": ""}, {"total_casos": 0},
    {"indice_caso": 0}, {"indice_caso": 3}, {"usuario": ""}, {"clave": ""}, {"etiqueta": "x" * 61},
    {"adicional": "no permitido"}, {"tipo": "con\ncontrol"},
])
def test_entradas_invalidas_se_rechazan_sin_conectar(servicio, cambios):
    fabrica = Fabrica({"historiales": [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        r = c.post("/real/sesion", headers=H, json=cuerpo(**cambios))
        assert r.status_code == 422 and USUARIO not in r.text and CLAVE not in r.text
    assert fabrica.clientes == []


def test_sin_confirmacion_explicita_no_hay_sesion(servicio):
    gestor, _, _ = gestor_de(servicio, Fabrica())
    with cliente_http(servicio, gestor) as c:
        datos = cuerpo()
        del datos["confirmacion"]
        assert c.post("/real/sesion", headers=H, json=datos).status_code == 422


# --- Solo transporte local ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cliente,base,extra", [
    (("203.0.113.9", 4000), "http://127.0.0.1:8000", {}),                       # conexión remota
    (("127.0.0.1", 4000), "http://192.168.1.20:8000", {}),                      # Host de red local
    (("127.0.0.1", 4000), "http://tinotify.example.com", {}),                   # Host público (túnel)
    (("127.0.0.1", 4000), "http://127.0.0.1:8000", {"X-Forwarded-For": "198.51.100.2"}),
    (("127.0.0.1", 4000), "http://127.0.0.1:8000", {"X-Forwarded-Proto": "https"}),
    (("127.0.0.1", 4000), "http://127.0.0.1:8000", {"Forwarded": "for=198.51.100.2"}),
    (("127.0.0.1", 4000), "http://127.0.0.1:8000", {"Via": "1.1 proxy"}),
    (("127.0.0.1", 4000), "http://127.0.0.1:8000", {"X-Real-IP": "198.51.100.2"}),
    (("127.0.0.1", 4000), "http://127.0.0.1:8000", {"CF-Connecting-IP": "198.51.100.2"}),
])
def test_las_credenciales_se_rechazan_por_conexiones_remotas_o_con_proxy(servicio, cliente, base, extra):
    fabrica = Fabrica({"historiales": [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica)
    app = crear_app(ServicioDemo(("A" * 32, "B" * 32)), push(), real=servicio, acceso_real=AccesoLocal(CODIGO), gestor=gestor)
    with TestClient(app, base_url=base, client=cliente) as c:
        r = c.post("/real/sesion", headers={**H, **extra}, json=cuerpo())
        assert r.status_code == 403 and USUARIO not in r.text and CLAVE not in r.text
    assert fabrica.clientes == []


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_el_enlace_local_usb_si_se_acepta_pero_exige_igualmente_el_codigo(servicio, host):
    fabrica = Fabrica({"historiales": [historial(3)]})
    gestor, pausa, _ = gestor_de(servicio, fabrica)
    base = "http://127.0.0.1:8000" if host == "127.0.0.1" else "http://[::1]:8000"
    with cliente_http(servicio, gestor, host=host, base=base) as c:
        assert c.post("/real/sesion", json=cuerpo()).status_code == 401  # estar en el bucle local no autentica
        assert c.post("/real/sesion", headers=H, json=cuerpo()).status_code in (200, 202)


# --- Estados de la sesión ---------------------------------------------------------------------------------------------

def test_perfil_real_no_autentica_ni_confirma_monitor_ante_guion_valido(servicio):
    fabrica = Fabrica({'historiales': [historial(3), historial(4)]})
    gestor, pausa, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        _, s = comprobar_bloqueo(servicio, gestor, fabrica, c)
        assert s['estado'] != 'monitor_activo' and pausa.llamadas == []


def test_respuesta_del_post_bloqueado_es_generica_y_sin_secretos(servicio):
    fabrica = Fabrica({'historiales': [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        r, s = comprobar_bloqueo(servicio, gestor, fabrica, c)
        assert set(s) == {'estado', 'motivo', 'requiere_autorizacion', 'intervalo_s', 'ciclos_correctos',
                          'ciclos_fallidos', 'ultimo_ciclo', 'ultimo_fallo'}
        assert r.headers['cache-control'] == 'no-store'
        assert all(secreto not in r.text + json.dumps(s) for secreto in (USUARIO, CLAVE, TXTCASO))


@pytest.mark.parametrize("error", [
    SigacClientError("No se confirmó el acceso", codigo=T.SESION_NO_CONFIRMADA),
    SigacSessionExpired("No se confirmó el acceso; no se reintentará automáticamente."),
    SigacClientError("Error de comunicación o codificación; no se procesó la respuesta.", codigo=T.TRANSPORTE),
])
def test_guard_real_precede_a_errores_de_autenticacion_del_guion(servicio, error):
    fabrica = Fabrica({'historiales': [], 'fallar_login': error})
    gestor, _, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        r, _ = comprobar_bloqueo(servicio, gestor, fabrica, c)
        # Ni siquiera se alcanza la autenticación simulada: rechazo anterior a ella.
        assert 'Cookie' not in r.text and 'Sesión no confirm' not in r.text
        assert servicio.listar_casos() == []


def test_rechazo_previo_no_consume_cuota_de_autenticaciones(servicio):
    fallo = SigacClientError('x', codigo=T.SESION_NO_CONFIRMADA)
    fabrica = Fabrica(*[{'historiales': [], 'fallar_login': fallo} for _ in range(4)])
    gestor, _, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        for _ in range(4):
            comprobar_bloqueo(servicio, gestor, fabrica, c)
        assert len(gestor._fallos_acceso) == 0
        # No contar un fallo de precondición como un intento de autenticación.
        assert all(cl.llamadas == [] for cl in fabrica.clientes)


def test_el_codigo_de_acceso_incorrecto_repetido_se_limita(servicio):
    reloj = Reloj()
    gestor, _, _ = gestor_de(servicio, Fabrica())
    acceso = AccesoLocal(CODIGO, reloj=reloj, max_fallos=3, ventana=60.0)
    with cliente_http(servicio, gestor, acceso=acceso) as c:
        for _ in range(3):
            assert c.post("/real/sesion", headers={"Authorization": "Bearer mal"}, json=cuerpo()).status_code == 401
        assert c.post("/real/sesion", headers=H, json=cuerpo()).status_code == 429


# --- Concurrencia -------------------------------------------------------------------------------------------------------

def test_no_se_permiten_sesiones_concurrentes_ni_con_sesion_pendiente(servicio, monkeypatch):
    liberar, entrada = threading.Event(), threading.Event()
    def entrar(cl):
        entrada.set()
        assert liberar.wait(5)
        return cl
    monkeypatch.setattr(ClienteSimulado, '__enter__', entrar)
    fabrica = Fabrica({'historiales': [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica, espera_login_s=0.05)
    antes = snapshot(servicio)
    try:
        with cliente_http(servicio, gestor) as c:
            assert c.post('/real/sesion', headers=H, json=cuerpo()).status_code == 202
            assert entrada.is_set()
            assert c.post('/real/sesion', headers=H, json=cuerpo()).status_code == 409
            liberar.set()
            assert esperar(lambda: estado(c)['estado'] == 'error')
            gestor.apagar()
            assert len(fabrica.clientes) == 1 and fabrica.clientes[0].llamadas == []
            assert snapshot(servicio) == antes
    finally:
        liberar.set()
        gestor.apagar()


def test_dos_solicitudes_simultaneas_inician_una_sola_sesion(servicio, monkeypatch):
    liberar = threading.Event()
    def entrar(cl):
        assert liberar.wait(5)
        return cl
    monkeypatch.setattr(ClienteSimulado, '__enter__', entrar)
    fabrica = Fabrica({'historiales': [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica, espera_login_s=0.05)
    codigos = []
    antes = snapshot(servicio)
    try:
        with cliente_http(servicio, gestor) as c:
            hilos = [threading.Thread(target=lambda: codigos.append(c.post('/real/sesion', headers=H, json=cuerpo()).status_code)) for _ in range(5)]
            for h in hilos: h.start()
            for h in hilos: h.join(5)
            assert not any(h.is_alive() for h in hilos)
            assert sorted(codigos) == [202, 409, 409, 409, 409]
            liberar.set()
            assert esperar(lambda: estado(c)['estado'] == 'error')
            assert len(fabrica.clientes) == 1 and fabrica.clientes[0].llamadas == []
            assert snapshot(servicio) == antes
    finally:
        liberar.set()
        gestor.apagar()


def test_un_monitor_de_otro_proceso_o_el_cli_bloquea_la_sesion(servicio):
    from tinotify.services.monitor_local import BloqueoMonitor
    fabrica = Fabrica({"historiales": [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica)
    with BloqueoMonitor(servicio.almacen.ruta), cliente_http(servicio, gestor) as c:
        assert c.post("/real/sesion", headers=H, json=cuerpo()).status_code == 409
    assert fabrica.clientes == []


# --- Expiración, detención y reinicio -------------------------------------------------------------------------------------

def test_guard_real_impide_consultar_sesion_expirada_y_reautenticar(servicio):
    expirada = SigacSessionExpired('Sesion ficticia vencida', codigo=T.SESION_NO_CONFIRMADA)
    fabrica = Fabrica({'historiales': [historial(3)], 'listados': [expirada]})
    gestor, pausa, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        _, s = comprobar_bloqueo(servicio, gestor, fabrica, c)
        assert s['requiere_autorizacion'] and pausa.llamadas == []
        assert fabrica.clientes[0].g['listados'] == [expirada]  # no se consulta ni reautentica


def test_detener_tras_rechazo_conserva_estado_y_libera_bloqueo(servicio):
    fabrica = Fabrica({'historiales': [historial(3)]})
    gestor, pausa, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        comprobar_bloqueo(servicio, gestor, fabrica, c)
        assert pausa.llamadas == []
        r = c.delete('/real/sesion', headers=H)
        assert r.status_code == 200 and r.json()['estado'] == 'error'
        assert not gestor._hilo.is_alive() and fabrica.clientes[0].cerrado
        assert not Path(str(servicio.almacen.ruta) + '.monitor.lock').exists()


def test_guard_real_impide_entrar_en_consulta_y_detener_no_persiste(servicio):
    en_consulta, bloquear = threading.Event(), threading.Event()
    fabrica = Fabrica({'historiales': [historial(3), historial(4)], 'en_consulta': en_consulta, 'bloquear_consulta': bloquear})
    gestor, _, _ = gestor_de(servicio, fabrica)
    antes = snapshot(servicio)
    with cliente_http(servicio, gestor) as c:
        comprobar_bloqueo(servicio, gestor, fabrica, c)
        assert not en_consulta.is_set()  # el perfil real no puede alcanzar la consulta
        c.delete('/real/sesion', headers=H)
    assert snapshot(servicio) == antes


def test_detener_sin_sesion_es_inofensivo(servicio):
    gestor, _, _ = gestor_de(servicio, Fabrica())
    with cliente_http(servicio, gestor) as c:
        assert c.delete("/real/sesion", headers=H).json()["estado"] == "sin_sesion"


def test_apagar_el_servidor_detiene_el_monitor_sin_dejar_hilos(servicio):
    fabrica = Fabrica({'historiales': [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        comprobar_bloqueo(servicio, gestor, fabrica, c)
        hilo = gestor._hilo
    assert not hilo.is_alive() and fabrica.clientes[0].cerrado


def test_reiniciar_el_backend_elimina_la_sesion_y_conserva_historial_sin_duplicados(servicio, tmp_path):
    fabrica = Fabrica({'historiales': []})
    gestor, _, _ = gestor_de(servicio, fabrica)
    primera = servicio.observar_validada(lectura_acreditada(3), clave=uuid4(), generacion_esperada=0)
    clave = uuid4()
    servicio.observar_validada(lectura_acreditada(4), clave=clave, generacion_esperada=1)
    antes = snapshot(servicio)
    with cliente_http(servicio, gestor) as c:
        comprobar_bloqueo(servicio, gestor, fabrica, c)
    nuevo = ServicioNovedadesLocal(AlmacenSqliteLocal(servicio.almacen.ruta, perfil='real'), instancia=INSTANCIA_REAL)
    gestor2, _, _ = gestor_de(nuevo, Fabrica())
    with cliente_http(nuevo, gestor2) as c:
        assert estado(c)['estado'] == 'sin_sesion' and estado(c)['ultimo_ciclo'] is None
        assert c.get('/real/cases', headers=H).json()[0]['ocurrencias_observadas'] == 4
        assert len(c.get('/real/observaciones', headers=H).json()['observaciones']) == 1
    assert nuevo.observar_validada(lectura_acreditada(4), clave=clave, generacion_esperada=1)['novedades_nuevas'] == 0
    assert snapshot(nuevo) == antes and primera['baseline']


def test_guard_real_no_consulta_listados_fallidos_y_requiere_autorizacion(servicio):
    error = SigacClientError('Respuesta ficticia no valida', codigo=T.HTTP_INVALIDO)
    fabrica = Fabrica({'historiales': [historial(3)], 'listados': [error]})
    gestor, _, _ = gestor_de(servicio, fabrica)
    with cliente_http(servicio, gestor) as c:
        _, s = comprobar_bloqueo(servicio, gestor, fabrica, c)
        assert s['requiere_autorizacion'] and s['motivo'] and 'http' not in json.dumps(s).lower()
        assert fabrica.clientes[0].g['listados'] == [error]


# --- Persistencia y no filtración ----------------------------------------------------------------------------------------

def test_referencia_observacion_y_repeticion_acreditadas_se_consultan_sin_duplicados(servicio):
    fabrica = Fabrica({'historiales': []})
    gestor, _, _ = gestor_de(servicio, fabrica)
    for cantidad, gen, eventos in ((3, 0, 0), (4, 1, 1), (4, 2, 0)):
        r = servicio.observar_validada(lectura_acreditada(cantidad), clave=uuid4(), generacion_esperada=gen)
        assert r['novedades_nuevas'] == eventos
    with cliente_http(servicio, gestor) as c:
        (obs,) = c.get('/real/observaciones', headers=H).json()['observaciones']
        assert obs['tipo'] == 'primera_observacion' and obs['creacion_reciente_acreditada'] is False
        (caso,) = c.get('/real/cases', headers=H).json()
        assert caso['titulo'] == 'Expediente local' and caso['ocurrencias_observadas'] == 4
        assert caso['cobertura'] == 'desconocida'
        assert c.get('/real/novedades', headers=H).status_code == 410
        comprobar_bloqueo(servicio, gestor, fabrica, c)


def test_las_credenciales_no_llegan_a_respuestas_estado_base_registros_ni_al_gestor(servicio, caplog, capsys):
    import logging
    caplog.set_level(logging.DEBUG)
    fabrica = Fabrica({'historiales': [historial(3)]})
    gestor, _, _ = gestor_de(servicio, fabrica)
    textos = []
    with cliente_http(servicio, gestor) as c:
        r, s = comprobar_bloqueo(servicio, gestor, fabrica, c, caso_login=TXTCASO)
        textos.extend((r.text, json.dumps(s)))
        for ruta in ('/real/monitor', '/real/cases', '/real/observaciones', '/real/novedades'):
            r = c.get(ruta, headers=H)
            textos.append(r.text + str(r.headers))
        textos.append(c.delete('/real/sesion', headers=H).text)
    salida = capsys.readouterr()
    for secreto in (USUARIO, CLAVE, TXTCASO, 'JSESSIONID'):
        assert not any(secreto in t for t in textos)
        assert secreto not in salida.out + salida.err + caplog.text
        assert secreto.encode() not in servicio.almacen.ruta.read_bytes()


def test_las_credenciales_se_descartan_al_autenticar_incluso_si_falla(servicio):
    fallo = SigacClientError("x", codigo=T.SESION_NO_CONFIRMADA)
    fabrica = Fabrica({"fallar_login": fallo, "historiales": []})
    gestor, _, _ = gestor_de(servicio, fabrica)
    gestor.iniciar(usuario=USUARIO, clave=CLAVE, tipo="T", total_casos=2, indice_caso=1, intervalo_s=1800)
    assert gestor.snapshot()["estado"] == "error"
    assert USUARIO not in repr(vars(gestor)) and CLAVE not in repr(vars(gestor))


def test_sin_cors_ni_cabeceras_de_acceso_cruzado(servicio):
    gestor, _, _ = gestor_de(servicio, Fabrica())
    with cliente_http(servicio, gestor) as c:
        r = c.get("/real/monitor", headers={**H, "Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in r.headers
        pre = c.options("/real/sesion", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
        assert pre.status_code == 405 and "access-control-allow-origin" not in pre.headers


# --- Separación de producción y de la API de demostración abierta ---------------------------------------------------------

def test_la_api_de_produccion_no_tiene_estas_rutas_ni_carga_el_gestor():
    from tinotify.api import app
    rutas = {r.path for r in app.routes}
    assert not any(p.startswith(("/real", "/demo")) for p in rutas)
    codigo = ("import sys, tinotify.api, tinotify.api.demo, tinotify.api.real_local;"
              "print('tinotify.services.sesion_sigac_local' in sys.modules,"
              "'tinotify.services.monitor_local' in sys.modules,"
              "'tinotify.integrations.sigac.sigac_client' in sys.modules)")
    salida = subprocess.run([sys.executable, "-B", "-c", codigo], capture_output=True, text=True, timeout=60).stdout
    assert salida.split() == ["False", "False", "False"]  # solo se cargan al activar la sesión local


def test_las_rutas_abiertas_de_demo_no_exponen_ni_inician_nada_real(servicio):
    gestor, _, _ = gestor_de(servicio, Fabrica())
    with cliente_http(servicio, gestor) as c:
        for ruta in ("/demo/local/cases", "/demo/catalog/cases", "/health"):
            assert "sesion" not in c.get(ruta).text and USUARIO not in c.get(ruta).text
        assert c.post("/demo/local/cases").status_code == 405
