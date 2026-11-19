"""Cliente de Brevo (HTTPS), configuración del correo y correo de prueba del propietario. Todo ficticio; sin red."""

import httpx
import pytest

from backend.tests.helpers.correo_falso import CorreoFalso
from backend.tests.test_monitor_real import Mundo, casos_base
from backend.tests.test_real_remoto import CAB
from backend.tests.test_servicio_cuentas import AlmacenMemoria as CuentasMemoria
from tinotify.real_remoto.correo_brevo import ClienteBrevo, CorreoNoValido, URL_BREVO


def test_el_cliente_de_brevo_envia_por_https_con_la_clave_y_no_la_expone():
    visto = {}

    def responder(peticion):
        visto["url"], visto["clave"], visto["cuerpo"] = str(peticion.url), peticion.headers.get("api-key"), peticion.read()
        return httpx.Response(201, json={"messageId": "x"})

    clave = "xkeysib-" + "a" * 40
    cliente = ClienteBrevo(clave, "Remitente@Ejemplo.com", http=httpx.Client(transport=httpx.MockTransport(responder)))
    assert cliente.enviar("persona@ejemplo.com", "Asunto", "texto", "<p>html</p>") is None
    assert visto["url"] == URL_BREVO and visto["clave"] == clave
    assert b"remitente@ejemplo.com" in visto["cuerpo"] and b"persona@ejemplo.com" in visto["cuerpo"]
    assert clave not in repr(cliente)


def test_el_cliente_de_brevo_devuelve_el_motivo_ante_errores_sin_lanzar():
    def caido(peticion):
        raise httpx.ConnectError("sin red")

    clave = "xkeysib-" + "a" * 40
    ip = {"code": "unauthorized", "message": "We have detected you are using an unrecognised IP address"}
    rechazado = ClienteBrevo(clave, "r@ejemplo.com", http=httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(401, json=ip))))
    sin_cuerpo = ClienteBrevo(clave, "r@ejemplo.com", http=httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(500))))
    sin_red = ClienteBrevo(clave, "r@ejemplo.com", http=httpx.Client(transport=httpx.MockTransport(caido)))
    assert rechazado.enviar("p@ejemplo.com", "a", "t", "h").startswith("http_401:unauthorized: We have detected")
    assert sin_cuerpo.enviar("p@ejemplo.com", "a", "t", "h") == "http_500:" and sin_red.enviar("p@ejemplo.com", "a", "t", "h") == "sin_conexion"
    assert "p@ejemplo.com" not in rechazado.enviar("p@ejemplo.com", "a", "t", "h")  # el motivo nunca lleva al destinatario


def test_la_configuracion_de_brevo_se_valida():
    with pytest.raises(CorreoNoValido):
        ClienteBrevo("corta", "r@ejemplo.com")
    with pytest.raises(CorreoNoValido):
        ClienteBrevo("xkeysib-" + "a" * 40, "no-es-correo")


def test_las_variables_de_brevo_se_validan_en_la_configuracion(tmp_path):
    from backend.tests.test_monitor_real import entorno_monitor
    from tinotify.real_remoto.comun import ConfiguracionInsegura
    from tinotify.real_remoto.config import Config
    base = {**entorno_monitor(tmp_path), "TINOTIFY_RR_CUENTAS": "1"}
    clave = "xkeysib-" + "a" * 40
    for malas in ({"TINOTIFY_RR_BREVO_CLAVE": clave},                                        # falta el remitente
                  {"TINOTIFY_RR_BREVO_CLAVE": "corta", "TINOTIFY_RR_BREVO_REMITENTE": "r@ejemplo.com"},
                  {"TINOTIFY_RR_BREVO_CLAVE": clave, "TINOTIFY_RR_BREVO_REMITENTE": "no-es-correo"}):
        with pytest.raises(ConfiguracionInsegura):
            Config.desde_entorno({**base, **malas})
    with pytest.raises(ConfiguracionInsegura):                                               # sin cuentas no tiene sentido
        Config.desde_entorno({**entorno_monitor(tmp_path), "TINOTIFY_RR_BREVO_CLAVE": clave, "TINOTIFY_RR_BREVO_REMITENTE": "r@ejemplo.com"})
    ok = Config.desde_entorno({**base, "TINOTIFY_RR_BREVO_CLAVE": clave, "TINOTIFY_RR_BREVO_REMITENTE": "R@Ejemplo.com"})
    assert ok.correo_api == (clave, "r@ejemplo.com") and clave not in repr(ok)
    assert Config.desde_entorno(base).correo_api is None


def test_solo_el_propietario_prueba_el_correo_y_ve_el_motivo_si_falla():
    sano = Mundo(casos_base(), cuentas=CuentasMemoria(), correo=CorreoFalso())
    roto = Mundo(casos_base(), cuentas=CuentasMemoria(), correo=CorreoFalso(motivo="http_401:unauthorized: IP no autorizada"))
    sin = Mundo(casos_base(), cuentas=CuentasMemoria(), correo=False)
    assert sano.c.post("/auth/correo/prueba").status_code == 401
    assert sano.c.post("/auth/correo/prueba", headers=CAB).json() == {"enviado": True, "motivo": None}
    assert roto.c.post("/auth/correo/prueba", headers=CAB).json() == {"enviado": False, "motivo": "http_401:unauthorized: IP no autorizada"}
    assert sin.c.post("/auth/correo/prueba", headers=CAB).json() == {"enviado": False, "motivo": "correo_no_configurado"}


def test_si_el_proveedor_rechaza_el_correo_se_le_avisa_a_quien_pidio_el_codigo():
    correo = CorreoFalso(motivo="http_401:unauthorized")
    m = Mundo(casos_base(), cuentas=CuentasMemoria(), correo=correo)
    from backend.tests.test_rutas_cuentas import registrar
    assert m.c.post("/auth/registro/codigo", json={"correo": "a@ejemplo.com", "invitacion": m.c.post("/auth/invitaciones", headers=CAB).json()["codigo"]}).json() == {"estado": "fallo_envio"}
