"""Monitor local con clientes, reloj y esperas SIMULADOS. Ninguna prueba abre red ni espera de verdad."""

import importlib.util
import inspect
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from tinotify.demo.novedades import INSTANCIA_REAL, ServicioNovedadesLocal, html_historial_sintetico
from tinotify.integrations.sigac.sigac_client import SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial, EtapaSigac
from tinotify.parsers.parser import parse_actuaciones
from tinotify.persistence.sqlite_local import AlmacenSqliteLocal
from tinotify.services.consulta_real_local import caso_local
from tinotify.services.monitor_local import (
    INTERVALO_MAXIMO_S, INTERVALO_MINIMO_S, INTERVALO_PREDETERMINADO_S, BloqueoMonitor, Motivo, MonitorEnEjecucion,
    clasificar, monitorear,
)


RAIZ = Path(__file__).resolve().parents[1]
NUMERO = 515151
USUARIO, CLAVE, COOKIE = "USUARIO_FICTICIO_MON", "CLAVE_FICTICIA_MON_NO_REAL", "JSESSIONID=COOKIE_FICTICIA"
T = CodigoHistorial


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("Estas pruebas no deben abrir conexiones")
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)


def historial(n):
    return tuple(parse_actuaciones(html_historial_sintetico(n), "CASO_FICTICIO"))


class Reloj:
    """Tiempo simulado: `espera` avanza el reloj sin dormir y registra cada espera."""

    def __init__(self, interrumpir_en_espera=None):
        self.t, self.esperas, self.interrumpir = 0.0, [], interrumpir_en_espera

    def __call__(self):
        return self.t

    def espera(self, segundos):
        self.esperas.append(round(segundos, 3))
        if self.interrumpir == len(self.esperas):
            raise KeyboardInterrupt
        self.t += segundos


class ClienteGuion:
    """Cada elemento de `historiales` es un resultado o una excepción por consulta; el listado es configurable."""

    def __init__(self, reloj, *historiales, listados=(), costo_listado=2, costo_historial=3, numeros=(NUMERO, 9)):
        self.reloj, self.historiales, self.listados = reloj, list(historiales), list(listados)
        self.costos, self.numeros, self.llamadas, self.enlinea = (costo_listado, costo_historial), numeros, [], 0

    def listar_casos(self, *, total_esperado):
        self.llamadas.append("listar")
        self.reloj.t += self.costos[0]
        if self.listados:
            siguiente = self.listados.pop(0)
            if isinstance(siguiente, BaseException):
                raise siguiente
            return siguiente
        return [SimpleNamespace(numero=n) for n in self.numeros]

    def consultar_historial(self, numero, *, total_esperado=None, contenedor_id=None):
        self.llamadas.append("historial")
        self.enlinea += 1
        assert self.enlinea == 1, "consultas simultáneas"
        try:
            self.reloj.t += self.costos[1]
            siguiente = self.historiales.pop(0)
            if isinstance(siguiente, BaseException):
                raise siguiente
            return siguiente
        finally:
            self.enlinea -= 1


@pytest.fixture
def servicio(tmp_path):
    # Dobles sin HTTP/identidad solo pueden escribir en el perfil sintético.
    return ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "monitor-sintetico.sqlite3"))


class Entrada:
    def __init__(self, error=None):
        self.llamadas, self.error = 0, error

    def __call__(self):
        self.llamadas += 1
        if self.error:
            raise self.error
        return [SimpleNamespace(numero=NUMERO), SimpleNamespace(numero=9)]


def correr(servicio, cliente, reloj, *, entrada=None, **extra):
    eventos = []
    entrada = entrada or Entrada()
    resultado = monitorear(cliente, entrada, total_casos=2, indice_caso=1, servicio=servicio, reloj=reloj,
                           espera=reloj.espera, emitir=eventos.append, **{"intervalo_s": 1800, **extra})
    return resultado, eventos, entrada


def estado(servicio):
    return servicio.listar_casos(), servicio.novedades()


def transitorio():
    return SigacClientError("Error de comunicación o codificación; no se procesó la respuesta.", codigo=T.TRANSPORTE)


def estructural(codigo=T.CABECERAS_DISCORDANTES):
    return SigacClientError("Historial incompleto, ambiguo o de estructura no confirmada.", codigo=codigo)


# --- Ciclos, intervalos y persistencia ---------------------------------------------------------------------------

def test_primera_consulta_y_posteriores_con_baseline_novedad_y_repeticion(servicio):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), historial(4), historial(4))
    resultado, eventos, entrada = correr(servicio, cliente, r, max_ciclos=3)
    ciclos = [e for e in eventos if e["evento"] == "ciclo"]
    assert [(c["baseline"], c["novedades_nuevas"], c["actuaciones"]) for c in ciclos] == [
        (True, 0, 3), (False, 1, 4), (False, 0, 4)]
    assert resultado.motivo is Motivo.MAX_CICLOS and resultado.ciclos_correctos == 3 and resultado.codigo_salida == 0
    assert entrada.llamadas == 1  # una sola autenticación para toda la ejecución
    assert cliente.llamadas == ["historial", "listar", "historial", "listar", "historial"]  # el primer ciclo no repite el listado
    (caso,) = servicio.listar_casos()
    assert caso["id"] == caso_local(NUMERO) and caso["total_actuaciones"] == 4 and len(servicio.novedades()) == 1


def test_los_intervalos_se_miden_de_inicio_a_inicio_con_reloj_simulado(servicio):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), historial(3), historial(3))
    correr(servicio, cliente, r, max_ciclos=3, intervalo_s=INTERVALO_PREDETERMINADO_S)
    # Ciclo 1: 3 s (solo historial); ciclo 2 empieza a los 1800 s y dura 5 s (listado + historial).
    assert r.esperas == [1797.0, 1795.0]
    assert INTERVALO_PREDETERMINADO_S == 1800 and INTERVALO_MINIMO_S == 600 and INTERVALO_MAXIMO_S == 14400


@pytest.mark.parametrize("intervalo", [0, 599, 14401, 1800.5, "1800", None])
def test_el_intervalo_fuera_de_rango_se_rechaza_antes_de_autenticar(servicio, intervalo):
    r = Reloj()
    entrada = Entrada()
    with pytest.raises(ValueError):
        monitorear(ClienteGuion(r), entrada, total_casos=2, indice_caso=1, servicio=servicio, intervalo_s=intervalo)
    assert entrada.llamadas == 0


@pytest.mark.parametrize("extra", [{"max_ciclos": 0}, {"indice_caso": 3}, {"indice_caso": 0}, {"total_casos": 0},
                                   {"etiqueta": "x" * 61}])
def test_parametros_invalidos_se_rechazan_sin_conectar(servicio, extra):
    r = Reloj()
    entrada = Entrada()
    base = {"total_casos": 2, "indice_caso": 1, "servicio": servicio}
    with pytest.raises(ValueError):
        monitorear(ClienteGuion(r), entrada, **{**base, **extra})
    assert entrada.llamadas == 0


def test_reinicio_del_proceso_conserva_el_estado_sin_duplicados(tmp_path):
    ruta = tmp_path / "real.sqlite3"
    def nuevo():
        return ServicioNovedadesLocal(AlmacenSqliteLocal(ruta))
    r1 = Reloj()
    correr(nuevo(), ClienteGuion(r1, historial(3), historial(4)), r1, max_ciclos=2)
    r2 = Reloj()  # monitor nuevo sobre el mismo archivo
    resultado, eventos, _ = correr(nuevo(), ClienteGuion(r2, historial(4), historial(4)), r2, max_ciclos=2)
    assert [e["novedades_nuevas"] for e in eventos if e["evento"] == "ciclo"] == [0, 0]
    s = nuevo()
    assert len(s.novedades()) == 1 and s.listar_casos()[0]["total_actuaciones"] == 4


# --- Sin consultas simultáneas -------------------------------------------------------------------------------------

def test_un_segundo_monitor_en_el_mismo_proceso_no_puede_iniciar(servicio):
    r = Reloj()
    intentos = []

    class ClienteReentrante(ClienteGuion):
        def consultar_historial(self, numero, **kw):
            try:
                monitorear(self, Entrada(), total_casos=2, indice_caso=1, servicio=servicio, reloj=r,
                           espera=r.espera)
            except MonitorEnEjecucion:
                intentos.append("bloqueado")
            return super().consultar_historial(numero, **kw)

    correr(servicio, ClienteReentrante(r, historial(3)), r, max_ciclos=1)
    assert intentos == ["bloqueado"]
    resultado, _, _ = correr(servicio, ClienteGuion(r, historial(3)), r, max_ciclos=1)  # el cerrojo se liberó
    assert resultado.motivo is Motivo.MAX_CICLOS


def test_el_bloqueo_de_archivo_impide_dos_monitores_y_no_borra_bloqueos_ajenos(tmp_path):
    ruta = tmp_path / "real.sqlite3"
    with BloqueoMonitor(ruta) as bloqueo:
        assert bloqueo.ruta.exists()
        with pytest.raises(MonitorEnEjecucion):
            BloqueoMonitor(ruta).__enter__()
        assert bloqueo.ruta.exists()  # el segundo intento no lo elimina
    assert not bloqueo.ruta.exists()
    with pytest.raises(RuntimeError):
        with BloqueoMonitor(ruta) as otra:
            raise RuntimeError("fallo_ficticio")
    assert not otra.ruta.exists()  # se libera aunque falle el cuerpo


# --- Detención con Ctrl+C -----------------------------------------------------------------------------------------------

def test_ctrl_c_durante_la_espera_detiene_limpiamente_y_no_consulta_mas(servicio):
    r = Reloj(interrumpir_en_espera=1)
    cliente = ClienteGuion(r, historial(3), historial(4))
    resultado, eventos, entrada = correr(servicio, cliente, r)
    assert resultado.motivo is Motivo.INTERRUMPIDO and resultado.codigo_salida == 0 and resultado.ciclos_correctos == 1
    assert cliente.llamadas == ["historial"] and eventos[-1]["evento"] == "detenido"
    assert servicio.listar_casos()[0]["total_actuaciones"] == 3
    resultado, _, _ = correr(servicio, ClienteGuion(Reloj(), historial(3)), Reloj(), max_ciclos=1)  # nada quedó bloqueado
    assert resultado.motivo is Motivo.MAX_CICLOS


def test_ctrl_c_durante_una_consulta_o_la_autenticacion_no_modifica_nada(servicio):
    r = Reloj()
    resultado, _, _ = correr(servicio, ClienteGuion(r, KeyboardInterrupt()), r)
    assert resultado.motivo is Motivo.INTERRUMPIDO and servicio.listar_casos() == []
    resultado, _, _ = correr(servicio, ClienteGuion(r), r, entrada=Entrada(KeyboardInterrupt()))
    assert resultado.motivo is Motivo.INTERRUMPIDO


# --- Sesión expirada y errores de acceso: el monitor se detiene ----------------------------------------------------

@pytest.mark.parametrize("fase", ["listado", "historial"])
def test_sesion_expirada_detiene_sin_reautenticar_ni_consultar_mas(servicio, fase):
    r = Reloj()
    expirada = SigacSessionExpired("Sesión no confirmada o vencida.", codigo=T.SESION_NO_CONFIRMADA)
    cliente = ClienteGuion(r, historial(3), *( [expirada] if fase == "historial" else [historial(3)]),
                           listados=[expirada] if fase == "listado" else [])
    resultado, eventos, entrada = correr(servicio, cliente, r)
    assert resultado.motivo is Motivo.SESION_EXPIRADA and resultado.codigo_salida == 4
    assert entrada.llamadas == 1  # nunca se vuelve a autenticar
    llamadas = list(cliente.llamadas)
    assert servicio.listar_casos()[0]["total_actuaciones"] == 3
    assert eventos[-1]["motivo"] == "sesion_expirada_requiere_nueva_autorizacion"
    assert cliente.llamadas == llamadas and len(r.esperas) == 1  # tras detenerse no hay más consultas ni esperas


@pytest.mark.parametrize("error", [
    SigacClientError("Sin acceso", codigo=T.SESION_NO_CONFIRMADA),
    SigacClientError("Respuesta HTTP no válida; no se procesó.", codigo=T.HTTP_INVALIDO),     # 429, bloqueos, 5xx
    SigacClientError("La respuesta sigue siendo una página de acceso", codigo=T.PAGINA_NO_PROTEGIDA),  # CAPTCHA, etc.
    SigacClientError("SIGAC no devolvió contenido HTML.", codigo=T.NO_HTML),
    SigacClientError("Fallo no clasificado"),
])
def test_errores_de_acceso_o_restriccion_detienen_el_monitor(servicio, error):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), error)
    resultado, eventos, _ = correr(servicio, cliente, r)
    assert resultado.motivo is Motivo.ACCESO_RESTRINGIDO and resultado.codigo_salida == 4
    assert cliente.llamadas == ["historial", "listar", "historial"] and servicio.listar_casos()[0]["total_actuaciones"] == 3


@pytest.mark.parametrize("error", [SigacClientError("No se confirmó el acceso", codigo=T.SESION_NO_CONFIRMADA),
                                   SigacSessionExpired("No se confirmó el acceso."), transitorio()])
def test_un_fallo_de_autenticacion_detiene_antes_de_consultar_y_sin_reintentos(servicio, error):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3))
    resultado, eventos, entrada = correr(servicio, cliente, r, entrada=Entrada(error))
    assert resultado.motivo is Motivo.AUTENTICACION_FALLIDA and resultado.codigo_salida == 4
    assert entrada.llamadas == 1 and cliente.llamadas == [] and servicio.listar_casos() == [] and r.esperas == []


def test_cambios_en_el_listado_detienen_el_monitor(servicio):
    r = Reloj()
    sin_caso = [SimpleNamespace(numero=1), SimpleNamespace(numero=2)]
    resultado, _, _ = correr(servicio, ClienteGuion(r, historial(3), listados=[sin_caso]), r)
    assert resultado.motivo is Motivo.EXPEDIENTE_NO_LISTADO
    r = Reloj()
    discordante = SigacClientError("Listado incompleto, ambiguo o distinto del total contrastado.")
    resultado, _, _ = correr(servicio, ClienteGuion(r, historial(3), listados=[discordante]), r)
    assert resultado.motivo is Motivo.LISTADO_NO_CONFIRMADO


# --- Errores transitorios y extracciones rechazadas ---------------------------------------------------------------

def test_un_error_de_red_transitorio_espera_un_tiempo_limitado_y_continua(servicio):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), transitorio(), historial(4))
    resultado, eventos, _ = correr(servicio, cliente, r, max_ciclos=3)
    fallos = [e for e in eventos if e["evento"] == "fallo"]
    assert [(f["tipo"], f["codigo"], f["consecutivos"]) for f in fallos] == [("transitorio", "fallo_transporte_o_codificacion", 1)]
    assert 60 in r.esperas and max(r.esperas) <= 1800  # espera corta y acotada, nunca inmediata
    assert resultado.ciclos_correctos == 2 and resultado.ciclos_fallidos == 1 and resultado.motivo is Motivo.MAX_CICLOS
    assert len(servicio.novedades()) == 1


def test_errores_transitorios_repetidos_detienen_con_espera_creciente_y_limitada(servicio):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), transitorio(), transitorio(), transitorio(), historial(4))
    resultado, eventos, _ = correr(servicio, cliente, r)
    assert resultado.motivo is Motivo.FALLOS_REPETIDOS and resultado.codigo_salida == 5
    esperas_de_fallo = [e for e in r.esperas if e < 1000]
    assert esperas_de_fallo == [60, 120]  # y a la tercera falla se detiene, sin una cuarta consulta
    assert len(cliente.historiales) == 1  # la cuarta consulta nunca se hizo
    assert servicio.listar_casos()[0]["total_actuaciones"] == 3


def test_un_exito_reinicia_la_cuenta_de_fallos_consecutivos(servicio):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), transitorio(), transitorio(), historial(3), transitorio(), transitorio(),
                           historial(4))
    resultado, _, _ = correr(servicio, cliente, r, max_ciclos=7)
    assert resultado.motivo is Motivo.MAX_CICLOS and resultado.ciclos_correctos == 3 and resultado.ciclos_fallidos == 4


def test_la_espera_transitoria_nunca_supera_el_intervalo(servicio):
    r = Reloj()
    correr(servicio, ClienteGuion(r, historial(3), transitorio(), transitorio(), transitorio()), r,
           intervalo_s=INTERVALO_MINIMO_S)
    assert all(e <= INTERVALO_MINIMO_S for e in r.esperas)


@pytest.mark.parametrize("rechazo", [
    estructural(T.CABECERAS_DISCORDANTES), estructural(T.SIN_ACTUACIONES), estructural(T.TOTAL_DISCORDANTE),
    estructural(T.BLOQUE_CON_CONTROLES), estructural(T.DOCUMENTO_INCOMPLETO), estructural(T.HTML_VACIO),
    estructural(T.LONGITUD_RESPUESTA),
])
def test_una_extraccion_rechazada_no_modifica_el_historial_ni_se_reintenta_antes_del_intervalo(servicio, rechazo):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), rechazo, historial(4))
    resultado, eventos, _ = correr(servicio, cliente, r, max_ciclos=3)
    fallo = next(e for e in eventos if e["evento"] == "fallo")
    assert fallo["tipo"] == "extraccion" and fallo["codigo"] == rechazo.codigo.value
    assert r.esperas[1] > 1000  # espera el intervalo normal, no un reintento agresivo
    assert resultado.ciclos_correctos == 2 and len(servicio.novedades()) == 1  # el rechazo no cambió nada y la siguiente sí


def test_una_observacion_sospechosa_se_rechaza_sin_modificar_la_base(servicio):
    r = Reloj()
    cliente = ClienteGuion(r, historial(4), historial(3), historial(4))  # la segunda tiene menos actuaciones
    resultado, eventos, _ = correr(servicio, cliente, r, max_ciclos=3)
    fallo = next(e for e in eventos if e["evento"] == "fallo")
    assert fallo["codigo"] == "observacion_rechazada" and fallo["tipo"] == "extraccion"
    assert servicio.listar_casos()[0]["total_actuaciones"] == 4 and servicio.novedades() == []
    assert resultado.ciclos_correctos == 2 and resultado.ciclos_fallidos == 1


def test_extracciones_rechazadas_repetidas_detienen_el_monitor_sin_tocar_la_base(servicio):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), estructural(), estructural(), estructural(), historial(4))
    resultado, _, _ = correr(servicio, cliente, r)
    assert resultado.motivo is Motivo.FALLOS_REPETIDOS and servicio.listar_casos()[0]["total_actuaciones"] == 3
    assert len(cliente.historiales) == 1  # no se consultó una vez más


def test_clasificacion_de_errores():
    assert clasificar(transitorio()) == "transitorio"
    assert clasificar(SigacSessionExpired("x")) == "acceso"
    assert clasificar(estructural()) == "extraccion"
    for codigo in (T.SESION_NO_CONFIRMADA, T.HTTP_INVALIDO, T.PAGINA_NO_PROTEGIDA, T.NO_HTML, T.NO_CLASIFICADO):
        assert clasificar(SigacClientError("x", codigo=codigo)) == "acceso"


@pytest.mark.parametrize('etapa', [EtapaSigac.LISTADO_INICIAL, EtapaSigac.LISTADO_REPETIDO])
def test_codigos_preservados_del_listado_conservan_clasificacion_anterior(etapa):
    for codigo in (T.LISTADO_NO_CONFIRMADO, T.DOCUMENTO_INCOMPLETO, T.PAGINA_NO_PROTEGIDA):
        assert clasificar(SigacClientError('FICTICIO', codigo=codigo, etapa=etapa)) == 'acceso'
    assert clasificar(SigacClientError('FICTICIO', codigo=T.TRANSPORTE, etapa=etapa)) == 'transitorio'
    assert clasificar(SigacClientError('FICTICIO', codigo=T.DOCUMENTO_INCOMPLETO,
                                     etapa=EtapaSigac.HISTORIAL)) == 'extraccion'


def test_un_error_inesperado_detiene_sin_filtrar_secretos(servicio):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), RuntimeError(f"fallo con {USUARIO} {CLAVE} {COOKIE}"))
    resultado, eventos, _ = correr(servicio, cliente, r)
    assert resultado.motivo is Motivo.ERROR_INESPERADO
    salida = json.dumps(eventos)
    for secreto in (USUARIO, CLAVE, COOKIE, "COOKIE_FICTICIA"):
        assert secreto not in salida


# --- Secretos y alcance -------------------------------------------------------------------------------------------------

def test_los_eventos_solo_contienen_estado_cantidades_codigos_y_horas(servicio):
    r = Reloj()
    cliente = ClienteGuion(r, historial(3), transitorio(), historial(4))
    _, eventos, _ = correr(servicio, cliente, r, max_ciclos=3)
    permitidas = {"evento", "hora", "intervalo_s", "segundos", "ciclo", "duracion_s", "baseline", "novedades_nuevas",
                  "actuaciones", "generacion", "tipo", "codigo", "consecutivos", "proximo_en_s", "motivo",
                  "ciclos_correctos", "ciclos_fallidos"}
    assert all(set(e) <= permitidas for e in eventos)
    salida = json.dumps(eventos)
    for contenido in ("Actuación sintética", "REMITENTE", "TITULO SINTETICO", str(NUMERO)):
        assert contenido not in salida


def test_el_monitor_no_recibe_credenciales_ni_las_guarda():
    parametros = set(inspect.signature(monitorear).parameters)
    assert not parametros & {"usuario", "clave", "password", "caso_login", "cookies", "credenciales"}
    fuente = inspect.getsource(sys.modules["tinotify.services.monitor_local"])
    for prohibido in ("getpass", "environ", "SecureStore", "write_text", "sqlite3", "json.dump"):
        assert prohibido not in fuente


def test_la_api_no_importa_ni_expone_el_monitor():
    codigo = ("import sys, tinotify.api, tinotify.api.demo, tinotify.api.real_local;"
              "print('tinotify.services.monitor_local' in sys.modules,"
              "'tinotify.integrations.sigac.sigac_client' in sys.modules)")
    salida = subprocess.run([sys.executable, "-B", "-c", codigo], capture_output=True, text=True, timeout=60).stdout
    assert salida.split() == ["False", "False"]
    from tinotify.api import app
    from tinotify.api.demo import crear_app
    from tinotify.demo.servicio import ServicioDemo
    demo = crear_app(ServicioDemo(("A" * 32, "B" * 32)))
    for aplicacion in (app, demo):
        rutas = " ".join(getattr(r, "path", "") for r in aplicacion.routes)
        assert "monitor" not in rutas and "consult" not in rutas


# --- CLI ------------------------------------------------------------------------------------------------------------------

def cargar_cli():
    spec = importlib.util.spec_from_file_location("sigac_local_cli_mon", RAIZ / "scripts" / "sigac_local.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TerminalFalsa:
    def isatty(self):
        return True


class SigacFalso:
    """Doble del cliente SIGAC para el CLI: registra las credenciales recibidas y no abre red."""

    instancias = []

    def __init__(self, *historiales, reloj=None, **extra):
        self.credenciales = None
        self.cliente = ClienteGuion(reloj or Reloj(), *historiales, **extra)
        SigacFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def autenticar(self, usuario, clave, *, tipo, total_casos_esperado, caso_login=None):
        self.credenciales = (usuario, clave, caso_login)
        return [SimpleNamespace(numero=NUMERO), SimpleNamespace(numero=9)]

    def listar_casos(self, **kw):
        return self.cliente.listar_casos(**kw)

    def consultar_historial(self, *a, **kw):
        return self.cliente.consultar_historial(*a, **kw)


@pytest.fixture
def cli(monkeypatch, tmp_path):
    SigacFalso.instancias.clear()
    modulo = cargar_cli()
    # Solo esta fixture reemplaza el almacén del bucle interno. La entrada CLI
    # real continúa bloqueada y el comportamiento productivo no se relaja.
    monkeypatch.setattr(modulo, '_servicio', lambda ruta: ServicioNovedadesLocal(AlmacenSqliteLocal(ruta)))
    monkeypatch.setattr(sys, "stdin", TerminalFalsa())
    monkeypatch.setattr("builtins.input", lambda _: "SIGAC-MONITOR-LOCAL")
    respuestas = iter([USUARIO, CLAVE, "TXTCASO_FICTICIO"])
    monkeypatch.setattr(modulo.getpass, "getpass", lambda prompt: next(respuestas))
    return modulo, tmp_path / "real.sqlite3"


def args_monitor(ruta, *extra):
    return ["--db", str(ruta), "monitorear", "--autorizar-sigac-real", "--tipo", "TIPO_FICTICIO", "--total-casos", "2",
            "--caso-numero", str(NUMERO), *extra]


def bucle_sintetico(modulo, ruta, **extra):
    """Ejercita el bucle con SigacFalso; el CLI real permanece cerrado."""
    import argparse
    args = SimpleNamespace(db=ruta, intervalo_minutos=30, max_ciclos=None, pedir_caso_login=False,
        tipo='TIPO_FICTICIO', total_casos=2, caso_numero=NUMERO, etiqueta=None, total_actuaciones=None,
        contenedor_historial=None)
    for clave, valor in extra.items():
        setattr(args, clave, valor)
    return modulo._ejecutar_monitor(argparse.ArgumentParser(), args)


def test_el_monitor_exige_bandera_terminal_confirmacion_e_intervalo_valido(cli, monkeypatch, capsys):
    modulo, ruta = cli
    monkeypatch.setattr(modulo, "SigacClient", lambda: pytest.fail("No debe abrirse el cliente SIGAC"))
    monkeypatch.setattr(modulo.getpass, "getpass", lambda prompt: pytest.fail("No debe pedir credenciales"))
    with pytest.raises(SystemExit) as salida:  # sin bandera
        modulo.main(["--db", str(ruta), "monitorear", "--tipo", "T", "--total-casos", "2"])
    assert salida.value.code == 2
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))  # sin terminal interactiva
    with pytest.raises(SystemExit) as salida:
        modulo.main(args_monitor(ruta))
    assert salida.value.code == 2
    monkeypatch.setattr(sys, "stdin", TerminalFalsa())
    for minutos in ("0", "9", "241", "-5"):  # más agresivo o más lento que lo permitido
        with pytest.raises(SystemExit) as salida:
            modulo.main(args_monitor(ruta, "--intervalo-minutos", minutos))
        assert salida.value.code == 2
    monkeypatch.setattr("builtins.input", lambda _: "SIGAC-CONSULTA-LOCAL")  # confirmación de otra orden
    assert bucle_sintetico(modulo, ruta) == 2 and "Cancelado" in capsys.readouterr().out
    assert not ruta.exists() and not Path(str(ruta) + ".monitor.lock").exists()


def test_bucle_sintetico_autentica_una_vez_e_imprime_solo_estado(cli, monkeypatch, capsys):
    modulo, ruta = cli
    r = Reloj()
    monkeypatch.setattr(modulo, "SigacClient", lambda: SigacFalso(historial(3), historial(4), reloj=r))
    original = modulo.monitorear
    monkeypatch.setattr(modulo, "monitorear", lambda *a, **k: original(*a, **k, reloj=r, espera=r.espera))
    codigo = bucle_sintetico(modulo, ruta, pedir_caso_login=True, max_ciclos=2, etiqueta='Mi expediente')
    salida = capsys.readouterr().out
    assert codigo == 0 and r.esperas and r.esperas[0] > 1700  # intervalo de 30 min por defecto, sin dormir de verdad
    lineas = [json.loads(linea) for linea in salida.splitlines() if linea.startswith("{")]
    assert [l["evento"] for l in lineas if l["evento"] in ("inicio", "ciclo", "detenido")] == [
        "inicio", "ciclo", "ciclo", "detenido"]
    assert lineas[0]["intervalo_s"] == 1800
    for secreto in (USUARIO, CLAVE, "TXTCASO_FICTICIO", str(NUMERO)):
        assert secreto not in salida and secreto.encode() not in ruta.read_bytes()
    assert "Actuación sintética" not in salida  # el contenido vive solo en el archivo local, nunca en la salida
    (instancia,) = SigacFalso.instancias
    assert instancia.credenciales == (USUARIO, CLAVE, "TXTCASO_FICTICIO")
    assert not Path(str(ruta) + ".monitor.lock").exists()
    assert ServicioNovedadesLocal(AlmacenSqliteLocal(ruta)).novedades()


def test_el_cli_se_detiene_con_ctrl_c_libera_el_bloqueo_y_no_filtra(cli, monkeypatch, capsys):
    modulo, ruta = cli
    r = Reloj(interrumpir_en_espera=1)
    monkeypatch.setattr(modulo, "SigacClient", lambda: SigacFalso(historial(3), historial(4), reloj=r))
    original = modulo.monitorear
    monkeypatch.setattr(modulo, "monitorear", lambda *a, **k: original(*a, **k, reloj=r, espera=r.espera))
    assert bucle_sintetico(modulo, ruta) == 0
    salida = capsys.readouterr().out
    assert "interrumpido_por_el_usuario" in salida and USUARIO not in salida and CLAVE not in salida
    assert not Path(str(ruta) + ".monitor.lock").exists()
    assert len(SigacFalso.instancias[0].cliente.llamadas) == 1  # ninguna consulta tras detenerse


def test_el_cli_termina_con_codigo_de_nueva_autorizacion_si_la_sesion_expira(cli, monkeypatch, capsys):
    modulo, ruta = cli
    r = Reloj()
    expirada = SigacSessionExpired("Sesión no confirmada o vencida.", codigo=T.SESION_NO_CONFIRMADA)
    monkeypatch.setattr(modulo, "SigacClient", lambda: SigacFalso(historial(3), reloj=r, listados=[expirada]))
    original = modulo.monitorear
    monkeypatch.setattr(modulo, "monitorear", lambda *a, **k: original(*a, **k, reloj=r, espera=r.espera))
    assert bucle_sintetico(modulo, ruta) == 4
    assert "sesion_expirada_requiere_nueva_autorizacion" in capsys.readouterr().out
    assert len(SigacFalso.instancias) == 1  # no se creó otro cliente ni se volvió a autenticar


def test_el_cli_no_arranca_si_ya_hay_un_monitor_y_no_pide_credenciales(cli, monkeypatch, capsys):
    modulo, ruta = cli
    monkeypatch.setattr(modulo.getpass, "getpass", lambda prompt: pytest.fail("No debe pedir credenciales"))
    monkeypatch.setattr(modulo, "SigacClient", lambda: pytest.fail("No debe abrirse el cliente SIGAC"))
    with BloqueoMonitor(ruta):
        assert bucle_sintetico(modulo, ruta) == 1
    assert "monitor activo" in capsys.readouterr().out


def test_el_cli_valida_el_perfil_antes_de_pedir_credenciales(cli, monkeypatch, capsys):
    modulo, ruta = cli
    # Aquí se comprueba la fábrica productiva, no la del bucle ficticio.
    monkeypatch.setattr(modulo, '_servicio', cargar_cli()._servicio)
    AlmacenSqliteLocal(ruta)  # archivo sintético
    monkeypatch.setattr(modulo.getpass, "getpass", lambda prompt: pytest.fail("No debe pedir credenciales"))
    monkeypatch.setattr(modulo, "SigacClient", lambda: pytest.fail("No debe abrirse el cliente SIGAC"))
    assert bucle_sintetico(modulo, ruta) == 1
    assert "mismo perfil" in capsys.readouterr().out.lower()
    assert not Path(str(ruta) + ".monitor.lock").exists()


def test_el_cli_en_subproceso_sin_terminal_no_conecta(tmp_path):
    r = subprocess.run([sys.executable, "-B", str(RAIZ / "scripts" / "sigac_local.py"), "--db",
                        str(tmp_path / "real.sqlite3"), "monitorear", "--autorizar-sigac-real", "--tipo", "T",
                        "--total-casos", "2", "--caso-numero", "515151"], capture_output=True, text=True, input="", timeout=60)
    assert r.returncode == 2 and "terminal interactiva" in r.stderr
    assert not (tmp_path / "real.sqlite3").exists()
