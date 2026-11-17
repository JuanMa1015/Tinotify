"""Monitor real: cifrado, configuración, lógica de comparación y rutas (HTTP simulado + almacén en memoria).

Todo ficticio. Estas pruebas NO demuestran nada sobre SIGAC real; la integración con PostgreSQL se prueba aparte (contenedor desechable).
"""

from collections import Counter
import json
import logging
import threading

import pytest

from backend.tests.helpers.monitor_real import AlmacenMemoria, SigacSimulado
from backend.tests.test_contrato_expediente import CLAVE_TEST, politica_de_prueba
from backend.tests.test_real_remoto import CAB, TOKEN, cliente_http, config, entorno_valido, login, referencia_de
from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.real_remoto import cifrado
from tinotify.real_remoto.app import crear_app
from tinotify.real_remoto.config import Config, ConfigMonitor, ConfigPg, ConfiguracionInsegura, clave_desde_texto
from tinotify.real_remoto.monitor import EstadoPrevio, caso_ref, planificar
from tinotify.services.historial_temporal import HistorialTemporal
from tinotify.services.referencia_portable import huella_portable

LLAVE = bytes(range(1, 33))
TOKEN_MONITOR = "monitor-" + "mnopqrstuv" * 4
H = lambda n: huella_portable(CLAVE_TEST, f"{n:064x}")  # noqa: E731  huellas con clave ficticias
REF = lambda n: caso_ref(CLAVE_TEST, INSTANCIA_REAL, n)  # noqa: E731


# --- Cifrado de credenciales ---------------------------------------------------------------------------------------------

def test_el_cifrado_ida_y_vuelta_no_deja_texto_claro_y_rechaza_llaves_ajenas_o_datos_alterados():
    nonce, texto = cifrado.cifrar_credenciales(LLAVE, "usuario-secreto", "clave-secreta", "caso-secreto")
    assert len(nonce) == 12 and b"usuario-secreto" not in texto and b"clave-secreta" not in texto and b"caso-secreto" not in texto
    assert cifrado.descifrar_credenciales(LLAVE, nonce, texto) == ("usuario-secreto", "clave-secreta", "caso-secreto")
    assert cifrado.descifrar_credenciales(LLAVE, *cifrado.cifrar_credenciales(LLAVE, "u", "c")) == ("u", "c", None)
    n2, t2 = cifrado.cifrar_credenciales(LLAVE, "usuario-secreto", "clave-secreta")
    assert (n2, t2) != (nonce, texto)  # nonce aleatorio: nunca el mismo texto cifrado
    for malo in (lambda: cifrado.descifrar_credenciales(bytes(32), nonce, texto),                       # otra llave
                 lambda: cifrado.descifrar_credenciales(LLAVE, nonce, texto[:-1] + bytes([texto[-1] ^ 1])),  # alterado
                 lambda: cifrado.descifrar_credenciales(LLAVE, bytes(12), texto),                        # otro nonce
                 lambda: cifrado.descifrar_credenciales(LLAVE, nonce, b"x" * 40),
                 lambda: cifrado.descifrar_credenciales(LLAVE[:31], nonce, texto)):
        with pytest.raises(cifrado.CifradoNoValido):
            malo()
    for datos in (("", "c"), ("u", ""), (None, "c"), ("u", "c", 5)):
        with pytest.raises(cifrado.CifradoNoValido):
            cifrado.cifrar_credenciales(LLAVE, *datos)
    with pytest.raises(cifrado.CifradoNoValido):
        cifrado.cifrar_credenciales(b"corta", "u", "c")


def test_la_llave_de_cifrado_se_acepta_en_base64_y_rechaza_valores_debiles_o_de_otra_longitud():
    import base64
    esperado = clave_desde_texto(base64.urlsafe_b64encode(LLAVE).decode())
    assert esperado == LLAVE and clave_desde_texto(base64.urlsafe_b64encode(LLAVE).decode().rstrip("=")) == LLAVE
    assert clave_desde_texto(base64.b64encode(LLAVE).decode()) == LLAVE
    for malo in ("", "corta", base64.urlsafe_b64encode(bytes(32)).decode(), base64.urlsafe_b64encode(LLAVE[:16]).decode(), "!!!", None):
        with pytest.raises(ConfiguracionInsegura):
            clave_desde_texto(malo)


# --- Configuración del monitor -------------------------------------------------------------------------------------------

def entorno_monitor(tmp_path):
    import base64
    (tmp_path / "ca.crt").write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n", encoding="utf-8")
    e = entorno_valido(tmp_path)
    e.update({"TINOTIFY_RR_PG_HOST": "aws-0-us-east-1.pooler.supabase.com", "TINOTIFY_RR_PG_USER": "tinotify_real_login.abcdefghijklmnop",
              "TINOTIFY_RR_PG_PASSWORD": "contrasena-de-prueba-0123456789", "TINOTIFY_RR_PG_CA_FILE": str(tmp_path / "ca.crt"),
              "TINOTIFY_RR_CLAVE_CIFRADO": base64.urlsafe_b64encode(LLAVE).decode(), "TINOTIFY_RR_MONITOR_TOKEN": TOKEN_MONITOR})
    return e


def test_la_configuracion_del_monitor_es_opcional_completa_y_no_expone_secretos(tmp_path):
    assert Config.desde_entorno(entorno_valido(tmp_path)).monitor is None
    c = Config.desde_entorno(entorno_monitor(tmp_path))
    assert c.monitor.pg.puerto == 5432 and c.monitor.pg.base == "postgres" and c.monitor.pg.tls and c.monitor.clave_cifrado == LLAVE
    texto = repr(c) + repr(c.monitor) + repr(c.monitor.pg)
    for secreto in ("contrasena-de-prueba", TOKEN_MONITOR, "supabase.com", "tinotify_real_login", str(tmp_path)):
        assert secreto not in texto


@pytest.mark.parametrize("cambio", [
    {"TINOTIFY_RR_PG_PASSWORD": None}, {"TINOTIFY_RR_CLAVE_CIFRADO": None}, {"TINOTIFY_RR_MONITOR_TOKEN": None},
    {"TINOTIFY_RR_PG_HOST": None}, {"TINOTIFY_RR_PG_CA_FILE": None}, {"TINOTIFY_RR_PG_USER": None},       # incompleto
    {"TINOTIFY_RR_PG_USER": "postgres"}, {"TINOTIFY_RR_PG_USER": "tinotify_sintetico_login.abcdefghij"},
    {"TINOTIFY_RR_PG_USER": "service_role"}, {"TINOTIFY_RR_PG_PORT": "6543"}, {"TINOTIFY_RR_PG_PORT": "x"},
    {"TINOTIFY_RR_PG_PASSWORD": "corta"}, {"TINOTIFY_RR_PG_PASSWORD": " con-espacio-0123456789 "},
    {"TINOTIFY_RR_PG_HOST": "-malo"}, {"TINOTIFY_RR_PG_HOST": "host con espacios"}, {"TINOTIFY_RR_PG_DBNAME": "a;b"},
    {"TINOTIFY_RR_MONITOR_TOKEN": TOKEN}, {"TINOTIFY_RR_MONITOR_TOKEN": "corto"}, {"TINOTIFY_RR_CLAVE_CIFRADO": "corta"},
    {"TINOTIFY_RR_PG_CA_FILE": "/no/existe"}, {"PGSSLMODE": "disable"}, {"PGPASSWORD": "x"}, {"DATABASE_URL": "x"},
    {"SUPABASE_URL": "x"}, {"TINOTIFY_SR_PG_HOST": "x"}, {"TINOTIFY_RR_PG_SSLMODE": "disable"},
])
def test_la_configuracion_insegura_o_incompleta_del_monitor_no_arranca(tmp_path, cambio):
    e = entorno_monitor(tmp_path)
    for k, v in cambio.items():
        if v is None:
            e.pop(k)
        else:
            e[k] = v
    with pytest.raises(ConfiguracionInsegura) as error:
        Config.desde_entorno(e)
    assert "contrasena-de-prueba" not in str(error.value) and TOKEN_MONITOR not in str(error.value)


def test_un_certificado_ca_invalido_se_rechaza(tmp_path):
    e = entorno_monitor(tmp_path)
    (tmp_path / "ca.crt").write_text("no es un certificado", encoding="utf-8")
    with pytest.raises(ConfiguracionInsegura):
        Config.desde_entorno(e)


# --- Lógica de comparación (pura) ----------------------------------------------------------------------------------------

def prev(*pares, acreditado=False, generacion=1, anomalia=False):
    return EstadoPrevio(Counter(dict(pares)), acreditado, generacion, anomalia)


def test_sin_estado_previo_todo_es_linea_base_silenciosa():
    plan = planificar({}, {REF(1): Counter({H(1): 2}), REF(2): Counter({H(2): 1})})
    assert plan.primera_ejecucion and plan.resultado == "linea_base" and not plan.requiere_aviso
    assert plan.expedientes == 2 and plan.novedades == 0 and plan.expedientes_nuevos == 0
    assert all(c.accion == "nuevo" and not c.en_bd for c in plan.cambios)


def test_la_semilla_del_expediente_acreditado_hace_que_lo_posterior_a_la_referencia_sea_novedad():
    semilla = {REF(1): Counter({H(1): 1, H(2): 2})}
    plan = planificar({}, {REF(1): Counter({H(1): 1, H(2): 2, H(3): 1}), REF(9): Counter({H(9): 5})}, semilla)
    assert plan.novedades == 1 and plan.expedientes_con_novedades == 1 and plan.expedientes_nuevos == 0 and plan.requiere_aviso
    acreditado = next(c for c in plan.cambios if c.caso_ref == REF(1))
    assert acreditado.accion == "novedades" and acreditado.acreditado and acreditado.en_bd is False and acreditado.generacion == 2
    assert next(c for c in plan.cambios if c.caso_ref == REF(9)).accion == "nuevo"   # el resto: línea base silenciosa
    sin_cambios = planificar({}, {REF(1): Counter({H(1): 1, H(2): 2})}, semilla)
    assert sin_cambios.cambios[0].accion == "sin_cambios" and not sin_cambios.requiere_aviso and sin_cambios.resultado == "linea_base"


def test_las_novedades_respetan_multiplicidades_y_no_dependen_del_orden():
    previos = {REF(1): prev((H(1), 2), (H(2), 1))}
    assert planificar(previos, {REF(1): Counter({H(1): 2, H(2): 1})}).requiere_aviso is False
    plan = planificar(previos, {REF(1): Counter({H(1): 3, H(2): 1})})          # una copia más de un duplicado = una novedad
    assert plan.novedades == 1 and plan.cambios[0].huellas == Counter({H(1): 3, H(2): 1}) and plan.cambios[0].generacion == 2
    assert planificar(previos, {REF(1): Counter({H(2): 1, H(1): 2, H(7): 2})}).novedades == 2
    assert planificar(previos, {REF(1): Counter({H(1): 2, H(2): 1})}).resultado == "ok"


def test_un_expediente_nuevo_posterior_a_la_primera_ejecucion_avisa_solo_de_que_aparecio():
    previos = {REF(1): prev((H(1), 1))}
    plan = planificar(previos, {REF(1): Counter({H(1): 1}), REF(5): Counter({H(5): 40})})
    assert plan.expedientes_nuevos == 1 and plan.novedades == 0 and plan.requiere_aviso and plan.resultado == "ok"
    nuevo = next(c for c in plan.cambios if c.caso_ref == REF(5))
    assert nuevo.accion == "nuevo" and nuevo.novedades == 0   # sus 40 actuaciones antiguas NO son novedades


def test_una_huella_previa_ausente_es_anomalia_no_novedad_y_solo_avisa_al_producirse():
    previos = {REF(1): prev((H(1), 2), (H(2), 1), acreditado=True)}
    plan = planificar(previos, {REF(1): Counter({H(1): 1, H(2): 1, H(9): 3})})   # falta una copia y hay actuaciones nuevas
    assert plan.anomalias == 1 and plan.novedades == 0 and plan.resultado == "anomalia" and plan.requiere_aviso
    c = plan.cambios[0]
    assert c.accion == "anomalia" and c.huellas == Counter({H(1): 2, H(2): 1}) and c.anomalia and c.acreditado   # no se sobrescribe
    persistente = planificar({REF(1): prev((H(1), 2), (H(2), 1), anomalia=True)}, {REF(1): Counter({H(1): 1, H(2): 1})})
    assert persistente.anomalias == 0 and not persistente.requiere_aviso and persistente.cambios[0].anomalia
    recuperado = planificar({REF(1): prev((H(1), 2), anomalia=True)}, {REF(1): Counter({H(1): 2})})
    assert recuperado.cambios[0].accion == "sin_cambios" and recuperado.cambios[0].anomalia is False and not recuperado.requiere_aviso


def test_un_expediente_que_deja_de_listarse_no_cambia_y_un_historial_vacio_es_un_estado_valido():
    previos = {REF(1): prev((H(1), 1)), REF(2): prev((H(2), 1))}
    plan = planificar(previos, {REF(1): Counter({H(1): 1})})
    assert plan.expedientes == 1 and [c.caso_ref for c in plan.cambios] == [REF(1)]
    vacio = planificar({REF(3): prev()}, {REF(3): Counter({H(3): 1})})
    assert vacio.novedades == 1                                 # la primera actuación de un expediente que estaba vacío SÍ es novedad
    assert planificar({}, {REF(3): Counter()}).cambios[0].huellas == Counter()


def test_el_identificador_de_expediente_es_opaco_estable_y_depende_de_la_clave():
    assert REF(101) == REF(101) and REF(101) != REF(102) and len(REF(101)) == 64 and "101" not in REF(101)
    assert caso_ref(b"otra-clave-de-prueba-0123456789", INSTANCIA_REAL, 101) != REF(101)
    assert caso_ref(CLAVE_TEST, "otra-instancia", 101) != REF(101)


# --- Rutas del monitor ---------------------------------------------------------------------------------------------------

BASE_101 = [f"CONTENIDO_SINTETICO_{n}" for n in range(4)]


def huellas_del_simulado(textos):
    sim = SigacSimulado({101: textos})
    with sim.cliente() as cliente:
        cliente.autenticar("u", "c", tipo="2", total_casos_esperado=None, listado_estructural=True)
        return [a.huella_version for a in cliente.consultar_historial(101)]


class Mundo:
    def __init__(self, casos, *, sim_extra=None, almacen=None, llave=LLAVE, max_logins=30, con_monitor=True, fabrica=None):
        self.sim = SigacSimulado(casos, **(sim_extra or {}))
        self.almacen = almacen or AlmacenMemoria()
        referencia, _ = referencia_de(huellas_del_simulado(BASE_101))
        monitor = ConfigMonitor(ConfigPg("h", 5432, "postgres", "tinotify_real_login", "x" * 20, None, tls=False), llave, TOKEN_MONITOR) if con_monitor else None
        self.historial = HistorialTemporal()
        self.app = crear_app(config(max_logins=max_logins, monitor=monitor), politica=politica_de_prueba(), referencia=referencia,
                             historial=self.historial, fabrica_cliente=(fabrica(self.sim) if fabrica else self.sim.cliente), clave_acreditacion=CLAVE_TEST,
                             almacen=self.almacen)
        self.c = cliente_http(self.app)

    def guardar_credenciales(self):
        return login(self.c, self.sim.usuario, self.sim.clave, recordar=True)

    def ejecutar(self, token=TOKEN_MONITOR):
        return self.c.post("/real/monitor/ejecutar", headers={"Authorization": f"Bearer {token}"})

    def avisos(self, token=TOKEN_MONITOR):
        return self.c.get("/real/monitor/avisos", headers={"Authorization": f"Bearer {token}"})

    def entregar(self, aviso, token=TOKEN_MONITOR):
        return self.c.post(f"/real/monitor/avisos/{aviso}/entregado", headers={"Authorization": f"Bearer {token}"})


def casos_base():
    return {101: list(BASE_101), 202: ["EXPEDIENTE_A_1", "EXPEDIENTE_A_2"], 303: ["EXPEDIENTE_B_1"]}


def test_recordar_guarda_las_credenciales_cifradas_y_sin_el_monitor_no_hay_rutas_ni_se_puede_recordar():
    m = Mundo(casos_base())
    r = m.guardar_credenciales()
    assert r.status_code == 200 and r.json()["credenciales_guardadas"] is True
    version, nonce, texto = m.almacen.cred
    assert version == 1 and len(nonce) == 12 and m.sim.usuario.encode() not in texto and m.sim.clave.encode() not in texto
    assert cifrado.descifrar_credenciales(LLAVE, nonce, texto)[:2] == (m.sim.usuario, m.sim.clave)
    assert m.c.get("/real/monitor/estado", headers=CAB).json()["credenciales_guardadas"] is True
    assert login(m.c, m.sim.usuario, m.sim.clave).json().get("credenciales_guardadas") is None   # sin «recordar» no se toca
    sin = Mundo(casos_base(), con_monitor=False)
    assert sin.ejecutar().status_code == 404 and sin.c.get("/real/monitor/estado", headers=CAB).status_code == 404
    r2 = login(sin.c, sin.sim.usuario, sin.sim.clave, recordar=True)
    assert r2.status_code == 422 and sin.sim.logins == 0                                          # no se conecta si no se puede guardar


def test_si_la_base_falla_al_guardar_el_acceso_funciona_y_se_informa():
    m = Mundo(casos_base())
    m.almacen.caido = True
    r = m.guardar_credenciales()
    assert r.status_code == 200 and r.json()["credenciales_guardadas"] is False and m.almacen.cred is None
    assert m.historial.estado()["activa"] is True      # el acceso ya funcionó: la sesión de historial sigue activa


def test_los_tokens_estan_separados_el_de_la_app_no_dispara_el_monitor_ni_al_reves():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    assert m.ejecutar(token=TOKEN).status_code == 401
    assert m.c.post("/real/monitor/ejecutar").status_code == 401
    assert m.c.get("/real/monitor/avisos", headers=CAB).status_code == 401
    assert m.c.get("/real/monitor/estado", headers={"Authorization": f"Bearer {TOKEN_MONITOR}"}).status_code == 401
    assert m.c.delete("/real/credenciales", headers={"Authorization": f"Bearer {TOKEN_MONITOR}"}).status_code == 401
    assert m.sim.logins == 1   # solo el login manual de guardar_credenciales


def test_primera_ejecucion_linea_base_luego_novedades_expediente_nuevo_y_confirmacion_sin_duplicados():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    logins_antes = m.sim.logins
    r = m.ejecutar()
    assert r.status_code == 200
    d = r.json()
    assert d["resultado"] == "linea_base" and d["linea_base"] is True and d["expedientes"] == 3 and d["novedades"] == 0
    assert d["aviso_nuevo"] is None and d["avisos"] == [] and d["casos_fallidos"] == 0
    assert m.sim.logins == logins_antes + 1                                       # una sola autenticación por revisión
    assert m.sim.llamadas.count("casos.formCaso.con") >= 3
    assert len(m.almacen.estado_exp) == 3 and sum(e["acreditado"] for e in m.almacen.estado_exp.values()) == 1

    assert m.ejecutar().json()["resultado"] == "ok" and m.ejecutar().json()["avisos"] == []   # sin cambios: nada que avisar

    m.sim.casos[101].append("POSTERIOR_101")
    m.sim.casos[202] += ["POSTERIOR_202_A", "POSTERIOR_202_B"]
    m.sim.casos[404] = ["NUEVO_EXPEDIENTE_ANTIGUO_1", "NUEVO_EXPEDIENTE_ANTIGUO_2"]
    d = m.ejecutar().json()
    assert d["novedades"] == 3 and d["expedientes_con_novedades"] == 2 and d["expedientes_nuevos"] == 1 and d["anomalias"] == 0
    assert d["aviso_nuevo"] and [a["id"] for a in d["avisos"]] == [d["aviso_nuevo"]]
    aviso = d["avisos"][0]
    assert (aviso["novedades"], aviso["expedientes_con_novedades"], aviso["expedientes_nuevos"]) == (3, 2, 1)
    # Los UUID de los avisos son aleatorios y pueden contener por azar "101", "202" o "404": se excluyen del texto inspeccionado.
    sin_ids = {**d, "aviso_nuevo": None, "avisos": [{k: v for k, v in a.items() if k != "id"} for a in d["avisos"]]}
    texto = json.dumps(sin_ids)
    assert not any(s in texto for s in ("POSTERIOR", "NUEVO_EXPEDIENTE", "EXPEDIENTE_A", "101", "202", "404", m.sim.usuario, m.sim.clave))
    # Sin confirmar, el aviso sigue pendiente (se repite en la siguiente revisión, nunca se pierde) y no se duplica la novedad.
    d2 = m.ejecutar().json()
    assert d2["novedades"] == 0 and d2["aviso_nuevo"] is None and [a["id"] for a in d2["avisos"]] == [aviso["id"]]
    assert m.avisos().json()["avisos"][0]["id"] == aviso["id"]
    assert m.entregar(aviso["id"]).json() == {"entregado": True}
    assert m.entregar(aviso["id"]).status_code == 404 and m.avisos().json()["avisos"] == []
    assert m.entregar("00000000-0000-4000-8000-000000000000").status_code == 404
    assert m.ejecutar().json()["avisos"] == []                                     # ya entregado: no vuelve
    assert m.ejecutar().json()["novedades"] == 0 and len(m.almacen.estado_exp) == 4


def test_la_primera_ejecucion_avisa_de_lo_posterior_a_la_referencia_del_expediente_acreditado():
    casos = casos_base()
    casos[101].append("POSTERIOR_A_LA_REFERENCIA")
    m = Mundo(casos)
    m.guardar_credenciales()
    d = m.ejecutar().json()
    assert d["linea_base"] is True and d["resultado"] == "ok" and d["novedades"] == 1 and d["expedientes_nuevos"] == 0
    assert d["aviso_nuevo"] and "POSTERIOR" not in json.dumps(d)


def test_una_lectura_inconsistente_es_anomalia_se_avisa_una_vez_y_no_pisa_el_estado():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    m.ejecutar()
    antes = {r: Counter(e["huellas"]) for r, e in m.almacen.estado_exp.items()}
    m.sim.casos[202] = m.sim.casos[202][:1] + ["TEXTO_DISTINTO"]          # falta una huella previa
    d = m.ejecutar().json()
    assert d["anomalias"] == 1 and d["novedades"] == 0 and d["resultado"] == "anomalia" and d["aviso_nuevo"]
    assert {r: Counter(e["huellas"]) for r, e in m.almacen.estado_exp.items()} == antes
    assert any(e["anomalia"] for e in m.almacen.estado_exp.values())
    m.entregar(d["aviso_nuevo"])
    assert m.ejecutar().json()["aviso_nuevo"] is None                        # persistente: sin spam
    m.sim.casos[202] = ["EXPEDIENTE_A_1", "EXPEDIENTE_A_2"]
    assert m.ejecutar().json()["avisos"] == [] and not any(e["anomalia"] for e in m.almacen.estado_exp.values())


def test_un_expediente_que_falla_se_omite_sin_perder_su_estado_y_los_demas_se_procesan():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    m.ejecutar()
    previo = Counter(m.almacen.estado_exp[REF(202)]["huellas"])
    m.sim.caidos.add(202)
    m.sim.casos[101].append("POSTERIOR_101")
    d = m.ejecutar().json()
    assert d["casos_fallidos"] == 1 and d["expedientes"] == 2 and d["novedades"] == 1
    assert Counter(m.almacen.estado_exp[REF(202)]["huellas"]) == previo
    assert m.almacen.ejecuciones[-1]["codigo"] == "casos_fallidos"


def test_un_historial_vacio_se_registra_y_su_primera_actuacion_es_novedad():
    casos = casos_base()
    casos[505] = []
    m = Mundo(casos)
    m.guardar_credenciales()
    assert m.ejecutar().json()["expedientes"] == 4 and m.almacen.estado_exp[REF(505)]["huellas"] == Counter()
    m.sim.casos[505] = ["PRIMERA_ACTUACION_DEL_EXPEDIENTE"]
    assert m.ejecutar().json()["novedades"] == 1


def test_errores_sin_credenciales_con_llave_ajena_acceso_rechazado_base_caida_y_concurrencia():
    m = Mundo(casos_base())
    assert m.ejecutar().status_code == 412 and m.sim.logins == 0                      # nada que usar: no se conecta
    m.guardar_credenciales()
    otra = Mundo(casos_base(), almacen=m.almacen, llave=bytes(range(100, 132)))
    r = otra.ejecutar()
    assert r.status_code == 503 and r.json() == {"detail": "Servicio no configurado"} and otra.sim.logins == 0
    rechazado = Mundo(casos_base(), sim_extra={"rechazar_login": True}, almacen=m.almacen)
    r = rechazado.ejecutar()
    assert r.status_code == 403 and r.json() == {"detail": "Acceso no confirmado"}
    assert m.almacen.ejecuciones[-1]["resultado"] == "error_acceso"
    m.almacen.caido = True
    assert m.ejecutar().status_code == 503 and m.c.get("/real/monitor/estado", headers=CAB).status_code == 503
    assert m.avisos().status_code == 503 and m.entregar("00000000-0000-4000-8000-000000000000").status_code == 503
    m.almacen.caido = False
    assert m.almacen.cred is not None and m.ejecutar().status_code == 200              # las credenciales no se perdieron


def test_dos_revisiones_simultaneas_no_se_pisan_y_el_presupuesto_de_intentos_tambien_protege_al_monitor():
    entro, seguir, modo = threading.Event(), threading.Event(), {"lento": False}

    def fabrica(sim):
        def crear():
            if modo["lento"]:
                entro.set()
                assert seguir.wait(10)
            return sim.cliente()
        return crear
    m = Mundo(casos_base(), fabrica=fabrica)
    m.guardar_credenciales()
    modo["lento"] = True
    resultado = {}
    hilo = threading.Thread(target=lambda: resultado.update(r=m.ejecutar()))
    hilo.start()
    assert entro.wait(10)
    assert cliente_http(m.app).post("/real/monitor/ejecutar", headers={"Authorization": f"Bearer {TOKEN_MONITOR}"}).status_code == 409
    seguir.set()
    hilo.join(10)
    assert resultado["r"].status_code == 200
    limitado = Mundo(casos_base(), max_logins=2)
    limitado.guardar_credenciales()                                                    # intento 1
    assert limitado.ejecutar().status_code == 200                                      # intento 2
    r = limitado.ejecutar()
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1                 # intento 3: presupuesto agotado


def test_olvidar_las_credenciales_detiene_el_monitor_y_el_estado_solo_muestra_conteos():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    m.ejecutar()
    e = m.c.get("/real/monitor/estado", headers=CAB).json()
    assert e["credenciales_guardadas"] and e["expedientes_en_estado"] == 3 and e["avisos_pendientes"] == 0
    assert e["ultima_ejecucion"]["resultado"] == "linea_base"
    assert m.c.delete("/real/credenciales", headers=CAB).json() == {"credenciales_guardadas": False}
    assert m.almacen.cred is None and m.ejecutar().status_code == 412


def test_ni_las_respuestas_ni_los_logs_ni_el_estado_contienen_credenciales_numeros_o_texto(caplog):
    caplog.set_level(logging.DEBUG)
    m = Mundo(casos_base())
    respuestas = [m.guardar_credenciales(), m.ejecutar()]
    m.sim.casos[202].append("POSTERIOR_SECRETO_JUDICIAL")
    respuestas += [m.ejecutar(), m.avisos(), m.c.get("/real/monitor/estado", headers=CAB)]
    todo = " ".join(r.text for r in respuestas) + " ".join(x.getMessage() for x in caplog.records)
    estado = repr(m.almacen.estado_exp) + repr(m.almacen.avisos) + repr(m.almacen.ejecuciones)
    for secreto in (m.sim.usuario, m.sim.clave, "POSTERIOR_SECRETO", "EXPEDIENTE_A_1", TOKEN_MONITOR):
        assert secreto not in todo and secreto not in estado
    for numero in ("'101'", "'202'", "'303'", " 101,", " 202,"):
        assert numero not in estado


def test_el_script_de_activacion_solo_pide_credenciales_a_un_destino_real_y_con_confirmacion(monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "activar_monitor_remoto.py"
    spec = importlib.util.spec_from_file_location("activar_monitor_t", ruta)
    s = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s)
    for malo in ([], ["--url", "http://x.example"], ["--url", "https://u:p@x.example"], ["--url", "https://x.example/?a=1"]):
        with pytest.raises(SystemExit):
            s.main(malo)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit):
        s.main(["--url", "https://x.example"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(s.getpass, "getpass", lambda *_: pytest.fail("No debe pedir credenciales"))
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert s.main(["--url", "https://x.example"]) == 2                  # sin confirmación: nada de red ni credenciales
    monkeypatch.setattr("builtins.input", lambda _: s.CONFIRMACION)
    monkeypatch.setattr(s, "es_backend_real", lambda *a, **k: False)
    assert s.main(["--url", "https://x.example"]) == 5                  # destino que no es el backend real: aborta sin pedir nada


def test_los_expedientes_que_fallan_se_registran_solo_con_codigos_de_catalogo(caplog):
    m = Mundo(casos_base())
    m.guardar_credenciales()
    m.ejecutar()
    m.sim.caidos.update({202, 303})
    caplog.set_level(logging.WARNING)
    d = m.ejecutar().json()
    assert d["casos_fallidos"] == 2
    lineas = [x.getMessage() for x in caplog.records if x.getMessage().startswith("monitor_casos_fallidos")]
    assert len(lineas) == 1 and "listados=3 leidos=1" in lineas[0]
    detalle = json.loads(lineas[0].split("detalle=", 1)[1])
    assert sum(x["n"] for x in detalle) == 2 and all(set(x) == {"codigo", "etapa", "n"} for x in detalle)
    assert not any(s in " ".join(x.getMessage() for x in caplog.records) for s in ("202", "303", "EXPEDIENTE_", m.sim.usuario, m.sim.clave))


def _con_anexo_sin_enlace(sim, anexos, peticion):
    import httpx
    r = sim(peticion)
    if peticion.url.path.endswith("casos.formCaso.con") and b"hidCaso=202" in peticion.content:
        return httpx.Response(200, headers={"content-type": r.headers["content-type"]}, text=r.text.replace("</table></form>", anexos + "</table></form>", 1))
    return r


def test_un_anexo_sin_enlace_rechazado_se_diagnostica_solo_con_conteos_estructurales(caplog):
    import httpx
    from tinotify.integrations.sigac.sigac_client import BASE_URL, SigacClient
    anexos = ('<tr><td>Anexos :</td><td><table id="tablaAnexos"><tr><td>ANEXO_PRIVADO_SIN_ENLACE</td><td><span></span></td></tr></table></td></tr>')

    def fabrica(sim):
        return lambda: SigacClient(httpx.Client(base_url=BASE_URL, follow_redirects=False,
                                               transport=httpx.MockTransport(lambda p: _con_anexo_sin_enlace(sim, anexos, p))))
    m = Mundo(casos_base(), fabrica=fabrica)
    m.guardar_credenciales()
    caplog.set_level(logging.WARNING)
    d = m.ejecutar().json()
    mensajes = [x.getMessage() for x in caplog.records]
    assert d["casos_fallidos"] == 1, mensajes
    linea = [x for x in mensajes if x.startswith("monitor_diagnostico_anexos")]
    assert len(linea) == 1, mensajes
    conteos = json.loads(linea[0].split("conteos=", 1)[1])
    assert len(conteos) == 1 and all(type(v) is int for v in conteos[0].values()) and "anexo_ausente_celdas_th" in conteos[0]
    todo = " ".join(mensajes)
    assert not any(s in todo for s in ("ANEXO_PRIVADO", "202", m.sim.usuario, m.sim.clave))


def test_el_historial_de_ejecuciones_exige_el_token_de_la_app_y_solo_trae_estados_y_conteos():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    assert m.ejecutar().status_code == 200 and m.ejecutar().status_code == 200
    cab = CAB
    assert m.c.get("/real/monitor/ejecuciones").status_code == 401
    assert m.c.get("/real/monitor/ejecuciones", headers={"Authorization": f"Bearer {TOKEN_MONITOR}"}).status_code == 401  # tokens separados
    r = m.c.get("/real/monitor/ejecuciones?limite=1", headers=cab)
    assert r.status_code == 200 and len(r.json()["ejecuciones"]) == 1
    fila = m.c.get("/real/monitor/ejecuciones", headers=cab).json()["ejecuciones"][0]
    assert set(fila) == {"inicio", "fin", "resultado", "expedientes", "novedades", "codigo"}
    assert fila["resultado"] in ("ok", "linea_base")
    assert m.c.get("/real/monitor/ejecuciones?limite=0", headers=cab).status_code == 422
    assert m.c.get("/real/monitor/ejecuciones?limite=101", headers=cab).status_code == 422
    m.almacen.caido = True
    assert m.c.get("/real/monitor/ejecuciones", headers=cab).status_code == 503
