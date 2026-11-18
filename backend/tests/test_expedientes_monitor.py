"""Listado cifrado de expedientes, novedades sin ver, push con texto genérico y notificación de prueba. SIGAC y FCM simulados."""

import json

from backend.tests.helpers.monitor_real import AlmacenMemoria
from backend.tests.test_monitor_real import Mundo, casos_base
from backend.tests.test_real_remoto import CAB
from tinotify.real_remoto import cifrado
from tinotify.real_remoto.servicio_monitor import _texto_push
from types import SimpleNamespace


def listar(m):
    return m.c.get("/real/expedientes", headers=CAB)


def test_el_listado_se_guarda_cifrado_y_la_app_lo_ve_al_instante():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    assert m.ejecutar().status_code == 200
    r = listar(m)
    assert r.status_code == 200
    filas = r.json()["expedientes"]
    assert len(filas) == 3 and all(set(f) == {"id", "numero", "cliente", "estado", "novedades_no_vistas", "nuevo", "ultima_novedad"} for f in filas)
    assert {f["numero"] for f in filas} == {101, 202, 404} or len({f["numero"] for f in filas}) == 3
    # En la base solo hay cifrado: ni el número ni el cliente aparecen en claro.
    # Se compara contra los bytes cifrados (no contra su representación hexadecimal, donde "101" podría aparecer por azar).
    brutos = b"".join(bytes(v["cifrado"]) for v in m.almacen.__dict__["expedientes_cifrados"].values())
    for f in filas:
        assert f["cliente"].encode() not in brutos and f["id"].isalnum()


def test_requiere_el_token_de_la_app():
    m = Mundo(casos_base())
    assert m.c.get("/real/expedientes").status_code == 401
    assert m.c.post("/real/expedientes/vistos", json={}).status_code == 401


def test_las_novedades_se_acumulan_y_se_marcan_como_vistas():
    casos = casos_base()
    m = Mundo(casos)
    m.guardar_credenciales()
    m.ejecutar()                                  # línea base: nada pendiente
    assert all(f["novedades_no_vistas"] == 0 and not f["nuevo"] for f in listar(m).json()["expedientes"])
    primero = next(iter(casos))
    casos[primero] = list(casos[primero]) + ["ACTUACION_POSTERIOR_FICTICIA"]   # el expediente de prueba recibe una actuación
    m.ejecutar()
    filas = listar(m).json()["expedientes"]
    con = [f for f in filas if f["novedades_no_vistas"] > 0]
    assert len(con) == 1 and con[0]["novedades_no_vistas"] == 1 and filas[0]["id"] == con[0]["id"]  # primero en la lista
    assert m.c.post("/real/expedientes/vistos", headers=CAB, json={"id": "no-es-un-id"}).status_code == 422
    assert m.c.post("/real/expedientes/vistos", headers=CAB, json={"id": con[0]["id"]}).json() == {"actualizados": 1}
    assert all(f["novedades_no_vistas"] == 0 for f in listar(m).json()["expedientes"])


def test_un_dato_alterado_o_con_otra_llave_no_se_muestra():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    m.ejecutar()
    ref = next(iter(m.almacen.__dict__["expedientes_cifrados"]))
    m.almacen.__dict__["expedientes_cifrados"][ref]["cifrado"] = bytes(40)
    assert len(listar(m).json()["expedientes"]) == 2


def test_el_cifrado_liga_el_dato_a_su_expediente():
    llave, ref, otra = b"k" * 32, "a" * 64, "b" * 64
    nonce, c = cifrado.cifrar_expediente(llave, ref, 123, "CLIENTE_FICTICIO", "Activo")
    assert cifrado.descifrar_expediente(llave, ref, nonce, c) == (123, "CLIENTE_FICTICIO", "Activo")
    for args in ((llave, otra, nonce, c), (b"z" * 32, ref, nonce, c)):
        try:
            cifrado.descifrar_expediente(*args)
            raise AssertionError("debió fallar")
        except cifrado.CifradoNoValido:
            pass


def test_texto_del_push_sin_metadatos_solo_lleva_conteos_y_destino():
    p = lambda **k: SimpleNamespace(**{"novedades": 0, "expedientes_nuevos": 0, "expedientes_con_novedades": 0, "anomalias": 0, **k})  # noqa: E731
    assert _texto_push(p(novedades=3, expedientes_con_novedades=2)) == ("3 actuaciones nuevas en 2 expedientes", "casos", None)
    assert _texto_push(p(novedades=1, expedientes_con_novedades=1, expedientes_nuevos=1)) == ("1 actuación nueva en 1 expediente y 1 expediente nuevo", "casos", None)
    assert _texto_push(p(expedientes_nuevos=1)) == ("Apareció un expediente nuevo en tu cuenta", "casos", None)
    assert _texto_push(p(expedientes_nuevos=4))[0] == "Aparecieron 4 expedientes nuevos en tu cuenta"
    assert _texto_push(p(anomalias=1)) == ("Una lectura necesita tu revisión en SIGAC", "actividad", None)


def _plan_con(cambios, **k):
    base = {"novedades": 0, "expedientes_nuevos": 0, "expedientes_con_novedades": 0, "anomalias": 0, "primera_ejecucion": False, "cambios": cambios}
    return SimpleNamespace(**{**base, **k})


def _c(ref, accion, n=0):
    return SimpleNamespace(caso_ref=ref, accion=accion, novedades=n)


META = {"a" * 64: (91256, "CLIENTE UNO", "En proceso"), "b" * 64: (92617, "CLIENTE DOS", "En proceso"),
        "c" * 64: (93001, "CLIENTE TRES", "En proceso"), "d" * 64: (94002, "CLIENTE CUATRO", "En proceso")}


def test_el_push_nombra_el_radicado_y_abre_directamente_el_expediente_unico():
    texto, pestana, ref = _texto_push(_plan_con([_c("a" * 64, "novedades", 2), _c("b" * 64, "sin_cambios")]), META)
    assert (texto, pestana, ref) == ("2 actuaciones nuevas en el radicado 91256", "casos", "a" * 64)
    assert "CLIENTE" not in texto                                                      # el nombre del cliente no va en el push


def test_el_push_con_varios_expedientes_los_lista_hasta_tres_y_luego_cuenta():
    dos = _texto_push(_plan_con([_c("a" * 64, "novedades", 1), _c("b" * 64, "novedades", 2)]), META)
    assert dos == ("3 actuaciones nuevas en los radicados 91256 y 92617", "casos", None)
    tres = _texto_push(_plan_con([_c("a" * 64, "novedades", 1), _c("b" * 64, "novedades", 1), _c("c" * 64, "novedades", 1)]), META)
    assert tres[0] == "3 actuaciones nuevas en los radicados 91256, 92617 y 93001"
    cuatro = _texto_push(_plan_con([_c(r * 64, "novedades", 1) for r in "abcd"]), META)
    assert cuatro[0] == "4 actuaciones nuevas en 4 expedientes" and cuatro[2] is None


def test_el_push_de_expediente_nuevo_y_la_primera_ejecucion_no_avisa_de_nuevos():
    assert _texto_push(_plan_con([_c("b" * 64, "nuevo")]), META) == ("Expediente nuevo: 92617", "casos", "b" * 64)
    assert _texto_push(_plan_con([_c("a" * 64, "novedades", 1), _c("b" * 64, "nuevo")]), META)[0] == "1 actuación nueva en el radicado 91256 · Expediente nuevo: 92617"
    texto, _, _ = _texto_push(_plan_con([_c("a" * 64, "nuevo"), _c("b" * 64, "nuevo")], primera_ejecucion=True, anomalias=1), META)
    assert texto == "Una lectura necesita tu revisión en SIGAC"                         # línea base: no hay nada que decir de "nuevos"


def test_la_notificacion_de_prueba_no_toca_el_estado_y_exige_fcm():
    m = Mundo(casos_base())
    assert m.c.post("/real/dispositivos/prueba", headers=CAB).status_code == 412      # sin FCM configurado
    assert m.c.post("/real/dispositivos/prueba").status_code == 401
    assert m.c.post("/real/dispositivos", headers=CAB, json={"token": "t" * 30}).json() == {"registrado": True}
    assert m.almacen.dispositivos() == ["t" * 30]
