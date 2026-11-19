"""Rutas /auth: registro por invitación, login, sesión, cambio de clave y borrado. Servicio real, almacén en memoria, datos ficticios."""

import pytest

from backend.tests.test_monitor_real import Mundo, casos_base
from backend.tests.test_real_remoto import CAB
from backend.tests.test_servicio_cuentas import AlmacenMemoria as CuentasMemoria

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


def pedir_registro(m, correo=CORREO, codigo=None):
    return m.c.post("/auth/registro/codigo", json={"correo": correo, "invitacion": codigo or invitacion(m)})


def registrar(m, correo=CORREO, codigo=None, consentimiento="consentimiento-v1", codigo_correo=None):
    """Cuenta nueva por el camino real: pide el código, lo lee del correo (falso) y termina el registro."""
    inv = codigo or invitacion(m)
    assert pedir_registro(m, correo, inv).json() == {"estado": "enviado"}
    return m.c.post("/auth/registro", json={"correo": correo, "codigo": codigo_correo or m.correo.codigo(), "invitacion": inv,
                                            "consentimiento": consentimiento, "dispositivo": "telefono"})


def entrar(m, correo=CORREO):
    assert m.c.post("/auth/entrar/codigo", json={"correo": correo}).json() == {"estado": "enviado"}
    return m.c.post("/auth/entrar", json={"correo": correo, "codigo": m.correo.codigo(), "dispositivo": "otro-telefono"})


def test_solo_el_propietario_crea_invitaciones(mundo):
    assert mundo.c.post("/auth/invitaciones").status_code == 401
    r = mundo.c.post("/auth/invitaciones", headers=CAB)
    assert r.status_code == 200 and len(r.json()["codigo"]) == 19 and r.json()["vigencia_dias"] == 7


def test_registro_entrada_sesion_y_logout(mundo):
    r = registrar(mundo)
    assert r.status_code == 200 and r.json()["token"].startswith("tn_")
    token = r.json()["token"]
    assert mundo.c.get("/auth/yo", headers=bearer(token)).json() == {"usuario": r.json()["usuario"], "admin": False}
    otra = entrar(mundo)
    assert otra.status_code == 200 and otra.json()["usuario"] == r.json()["usuario"] and otra.json()["token"] != token
    assert mundo.c.post("/auth/logout", headers=bearer(token)).json() == {"cerrada": True}
    assert mundo.c.get("/auth/yo", headers=bearer(token)).status_code == 401 and mundo.c.get("/auth/yo", headers=bearer(otra.json()["token"])).status_code == 200


def test_el_token_de_un_usuario_solo_abre_sus_propios_datos(mundo):
    token = registrar(mundo).json()["token"]
    assert mundo.c.get("/real/expedientes", headers=bearer(token)).json() == {"expedientes": []}      # vacío: no ve los del propietario
    assert mundo.c.get("/real/monitor/estado", headers=bearer(token)).json()["credenciales_guardadas"] is False
    assert mundo.c.get("/real/cases", headers=bearer(token)).status_code == 401                       # rutas del propietario: solo con su token
    assert mundo.c.post("/auth/invitaciones", headers=bearer(token)).status_code == 401              # un usuario no crea invitaciones


def test_el_token_del_propietario_no_es_una_sesion_de_usuario(mundo):
    assert mundo.c.get("/auth/yo", headers=CAB).status_code == 401


def test_pedir_el_codigo_de_registro_dice_que_pasa(mundo):
    assert pedir_registro(mundo, codigo="AAAA-AAAA-AAAA-AAAA").json() == {"estado": "invitacion_invalida"}
    assert pedir_registro(mundo, correo="no-es-correo").json() == {"estado": "correo_invalido"}
    registrar(mundo)
    assert pedir_registro(mundo).json() == {"estado": "ya_registrado"}
    assert len(mundo.correo.enviados) == 1


def test_registro_rechazado_sin_distinguir_la_causa(mundo):
    inv = invitacion(mundo)
    pedir_registro(mundo, codigo=inv)
    mal_codigo = mundo.c.post("/auth/registro", json={"correo": CORREO, "codigo": "AAAA-AAAA", "invitacion": inv, "consentimiento": "consentimiento-v1"})
    otro_correo = mundo.c.post("/auth/registro", json={"correo": "otra@ejemplo.com", "codigo": mundo.correo.codigo(), "invitacion": inv,
                                                       "consentimiento": "consentimiento-v1"})
    assert mal_codigo.status_code == otro_correo.status_code == 400 and mal_codigo.json() == otro_correo.json()


@pytest.mark.parametrize("cambio,esperado", [({"consentimiento": "otro"}, 422), ({"correo": "no-es-correo"}, 422)])
def test_validaciones_del_registro(mundo, cambio, esperado):
    inv = invitacion(mundo)
    pedir_registro(mundo, codigo=inv)
    cuerpo = {"correo": CORREO, "codigo": mundo.correo.codigo(), "invitacion": inv, "consentimiento": "consentimiento-v1", **cambio}
    assert mundo.c.post("/auth/registro", json=cuerpo).status_code == esperado


def test_entrar_con_un_codigo_malo_o_de_otro_correo_da_el_mismo_error(mundo):
    registrar(mundo)
    mundo.c.post("/auth/entrar/codigo", json={"correo": CORREO})
    bueno = mundo.correo.codigo()
    a = mundo.c.post("/auth/entrar", json={"correo": CORREO, "codigo": "AAAA-AAAA"})
    b = mundo.c.post("/auth/entrar", json={"correo": "nadie@ejemplo.com", "codigo": bueno})
    assert a.status_code == b.status_code == 400 and a.json() == b.json()
    assert mundo.c.post("/auth/entrar", json={"correo": CORREO, "codigo": bueno}).status_code == 200


def test_pedir_acceso_dice_que_paso(mundo):
    assert mundo.c.post("/auth/entrar/codigo", json={"correo": "nadie@ejemplo.com"}).json() == {"estado": "no_registrado"}
    registrar(mundo)
    estados = [mundo.c.post("/auth/entrar/codigo", json={"correo": CORREO}).json()["estado"] for _ in range(4)]
    assert estados == ["enviado"] * 3 + ["limite"]


def test_borrar_la_cuenta_exige_escribir_el_correo(mundo):
    token = registrar(mundo).json()["token"]
    assert mundo.c.request("DELETE", "/auth/cuenta", headers=bearer(token), json={"correo": "otra@ejemplo.com"}).status_code == 400
    assert mundo.c.request("DELETE", "/auth/cuenta", headers=bearer(token), json={"correo": " Persona@Ejemplo.com "}).json() == {"borrada": True}
    assert mundo.c.get("/auth/yo", headers=bearer(token)).status_code == 401


def test_ya_no_existen_las_rutas_de_contrasena(mundo):
    for ruta in ("/auth/login", "/auth/cambiar-clave", "/auth/restablecer", "/auth/recuperar"):
        assert mundo.c.post(ruta, json={"correo": CORREO, "clave": "x" * 12}).status_code in (404, 405)


def test_las_respuestas_no_devuelven_el_codigo_ni_el_correo_en_los_errores(mundo):
    registrar(mundo)
    r = mundo.c.post("/auth/entrar", json={"correo": CORREO, "codigo": "ZZZZ-ZZZZ"})
    assert "ZZZZ" not in r.text and CORREO not in r.text


def test_tope_global_de_intentos(mundo):
    estados = [mundo.c.post("/auth/entrar", json={"correo": f"x{i}@ejemplo.com", "codigo": "AAAA-AAAA"}).status_code for i in range(32)]
    assert estados.count(429) >= 2 and 400 in estados


def test_tope_global_de_correos(mundo):
    estados = [mundo.c.post("/auth/entrar/codigo", json={"correo": f"x{i}@ejemplo.com"}).status_code for i in range(12)]
    assert estados.count(429) >= 2 and estados[0] == 200


def test_la_base_caida_da_503():
    class Caida(CuentasMemoria):
        def usuario_por_correo_ref(self, ref):
            from tinotify.real_remoto.almacen import AlmacenNoDisponible
            raise AlmacenNoDisponible
    m = Mundo(casos_base(), cuentas=Caida())
    assert m.c.post("/auth/entrar/codigo", json={"correo": CORREO}).status_code == 503
