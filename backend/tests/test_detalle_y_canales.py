"""Detalle de un expediente bajo demanda (SIGAC simulado) y estado de los canales de aviso. Datos ficticios."""

from backend.tests.test_monitor_real import Mundo, TOKEN_MONITOR, casos_base
from backend.tests.test_real_remoto import CAB

MON = {"Authorization": f"Bearer {TOKEN_MONITOR}"}


def listos():
    casos = casos_base()
    m = Mundo(casos)
    m.guardar_credenciales()
    assert m.ejecutar().status_code == 200
    return m, casos


def ids(m):
    return {f["numero"]: f["id"] for f in m.c.get("/real/expedientes", headers=CAB).json()["expedientes"]}


def test_el_detalle_devuelve_las_actuaciones_leidas_en_ese_momento_sin_guardarlas():
    m, casos = listos()
    numero, ref = next(iter(ids(m).items()))
    antes = m.sim.logins
    r = m.c.get(f"/real/expedientes/{ref}/actuaciones", headers=CAB)
    assert r.status_code == 200
    acts = r.json()["actuaciones"]
    assert len(acts) == len(casos[numero]) and all(
        set(a) == {"fecha", "etapa", "origen", "destino", "remitente", "descripcion", "anexos"} for a in acts)
    assert m.sim.logins == antes + 1                      # una autenticación para leer ese expediente
    m.c.get(f"/real/expedientes/{ref}/actuaciones", headers=CAB)
    assert m.sim.logins == antes + 1                      # la segunda consulta usa la caché breve: no vuelve a iniciar sesión
    assert "descripcion" not in str(m.almacen.__dict__.get("expedientes_cifrados"))  # nada del contenido en el almacén


def test_el_detalle_valida_el_id_y_exige_el_token_de_la_app():
    m, _ = listos()
    ref = next(iter(ids(m).values()))
    assert m.c.get(f"/real/expedientes/{ref}/actuaciones").status_code == 401
    assert m.c.get(f"/real/expedientes/{ref}/actuaciones", headers=MON).status_code == 401
    assert m.c.get("/real/expedientes/no-es-un-id/actuaciones", headers=CAB).status_code == 422
    assert m.c.get(f"/real/expedientes/{'0' * 64}/actuaciones", headers=CAB).status_code == 404


def test_el_detalle_sin_credenciales_o_con_la_base_caida():
    m, _ = listos()
    ref = next(iter(ids(m).values()))
    m.c.delete("/real/credenciales", headers=CAB)
    m.servicio_cache = None
    assert m.c.get(f"/real/expedientes/{ref}/actuaciones", headers=CAB).status_code in (404, 412)
    m.almacen.caido = True
    assert m.c.get(f"/real/expedientes/{ref}/actuaciones", headers=CAB).status_code == 503


def test_el_correo_informa_su_estado_y_la_actividad_lo_muestra():
    casos = casos_base()
    m = Mundo(casos)
    m.guardar_credenciales()
    m.ejecutar()
    casos[next(iter(casos))] = list(casos[next(iter(casos))]) + ["ACTUACION_POSTERIOR_FICTICIA"]
    d = m.ejecutar().json()
    aviso = d["aviso_nuevo"]
    assert aviso
    assert m.c.post(f"/real/monitor/avisos/{aviso}/canal", json={"canal": "correo", "estado": "enviado"}).status_code == 401
    assert m.c.post(f"/real/monitor/avisos/{aviso}/canal", headers=CAB, json={"canal": "correo", "estado": "enviado"}).status_code == 401
    assert m.c.post(f"/real/monitor/avisos/{aviso}/canal", headers=MON, json={"canal": "sms", "estado": "enviado"}).status_code == 422
    assert m.c.post(f"/real/monitor/avisos/{aviso}/canal", headers=MON, json={"canal": "correo", "estado": "quizas"}).status_code == 422
    assert m.c.post(f"/real/monitor/avisos/{'0' * 8}-0000-0000-0000-{'0' * 12}/canal", headers=MON, json={"canal": "correo", "estado": "enviado"}).status_code == 404
    assert m.c.post(f"/real/monitor/avisos/{aviso}/canal", headers=MON, json={"canal": "correo", "estado": "fallido"}).json() == {"registrado": True}
    ultima = m.c.get("/real/monitor/ejecuciones", headers=CAB).json()["ejecuciones"][0]
    assert ultima["aviso"] == {"push": "no_configurado", "correo": "fallido"}   # sin FCM en la prueba: el push consta como no configurado


def test_los_anexos_indican_si_tienen_enlace_de_descarga_sin_exponer_la_referencia():
    from tinotify.domain.actuaciones import Actuacion, Anexo
    from datetime import datetime
    from tinotify.real_remoto.servicio_monitor import _actuacion_json
    a = Actuacion(etapa="E", origen="O", destino="D", fecha=datetime(2026, 1, 1), remitente="R", descripcion="D",
                  anexos=(Anexo("Con enlace", "a.pdf", "general.descargarAnexo.con?codigo=X"), Anexo("Sin enlace", "", "", sin_enlace=True)))
    r = _actuacion_json(a)["anexos"]
    assert [x["con_enlace"] for x in r] == [True, False] and "descargarAnexo" not in str(r) and "codigo" not in str(r)
