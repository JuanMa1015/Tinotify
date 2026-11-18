"""Push por FCM con transporte simulado: sin red, con una cuenta de servicio y una llave RSA generadas aquí (ficticias)."""

import json
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import pytest

from backend.tests.helpers.monitor_real import AlmacenMemoria
from tinotify.real_remoto import fcm
from tinotify.real_remoto.config import Config
from tinotify.real_remoto.servicio_monitor import ServicioMonitor

TOKEN_DISP = "t" * 40


@pytest.fixture
def cuenta(tmp_path):
    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = llave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    ruta = tmp_path / "cuenta.json"
    ruta.write_text(json.dumps({"type": "service_account", "project_id": "proyecto-ficticio", "private_key": pem,
                                "client_email": "push@proyecto-ficticio.iam.gserviceaccount.com", "token_uri": fcm.URL_TOKEN}), encoding="utf-8")
    return ruta


def transporte(estado_fcm=200, cuerpo_error=None, vistos=None):
    vistos = [] if vistos is None else vistos

    def h(p):
        vistos.append((str(p.url), dict(p.headers), p.content))
        if str(p.url) == fcm.URL_TOKEN:
            return httpx.Response(200, json={"access_token": "acceso-ficticio", "expires_in": 3600})
        return httpx.Response(estado_fcm, json=cuerpo_error or {"name": "mensaje-ficticio"})
    return httpx.MockTransport(h), vistos


def test_envia_un_mensaje_generico_con_el_token_de_acceso(cuenta):
    t, vistos = transporte()
    c = fcm.ClienteFcm(cuenta, transporte=t)
    assert c.enviar(TOKEN_DISP, "Tinotify", "Hay novedades") == fcm.OK
    url, cabeceras, cuerpo = vistos[-1]
    assert url == "https://fcm.googleapis.com/v1/projects/proyecto-ficticio/messages:send"
    assert cabeceras["authorization"] == "Bearer acceso-ficticio"
    mensaje = json.loads(cuerpo)["message"]
    assert mensaje["token"] == TOKEN_DISP and mensaje["notification"] == {"title": "Tinotify", "body": "Hay novedades"}


def test_el_token_de_acceso_se_reutiliza_hasta_que_vence(cuenta):
    t, vistos = transporte()
    c = fcm.ClienteFcm(cuenta, transporte=t)
    c.enviar(TOKEN_DISP, "a", "b"); c.enviar(TOKEN_DISP, "a", "b")
    assert [v[0] == fcm.URL_TOKEN for v in vistos].count(True) == 1


@pytest.mark.parametrize("estado,cuerpo,esperado", [
    (404, {"error": {"status": "NOT_FOUND"}}, fcm.TOKEN_INVALIDO),
    (400, {"error": {"status": "INVALID_ARGUMENT"}}, fcm.TOKEN_INVALIDO),
    (500, None, fcm.ERROR), (403, {"error": {"status": "PERMISSION_DENIED"}}, fcm.ERROR),
])
def test_clasifica_las_respuestas_de_fcm(cuenta, estado, cuerpo, esperado):
    t, _ = transporte(estado, cuerpo)
    assert fcm.ClienteFcm(cuenta, transporte=t).enviar(TOKEN_DISP, "a", "b") == esperado


def test_un_fallo_de_red_es_error_reintentable_y_no_lanza(cuenta):
    def cae(_): raise httpx.ConnectError("sin red")
    assert fcm.ClienteFcm(cuenta, transporte=httpx.MockTransport(cae)).enviar(TOKEN_DISP, "a", "b") == fcm.ERROR


@pytest.mark.parametrize("contenido", ["no es json", "{}", json.dumps({"type": "authorized_user"})])
def test_cuenta_de_servicio_no_valida(tmp_path, contenido):
    ruta = tmp_path / "x.json"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(fcm.CuentaServicioNoValida):
        fcm.ClienteFcm(ruta)


def test_token_uri_ajeno_se_rechaza(cuenta, tmp_path):
    datos = json.loads(cuenta.read_text(encoding="utf-8"))
    datos["token_uri"] = "https://servidor-ajeno.example/token"
    ruta = tmp_path / "ajena.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(fcm.CuentaServicioNoValida):
        fcm.ClienteFcm(ruta)


class FcmFalso:
    def __init__(self, respuesta=fcm.OK): self.respuesta, self.enviados, self.datos = respuesta, [], []
    def enviar(self, token, titulo, cuerpo, datos=None, privado=False):
        self.enviados.append((token, titulo, cuerpo)); self.datos.append(datos); self.privado = privado
        return self.respuesta


def servicio(fcm_falso):
    s = ServicioMonitor.__new__(ServicioMonitor)
    s._almacen, s._fcm = AlmacenMemoria(), fcm_falso
    return s


def plan(**kw):
    return SimpleNamespace(**{"novedades": 0, "expedientes_nuevos": 0, "expedientes_con_novedades": 0, "anomalias": 0, **kw})


def test_el_push_es_generico_y_va_a_todos_los_dispositivos():
    f = FcmFalso()
    s = servicio(f)
    s.registrar_dispositivo("a" * 30); s.registrar_dispositivo("b" * 30); s.registrar_dispositivo("a" * 30)  # repetido: una sola vez
    s._notificar_push(plan(novedades=2, expedientes_con_novedades=1))
    assert [e[0] for e in f.enviados] == ["a" * 30, "b" * 30]
    assert f.enviados[0][1:] == ("Tinotify", "2 actuaciones nuevas en 1 expediente")
    f.enviados.clear()
    s._notificar_push(plan(expedientes_nuevos=1))
    assert "expediente nuevo" in f.enviados[0][2]


def test_un_token_invalido_se_borra_y_un_error_transitorio_no():
    s = servicio(FcmFalso(fcm.TOKEN_INVALIDO))
    s.registrar_dispositivo("a" * 30)
    s._notificar_push(plan(novedades=1, expedientes_con_novedades=1))
    assert s._almacen.dispositivos() == []
    s = servicio(FcmFalso(fcm.ERROR))
    s.registrar_dispositivo("a" * 30)
    s._notificar_push(plan(novedades=1, expedientes_con_novedades=1))
    assert s._almacen.dispositivos() == ["a" * 30]


def test_sin_fcm_configurado_no_hace_nada():
    s = servicio(None)
    s.registrar_dispositivo("a" * 30)
    s._notificar_push(plan(novedades=1))  # no lanza


def test_la_variable_de_fcm_se_valida_en_la_configuracion(tmp_path, cuenta):
    from backend.tests.test_monitor_real import entorno_monitor
    from backend.tests.test_real_remoto import entorno_valido
    from tinotify.real_remoto.comun import ConfiguracionInsegura
    with pytest.raises(ConfiguracionInsegura):  # sin monitor no hay donde guardar dispositivos
        Config.desde_entorno({**entorno_valido(tmp_path), "TINOTIFY_RR_FCM_CUENTA_SERVICIO": str(cuenta)})
    con_monitor = entorno_monitor(tmp_path)
    with pytest.raises(ConfiguracionInsegura):
        Config.desde_entorno({**con_monitor, "TINOTIFY_RR_FCM_CUENTA_SERVICIO": str(tmp_path / "no-existe.json")})
    assert Config.desde_entorno({**con_monitor, "TINOTIFY_RR_FCM_CUENTA_SERVICIO": str(cuenta)}).fcm_cuenta == cuenta.resolve()
    assert Config.desde_entorno(con_monitor).fcm_cuenta is None


def test_el_push_con_privado_oculta_el_texto_en_la_pantalla_de_bloqueo(cuenta):
    t, vistos = transporte()
    c = fcm.ClienteFcm(cuenta, transporte=t)
    c.enviar(TOKEN_DISP, "Tinotify", "1 actuación nueva en el radicado 123", {"pestana": "casos"}, privado=True)
    assert json.loads(vistos[-1][2])["message"]["android"]["notification"]["visibility"] == "PRIVATE"
    c.enviar(TOKEN_DISP, "Tinotify", "prueba")
    assert "visibility" not in json.loads(vistos[-1][2])["message"]["android"]["notification"]
