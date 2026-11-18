"""Rutas /auth: registro por invitación, login, sesión, cambio de clave y borrado. Servicio real, almacén en memoria, datos ficticios."""

import pytest

from backend.tests.test_monitor_real import Mundo, casos_base
from backend.tests.test_real_remoto import CAB
from backend.tests.test_servicio_cuentas import AlmacenMemoria as CuentasMemoria

CLAVE = "una-clave-ficticia-1"
CORREO = "persona@ejemplo.com"


@pytest.fixture
def mundo():
    return Mundo(casos_base(), cuentas=CuentasMemoria())


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def invitacion(m):
    r = m.c.post("/auth/invitaciones", headers=CAB)
    assert r.status_code == 200
    return r.json()["codigo"]


def registrar(m, correo=CORREO, clave=CLAVE, codigo=None, consentimiento="consentimiento-v1"):
    return m.c.post("/auth/registro", json={"correo": correo, "clave": clave, "invitacion": codigo or invitacion(m),
                                            "consentimiento": consentimiento, "dispositivo": "telefono"})


def test_sin_la_variable_no_existen_las_rutas_de_cuentas():
    m = Mundo(casos_base())
    assert m.c.post("/auth/login", json={"correo": CORREO, "clave": CLAVE}).status_code == 404


def test_solo_el_propietario_crea_invitaciones(mundo):
    assert mundo.c.post("/auth/invitaciones").status_code == 401
    r = mundo.c.post("/auth/invitaciones", headers=CAB)
    assert r.status_code == 200 and len(r.json()["codigo"]) == 19 and r.json()["vigencia_dias"] == 7


def test_registro_login_sesion_y_logout(mundo):
    r = registrar(mundo)
    assert r.status_code == 200 and r.json()["token"].startswith("tn_")
    token = r.json()["token"]
    assert mundo.c.get("/auth/yo", headers=bearer(token)).json()["usuario"] == r.json()["usuario"]
    l = mundo.c.post("/auth/login", json={"correo": " Persona@Ejemplo.COM ", "clave": CLAVE})
    assert l.status_code == 200 and l.json()["usuario"] == r.json()["usuario"]
    assert mundo.c.post("/auth/logout", headers=bearer(token)).json() == {"cerrada": True}
    assert mundo.c.get("/auth/yo", headers=bearer(token)).status_code == 401


def test_el_token_de_un_usuario_no_abre_los_datos_del_monitor(mundo):
    token = registrar(mundo).json()["token"]
    for ruta in ("/real/expedientes", "/real/monitor/estado", "/real/monitor/ejecuciones", "/real/cases"):
        assert mundo.c.get(ruta, headers=bearer(token)).status_code == 401   # fase 1: los datos siguen siendo solo del propietario
    assert mundo.c.post("/auth/invitaciones", headers=bearer(token)).status_code == 401   # y un usuario no crea invitaciones


def test_el_token_del_propietario_no_es_una_sesion_de_usuario(mundo):
    assert mundo.c.get("/auth/yo", headers=CAB).status_code == 401


def test_registro_rechazado_sin_distinguir_la_causa(mundo):
    r1 = registrar(mundo, codigo="AAAA-AAAA-AAAA-AAAA")                      # invitación inexistente
    registrar(mundo)
    r2 = registrar(mundo)                                                    # correo repetido con otra invitación válida
    assert r1.status_code == r2.status_code == 400 and r1.json() == r2.json()


@pytest.mark.parametrize("cambio,esperado", [
    ({"consentimiento": "otro"}, "consentimiento_no_valido"), ({"correo": "no-es-correo"}, "datos_no_validos:correo_no_valido"),
    ({"clave": "corta"}, "datos_no_validos:clave_longitud"),
])
def test_validaciones_del_registro(mundo, cambio, esperado):
    r = registrar(mundo, **cambio)
    assert r.status_code == 422
    assert esperado in str(r.json()) or r.json().get("detail") == esperado or esperado.split(":")[-1] in str(r.json())


def test_login_incorrecto_y_bloqueo(mundo):
    registrar(mundo)
    for _ in range(5):
        r = mundo.c.post("/auth/login", json={"correo": CORREO, "clave": "clave-mala-ficticia"})
        assert r.status_code == 401
    assert r.json() == mundo.c.post("/auth/login", json={"correo": "nadie@ejemplo.com", "clave": "clave-mala-ficticia"}).json()
    b = mundo.c.post("/auth/login", json={"correo": CORREO, "clave": CLAVE})
    assert b.status_code == 429 and int(b.headers["retry-after"]) > 0


def test_cambio_de_clave_y_borrado_de_cuenta(mundo):
    token = registrar(mundo).json()["token"]
    otro = mundo.c.post("/auth/login", json={"correo": CORREO, "clave": CLAVE}).json()["token"]
    assert mundo.c.post("/auth/cambiar-clave", headers=bearer(token), json={"actual": "no-es", "nueva": "otra-clave-ficticia-2"}).status_code == 401
    assert mundo.c.post("/auth/cambiar-clave", headers=bearer(token), json={"actual": CLAVE, "nueva": "otra-clave-ficticia-2"}).status_code == 200
    assert mundo.c.get("/auth/yo", headers=bearer(otro)).status_code == 401 and mundo.c.get("/auth/yo", headers=bearer(token)).status_code == 200
    assert mundo.c.request("DELETE", "/auth/cuenta", headers=bearer(token), json={"clave": "no-es"}).status_code == 401
    assert mundo.c.request("DELETE", "/auth/cuenta", headers=bearer(token), json={"clave": "otra-clave-ficticia-2"}).json() == {"borrada": True}
    assert mundo.c.get("/auth/yo", headers=bearer(token)).status_code == 401


def test_las_respuestas_no_devuelven_la_clave_ni_el_correo_en_los_errores(mundo):
    for r in (registrar(mundo, clave="corta-ficticia"), mundo.c.post("/auth/login", json={"correo": CORREO, "clave": "clave-secreta-ficticia"})):
        assert "corta-ficticia" not in r.text and "clave-secreta-ficticia" not in r.text and CORREO not in r.text


def test_tope_global_de_intentos(mundo):
    estados = [mundo.c.post("/auth/login", json={"correo": f"x{i}@ejemplo.com", "clave": "clave-mala-ficticia"}).status_code for i in range(32)]
    assert estados.count(429) >= 2 and 401 in estados


def test_la_base_caida_da_503(mundo):
    class Caida(CuentasMemoria):
        def usuario_por_correo_ref(self, ref):
            from tinotify.real_remoto.almacen import AlmacenNoDisponible
            raise AlmacenNoDisponible
    m = Mundo(casos_base(), cuentas=Caida())
    assert m.c.post("/auth/login", json={"correo": CORREO, "clave": CLAVE}).status_code == 503
