"""Panel de administración: lo que ve y puede hacer el propietario o una persona administradora. Servicio real, almacén en memoria, datos ficticios."""

import pytest

from backend.tests.test_monitor_real import Mundo, casos_base
from backend.tests.test_real_remoto import CAB
from backend.tests.test_rutas_cuentas import CORREO, bearer, registrar
from backend.tests.test_servicio_cuentas import AlmacenMemoria as CuentasMemoria

OTRO = "otra@ejemplo.com"


@pytest.fixture
def mundo():
    almacen = CuentasMemoria()
    m = Mundo(casos_base(), cuentas=almacen)
    m.cuentas = almacen
    return m


def usuarios(m, cab=CAB):
    r = m.c.get("/admin/usuarios", headers=cab)
    assert r.status_code == 200
    return r.json()["usuarios"]


def promover(m, token):
    uid = m.c.get("/auth/yo", headers=bearer(token)).json()["usuario"]
    assert m.c.post(f"/admin/usuarios/{uid}/admin", headers=CAB, json={"admin": True}).status_code == 200
    return uid


def test_el_panel_exige_ser_propietario_o_administrador(mundo):
    token = registrar(mundo).json()["token"]
    assert mundo.c.get("/admin/usuarios").status_code == 401
    assert mundo.c.get("/admin/usuarios", headers=bearer(token)).status_code == 401           # un usuario común no entra
    assert mundo.c.post("/auth/invitaciones", headers=bearer(token)).status_code == 401
    promover(mundo, token)
    assert mundo.c.get("/admin/usuarios", headers=bearer(token)).status_code == 200            # ya administra
    assert mundo.c.post("/auth/invitaciones", headers=bearer(token)).status_code == 200        # y puede invitar
    assert mundo.c.get("/auth/yo", headers=bearer(token)).json()["admin"] is True


def test_el_listado_muestra_correo_y_estado_pero_nunca_credenciales(mundo):
    registrar(mundo)
    filas = usuarios(mundo)
    assert len(filas) == 1 and filas[0]["correo"] == CORREO and filas[0]["activo"] is True and filas[0]["es_admin"] is False
    assert set(filas[0]) == {"id", "activo", "es_admin", "desde", "correo", "con_credenciales", "expedientes", "ultima_resultado", "ultima_inicio"}
    assert "scrypt" not in repr(filas)


def test_suspender_bloquea_el_acceso_y_cierra_las_sesiones_y_reactivar_lo_devuelve(mundo):
    token = registrar(mundo).json()["token"]
    uid = usuarios(mundo)[0]["id"]
    assert mundo.c.post(f"/admin/usuarios/{uid}/activo", headers=CAB, json={"activo": False}).status_code == 200
    assert mundo.c.get("/auth/yo", headers=bearer(token)).status_code == 401
    assert mundo.c.post("/auth/entrar/codigo", json={"correo": CORREO}).json() == {"estado": "no_registrado"}   # suspendida: no recibe códigos
    assert mundo.c.post(f"/admin/usuarios/{uid}/activo", headers=CAB, json={"activo": True}).status_code == 200
    assert mundo.c.post("/auth/entrar/codigo", json={"correo": CORREO}).json() == {"estado": "enviado"}


def test_borrar_datos_deja_la_cuenta_y_eliminar_la_quita(mundo):
    registrar(mundo)
    uid = usuarios(mundo)[0]["id"]
    assert mundo.c.request("DELETE", f"/admin/usuarios/{uid}/datos", headers=CAB).json() == {"borrados": True}
    assert uid in mundo.cuentas.borrados and len(usuarios(mundo)) == 1                         # la cuenta sigue
    assert mundo.c.request("DELETE", f"/admin/usuarios/{uid}", headers=CAB).json() == {"eliminada": True}
    assert usuarios(mundo) == []
    assert mundo.c.post("/auth/entrar/codigo", json={"correo": CORREO}).json() == {"estado": "no_registrado"}


def test_una_persona_administradora_no_puede_suspenderse_borrarse_ni_quitarse_el_rol(mundo):
    token = registrar(mundo).json()["token"]
    yo = promover(mundo, token)
    mio = bearer(token)
    assert mundo.c.post(f"/admin/usuarios/{yo}/activo", headers=mio, json={"activo": False}).status_code == 409
    assert mundo.c.post(f"/admin/usuarios/{yo}/admin", headers=mio, json={"admin": False}).status_code == 409
    assert mundo.c.request("DELETE", f"/admin/usuarios/{yo}", headers=mio).status_code == 409
    assert mundo.c.request("DELETE", f"/admin/usuarios/{yo}/datos", headers=mio).status_code == 200   # vaciar sus propios datos sí
    otro = registrar(mundo, correo=OTRO).json()["token"]
    otro_id = mundo.c.get("/auth/yo", headers=bearer(otro)).json()["usuario"]
    assert mundo.c.post(f"/admin/usuarios/{otro_id}/activo", headers=mio, json={"activo": False}).status_code == 200


def test_ids_invalidos_y_usuarios_inexistentes(mundo):
    assert mundo.c.post("/admin/usuarios/no-es-un-id/activo", headers=CAB, json={"activo": False}).status_code == 422
    fantasma = "00000000-0000-0000-0000-000000000000"
    assert mundo.c.request("DELETE", f"/admin/usuarios/{fantasma}", headers=CAB).status_code == 404
    assert mundo.c.post(f"/admin/usuarios/{fantasma}/admin", headers=CAB, json={"admin": True}).status_code == 404
    assert mundo.c.post(f"/admin/usuarios/{fantasma}/activo", headers=CAB, json={"activo": True, "otro": 1}).status_code == 422
