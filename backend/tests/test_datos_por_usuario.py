"""Datos del monitor por usuario: cada quien ve y ejecuta solo lo suyo; el propietario conserva lo de siempre. SIGAC simulado."""

from backend.tests.test_monitor_real import Mundo, TOKEN_MONITOR, casos_base
from backend.tests.test_real_remoto import CAB
from backend.tests.test_servicio_cuentas import AlmacenMemoria as CuentasMemoria

CLAVE = "una-clave-ficticia-1"
MON = {"Authorization": f"Bearer {TOKEN_MONITOR}"}


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def nuevo_usuario(m, correo):
    inv = m.c.post("/auth/invitaciones", headers=CAB).json()["codigo"]
    r = m.c.post("/auth/registro", json={"correo": correo, "clave": CLAVE, "invitacion": inv, "consentimiento": "consentimiento-v1"})
    assert r.status_code == 200
    return r.json()["usuario"], bearer(r.json()["token"])


def conectar(m, cab):
    return m.c.post("/real/conectar", headers=cab, json={"usuario": m.sim.usuario, "clave": m.sim.clave})


def ejecutar_usuario(m, uid):
    return m.c.post(f"/real/monitor/ejecutar?usuario={uid}", headers=MON)


def ids(m, cab):
    return {f["numero"]: f["id"] for f in m.c.get("/real/expedientes", headers=cab).json()["expedientes"]}


def mundo_con_propietario():
    casos = casos_base()
    m = Mundo(casos, cuentas=CuentasMemoria())
    m.guardar_credenciales()
    assert m.ejecutar().status_code == 200   # el propietario tiene sus 3 expedientes
    return m, casos


def test_un_usuario_nuevo_no_ve_nada_del_propietario():
    m, _ = mundo_con_propietario()
    _, cab = nuevo_usuario(m, "a@ejemplo.com")
    assert len(ids(m, CAB)) == 3 and ids(m, cab) == {}
    estado = m.c.get("/real/monitor/estado", headers=cab).json()
    assert estado["credenciales_guardadas"] is False and estado["expedientes_en_estado"] == 0 and estado["ultima_ejecucion"] is None
    assert m.c.get("/real/monitor/ejecuciones", headers=cab).json() == {"ejecuciones": []}
    assert m.c.get("/real/monitor/estado", headers=CAB).json()["credenciales_guardadas"] is True


def test_conectar_guarda_las_credenciales_del_usuario_y_el_monitor_las_ejecuta_aparte():
    m, _ = mundo_con_propietario()
    uid, cab = nuevo_usuario(m, "a@ejemplo.com")
    r = conectar(m, cab)
    assert r.status_code == 200 and r.json() == {"conectado": True, "expedientes": 3}
    assert "clave" not in r.text and m.sim.clave not in r.text
    assert m.c.get("/real/monitor/usuarios", headers=MON).json() == {"propietario": True, "usuarios": [uid]}
    e = ejecutar_usuario(m, uid)
    assert e.status_code == 200 and e.json()["resultado"] == "linea_base" and e.json()["expedientes"] == 3
    propios, ajenos = ids(m, cab), ids(m, CAB)
    assert len(propios) == 3 and not set(propios.values()) & set(ajenos.values())     # llaves distintas: no se correlacionan
    assert m.c.get("/real/monitor/estado", headers=cab).json()["expedientes_en_estado"] == 3
    assert len(m.c.get("/real/monitor/ejecuciones", headers=cab).json()["ejecuciones"]) == 1
    assert len(m.c.get("/real/monitor/ejecuciones", headers=CAB).json()["ejecuciones"]) == 1   # la del propietario sigue siendo solo suya


def test_el_usuario_no_puede_leer_ni_marcar_expedientes_ajenos():
    m, _ = mundo_con_propietario()
    _, cab_a = nuevo_usuario(m, "a@ejemplo.com")
    _, cab_b = nuevo_usuario(m, "b@ejemplo.com")
    ajeno = next(iter(ids(m, CAB).values()))
    for cab in (cab_a, cab_b):
        assert m.c.get(f"/real/expedientes/{ajeno}/actuaciones", headers=cab).status_code == 404
        assert m.c.post("/real/expedientes/vistos", headers=cab, json={"id": ajeno}).json() == {"actualizados": 0}
    assert m.c.get(f"/real/expedientes/{ajeno}/actuaciones", headers=CAB).status_code == 200


def test_los_avisos_y_dispositivos_son_de_cada_usuario():
    m, casos = mundo_con_propietario()
    uid, cab = nuevo_usuario(m, "a@ejemplo.com")
    conectar(m, cab)
    ejecutar_usuario(m, uid)
    casos[next(iter(casos))] = list(casos[next(iter(casos))]) + ["ACTUACION_POSTERIOR_FICTICIA"]
    d = ejecutar_usuario(m, uid).json()
    assert d["aviso_nuevo"] and d["novedades"] == 1
    avisos = m.c.get("/real/monitor/avisos", headers=MON).json()["avisos"]
    assert [a["usuario"] for a in avisos] == [uid]
    assert m.c.get("/real/monitor/estado", headers=cab).json()["avisos_pendientes"] == 1
    assert m.c.get("/real/monitor/estado", headers=CAB).json()["avisos_pendientes"] == 0
    assert m.c.post(f"/real/monitor/avisos/{d['aviso_nuevo']}/entregado", headers=MON).json() == {"entregado": True}
    assert m.c.post("/real/dispositivos", headers=cab, json={"token": "t" * 30}).status_code == 200
    assert m.almacen.de(uid).dispositivos() == ["t" * 30] and m.almacen.dispositivos() == []


def test_ejecutar_exige_un_usuario_valido_y_con_credenciales():
    m, _ = mundo_con_propietario()
    uid, cab = nuevo_usuario(m, "a@ejemplo.com")
    assert m.c.post(f"/real/monitor/ejecutar?usuario={uid}", headers=MON).status_code == 412       # sin credenciales
    assert m.c.post("/real/monitor/ejecutar?usuario=no-es-uuid", headers=MON).status_code == 422
    assert m.c.post(f"/real/monitor/ejecutar?usuario={uid}", headers=cab).status_code == 401        # el usuario no dispara el monitor
    assert m.c.post(f"/real/monitor/ejecutar?usuario={uid}", headers=CAB).status_code == 401
    assert m.c.get("/real/monitor/usuarios", headers=cab).status_code == 401


def test_olvidar_credenciales_solo_borra_las_propias():
    m, _ = mundo_con_propietario()
    uid, cab = nuevo_usuario(m, "a@ejemplo.com")
    conectar(m, cab)
    assert m.c.delete("/real/credenciales", headers=cab).status_code == 200
    assert m.c.get("/real/monitor/estado", headers=cab).json()["credenciales_guardadas"] is False
    assert m.c.get("/real/monitor/estado", headers=CAB).json()["credenciales_guardadas"] is True
    assert m.c.get("/real/monitor/usuarios", headers=MON).json()["usuarios"] == []


def test_conectar_con_credenciales_rechazadas_por_sigac_no_guarda_nada():
    m = Mundo(casos_base(), cuentas=CuentasMemoria(), sim_extra={"rechazar_login": True})   # SIGAC rechaza cualquier acceso
    _, cab = nuevo_usuario(m, "a@ejemplo.com")
    r = m.c.post("/real/conectar", headers=cab, json={"usuario": "USUARIO_FICTICIO", "clave": "clave-mala-ficticia"})
    assert r.status_code >= 400 and "clave-mala-ficticia" not in r.text
    assert m.c.get("/real/monitor/estado", headers=cab).json()["credenciales_guardadas"] is False
