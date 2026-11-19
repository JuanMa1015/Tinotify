"""Recuperación de contraseña con código por correo (Brevo, simulado). Todo ficticio; sin red ni base de datos."""

import httpx
import pytest

from backend.tests.test_monitor_real import Mundo, casos_base
from backend.tests.test_rutas_cuentas import CLAVE, CORREO, bearer, registrar
from backend.tests.test_servicio_cuentas import AlmacenMemoria as CuentasMemoria, LLAVE, Reloj
from tinotify.real_remoto import cuentas as c
from tinotify.real_remoto.correo_brevo import ClienteBrevo, CorreoNoValido, URL_BREVO
from tinotify.real_remoto.servicio_cuentas import CodigoNoValido, ServicioCuentas

NUEVA = "otra-clave-ficticia-2"


class CorreoFalso:
    def __init__(self):
        self.enviados = []

    def enviar(self, destino, asunto, texto, html):
        self.enviados.append({"destino": destino, "asunto": asunto, "texto": texto, "html": html})
        return True

    def codigo(self, i=-1):
        import re
        return re.search(r"[A-Z2-9]{4}-[A-Z2-9]{4}", self.enviados[i]["texto"]).group()


@pytest.fixture
def mundo():
    correo = CorreoFalso()
    m = Mundo(casos_base(), cuentas=CuentasMemoria(), correo=correo)
    return m, correo


def recuperar(m, correo=CORREO):
    return m.c.post("/auth/recuperar", json={"correo": correo})


def restablecer(m, codigo, clave=NUEVA, correo=CORREO):
    return m.c.post("/auth/restablecer", json={"correo": correo, "codigo": codigo, "clave": clave})


def test_se_envia_un_codigo_solo_a_cuentas_existentes_y_la_respuesta_es_la_misma(mundo):
    m, correo = mundo
    registrar(m)
    existe, no_existe = recuperar(m), recuperar(m, "nadie@ejemplo.com")
    assert existe.status_code == no_existe.status_code == 200 and existe.json() == no_existe.json() == {"solicitado": True}
    assert [e["destino"] for e in correo.enviados] == [CORREO]
    assert len(correo.codigo()) == 9 and "15 minutos" in correo.enviados[0]["texto"]


def test_con_el_codigo_se_cambia_la_clave_y_se_cierran_todas_las_sesiones(mundo):
    m, correo = mundo
    token = registrar(m).json()["token"]
    recuperar(m)
    assert restablecer(m, correo.codigo()).json() == {"restablecida": True}
    assert m.c.get("/auth/yo", headers=bearer(token)).status_code == 401            # la sesión anterior murió
    assert m.c.post("/auth/login", json={"correo": CORREO, "clave": CLAVE}).status_code == 401
    assert m.c.post("/auth/login", json={"correo": CORREO, "clave": NUEVA}).status_code == 200
    assert restablecer(m, correo.codigo()).status_code == 400                        # un código sirve una sola vez


def test_un_codigo_equivocado_cinco_veces_mata_el_codigo_aunque_luego_se_acierte(mundo):
    m, correo = mundo
    registrar(m)
    recuperar(m)
    for _ in range(5):
        assert restablecer(m, "AAAA-AAAA").status_code == 400
    assert restablecer(m, correo.codigo()).status_code == 400


def test_el_codigo_de_una_cuenta_no_sirve_para_otra(mundo):
    m, correo = mundo
    registrar(m)
    registrar(m, correo="otra@ejemplo.com")
    recuperar(m)
    assert restablecer(m, correo.codigo(), correo="otra@ejemplo.com").status_code == 400
    assert restablecer(m, correo.codigo()).status_code == 200


def test_solo_tres_solicitudes_por_hora_y_cada_codigo_nuevo_anula_el_anterior(mundo):
    m, correo = mundo
    registrar(m)
    for _ in range(5):
        recuperar(m)
    assert len(correo.enviados) == 3
    assert restablecer(m, correo.codigo(0)).status_code == 400                       # los anteriores quedaron anulados
    assert restablecer(m, correo.codigo(-1)).status_code == 200


def test_una_clave_nueva_debil_se_rechaza_sin_gastar_el_codigo(mundo):
    m, correo = mundo
    registrar(m)
    recuperar(m)
    assert restablecer(m, correo.codigo(), clave="corta").status_code == 422
    assert restablecer(m, correo.codigo()).status_code == 200


def test_sin_correo_configurado_la_recuperacion_no_esta_disponible_y_no_falla():
    m = Mundo(casos_base(), cuentas=CuentasMemoria())
    registrar(m)
    assert m.c.get("/auth/recuperacion").json() == {"disponible": False}
    assert recuperar(m).status_code == 200


def test_la_disponibilidad_se_anuncia_con_el_correo_configurado(mundo):
    m, _ = mundo
    assert m.c.get("/auth/recuperacion").json() == {"disponible": True}


def test_el_codigo_vence_a_los_quince_minutos():
    reloj, correo = Reloj(), CorreoFalso()
    s = ServicioCuentas(CuentasMemoria(), LLAVE, reloj=reloj, n_scrypt=2**10, correo=correo)
    s.registrar(CORREO, CLAVE, s.crear_invitacion(), "consentimiento-v1")
    assert s.solicitar_recuperacion(CORREO) is True
    reloj.avanzar(minutes=16)
    with pytest.raises(CodigoNoValido):
        s.restablecer_clave(CORREO, correo.codigo(), NUEVA)
    assert s.solicitar_recuperacion(CORREO) is True
    s.restablecer_clave(CORREO, correo.codigo(), NUEVA)


def test_el_hash_del_codigo_esta_ligado_al_usuario_y_normaliza():
    assert c.hash_recuperacion("u1", "abcd-efgh") == c.hash_recuperacion("u1", " ABCD EFGH ")
    assert c.hash_recuperacion("u1", "ABCD-EFGH") != c.hash_recuperacion("u2", "ABCD-EFGH")


def test_el_cliente_de_brevo_envia_por_https_con_la_clave_y_no_la_expone():
    visto = {}

    def responder(peticion):
        visto["url"], visto["clave"], visto["cuerpo"] = str(peticion.url), peticion.headers.get("api-key"), peticion.read()
        return httpx.Response(201, json={"messageId": "x"})

    clave = "xkeysib-" + "a" * 40
    cliente = ClienteBrevo(clave, "Remitente@Ejemplo.com", http=httpx.Client(transport=httpx.MockTransport(responder)))
    assert cliente.enviar("persona@ejemplo.com", "Asunto", "texto", "<p>html</p>") is True
    assert visto["url"] == URL_BREVO and visto["clave"] == clave
    assert b"remitente@ejemplo.com" in visto["cuerpo"] and b"persona@ejemplo.com" in visto["cuerpo"]
    assert clave not in repr(cliente)


def test_el_cliente_de_brevo_devuelve_false_ante_errores_sin_lanzar():
    def caido(peticion):
        raise httpx.ConnectError("sin red")

    clave = "xkeysib-" + "a" * 40
    rechazado = ClienteBrevo(clave, "r@ejemplo.com", http=httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(401))))
    sin_red = ClienteBrevo(clave, "r@ejemplo.com", http=httpx.Client(transport=httpx.MockTransport(caido)))
    assert rechazado.enviar("p@ejemplo.com", "a", "t", "h") is False and sin_red.enviar("p@ejemplo.com", "a", "t", "h") is False


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
