"""Backend remoto real: referencia portable, configuración, rutas, sesiones, credenciales y aislamiento.

Todo con HTTP simulado y contenido ficticio. Estas pruebas NO demuestran que Render pueda conectarse a SIGAC.
"""

import hashlib
import json
import logging
import threading

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.tests.test_contrato_expediente import CLAVE_TEST, contrato, politica_de_prueba, servicio_real
from backend.tests.test_integridad_historial_sigac import (
    CLAVE, FORMULARIO, LISTADO, USUARIO, bloque, cliente_sintetico, pagina,
)
from tinotify.integrations.sigac.sigac_client import BASE_URL, SigacClient
from tinotify.parsers.casos_parser import extraer_casos
from tinotify.real_remoto.app import crear_app
from tinotify.real_remoto.config import Config, ConfiguracionInsegura
from tinotify.services import referencia_portable as rp
from tinotify.services.consulta_real_local import caso_local, consultar_caso_acreditado
from tinotify.services.exportar_referencia import exportar
from tinotify.services.historial_temporal import HistorialTemporal

TOKEN = "t0ken-remoto-de-prueba-" + "abcdefghij" * 3
CONTENIDO = pagina(*(bloque(f"CONTENIDO_SINTETICO_{n}") for n in range(4)))
SECRETO_USUARIO, SECRETO_CLAVE = USUARIO, CLAVE
CAB = {"Authorization": f"Bearer {TOKEN}"}


class Reloj:
    t = 1000.0

    def __call__(self):
        return self.t


def huellas_de(contenido):
    with cliente_sintetico([contenido]) as (cliente, _):
        cliente.autenticar(USUARIO, CLAVE, tipo="2", total_casos_esperado=1)
        return [a.huella_version for a in cliente.consultar_historial(101)]


def referencia_de(huellas, numero=101):
    doc = rp.construir(CLAVE_TEST, instancia="sigac-real", numero=numero, version_hashes=huellas, generacion=1,
                       eventos_internos=0, contrato=contrato())
    return rp.verificar(CLAVE_TEST, doc, instancia="sigac-real", contrato=contrato()), doc


def config(**cambios):
    datos = dict(modo="pruebas-locales", token=TOKEN, ttl_s=300, max_logins=3, ventana_login_s=900)
    datos.update(cambios)
    return Config(**datos)


@pytest.fixture
def entorno():
    huellas = huellas_de(CONTENIDO)
    referencia, _ = referencia_de(huellas)
    return huellas, referencia


def cliente_http(app):
    return TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))


def login(c, usuario=SECRETO_USUARIO, clave=SECRETO_CLAVE, **extra):
    cuerpo = json.dumps({"usuario": usuario, "clave": clave, **extra})
    return c.post("/real/sesion", content=cuerpo, headers={**CAB, "Content-Type": "application/json"})


# --- Referencia portable ---------------------------------------------------------------------------------------------

def test_la_referencia_contiene_solo_huellas_con_clave_y_metadatos_minimos(entorno):
    huellas, ref = entorno[0], entorno[1]
    _, doc = referencia_de(huellas)
    assert set(doc) == {"version", "instancia", "contrato", "numero", "caso_id", "generacion", "eventos_internos", "huellas", "mac"}
    texto = json.dumps(doc)
    assert not any(h in texto for h in huellas)  # ninguna version_hash original
    assert "CONTENIDO_SINTETICO" not in texto and "local_id" not in texto and "remitente" not in texto
    assert doc["huellas"] == sorted(doc["huellas"]) and len(doc["huellas"]) == len(huellas)
    assert doc["caso_id"] != caso_local(101) and str(caso_local(101)) not in texto  # identificador opaco
    assert ref.entradas() == [(None, h) for h in doc["huellas"]]


def test_cualquier_alteracion_o_clave_ajena_invalida_la_referencia(entorno):
    huellas = entorno[0]
    _, doc = referencia_de(huellas)
    alteraciones = [
        lambda d: d.update(numero=102), lambda d: d.update(generacion=2), lambda d: d.update(eventos_internos=5),
        lambda d: d["huellas"].pop(), lambda d: d["huellas"].append(d["huellas"][0]), lambda d: d.update(caso_id=d["caso_id"][:-1] + "0"),
        lambda d: d.update(instancia="otra"), lambda d: d["contrato"].update(version=9), lambda d: d.update(mac="0" * 64),
        lambda d: d.update(extra=1), lambda d: d.pop("mac"), lambda d: d.update(version=2),
    ]
    for alterar in alteraciones:
        copia = json.loads(json.dumps(doc))
        alterar(copia)
        with pytest.raises(rp.ReferenciaPortableInvalida):
            rp.verificar(CLAVE_TEST, copia, instancia="sigac-real", contrato=contrato())
    with pytest.raises(rp.ReferenciaPortableInvalida):
        rp.verificar(b"otra-clave-de-prueba-0123456789", doc, instancia="sigac-real", contrato=contrato())
    with pytest.raises(rp.ReferenciaPortableInvalida):  # el contrato de producción es otro: la referencia debe regenerarse
        rp.verificar(CLAVE_TEST, doc, instancia="sigac-real")


def test_cargar_rechaza_archivos_ausentes_ilegibles_o_demasiado_grandes(tmp_path, entorno):
    _, doc = referencia_de(entorno[0])
    bueno = tmp_path / "ref.json"
    bueno.write_text(json.dumps(doc), encoding="utf-8")
    assert rp.cargar(bueno, CLAVE_TEST, instancia="sigac-real", contrato=contrato()).numero == 101
    for nombre, contenido in (("malo.json", "{no es json"), ("grande.json", " " * (rp.MAX_BYTES + 1))):
        (tmp_path / nombre).write_text(contenido, encoding="utf-8")
        with pytest.raises(rp.ReferenciaPortableInvalida):
            rp.cargar(tmp_path / nombre, CLAVE_TEST, instancia="sigac-real", contrato=contrato())
    with pytest.raises(rp.ReferenciaPortableInvalida):
        rp.cargar(tmp_path / "no-existe.json", CLAVE_TEST, instancia="sigac-real", contrato=contrato())


def test_el_exportador_lee_v2_en_solo_lectura_y_solo_escribe_el_archivo_nuevo(tmp_path, capsys):
    servicio = servicio_real(tmp_path, politica_de_prueba())
    with cliente_sintetico([CONTENIDO]) as (cliente, _):
        consultar_caso_acreditado(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=101, servicio=servicio)
    v2 = tmp_path / "real.sqlite3"
    antes = hashlib.sha256(v2.read_bytes()).hexdigest()
    clave = tmp_path / "clave.json"
    clave.write_text(json.dumps({"version": 1, "clave_hex": CLAVE_TEST.hex()}), encoding="utf-8")
    salida = tmp_path / "salida" / "referencia.json"
    resumen = exportar(v2, clave, salida, politica=politica_de_prueba(), contrato=contrato())
    assert resumen["huellas"] == 4 and resumen["generacion"] == 1 and resumen["eventos_internos"] == 0
    assert hashlib.sha256(v2.read_bytes()).hexdigest() == antes
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(["real.sqlite3", "clave.json", "salida"])  # sin -wal ni -journal
    doc = json.loads(salida.read_text(encoding="utf-8"))
    rp.verificar(CLAVE_TEST, doc, instancia="sigac-real", contrato=contrato())
    assert "CONTENIDO_SINTETICO" not in salida.read_text(encoding="utf-8") and "local_id" not in salida.read_text(encoding="utf-8")
    with pytest.raises(rp.ReferenciaPortableInvalida):  # no sobrescribe
        exportar(v2, clave, salida, politica=politica_de_prueba(), contrato=contrato())
    from tinotify.services.consulta_real_local import IdentidadExpedienteNoVerificada
    with pytest.raises(IdentidadExpedienteNoVerificada):  # con la política de producción, este expediente no está acreditado
        exportar(v2, clave, tmp_path / "otra.json")
    assert not (tmp_path / "otra.json").exists()


# --- Configuración ------------------------------------------------------------------------------------------------------

def entorno_valido(tmp_path):
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "r.json").write_text("{}", encoding="utf-8")
    return {"TINOTIFY_RR_MODO": "remoto", "TINOTIFY_RR_TOKEN": TOKEN, "TINOTIFY_RR_TLS": "proxy",
            "TINOTIFY_RR_PROXIES_CONFIABLES": "privadas", "TINOTIFY_RR_ACREDITACION_FILE": str(tmp_path / "a.json"),
            "TINOTIFY_RR_REFERENCIA_FILE": str(tmp_path / "r.json"), "PYTHON_VERSION": "3.11.18", "PORT": "10000"}


def test_la_configuracion_valida_arranca_y_no_expone_secretos(tmp_path):
    c = Config.desde_entorno(entorno_valido(tmp_path))
    assert c.remoto and c.total_casos is None and c.ttl_s == 1200 and c.tipo == "2"
    assert TOKEN not in repr(c) and str(tmp_path) not in repr(c)
    assert Config.desde_entorno({**entorno_valido(tmp_path), "TINOTIFY_RR_TOTAL_CASOS": "15"}).total_casos == 15


@pytest.mark.parametrize("cambio", [
    {"TINOTIFY_SR_TOKEN": "x"}, {"TINOTIFY_REAL_DB": "x"}, {"SIGAC_USUARIO": "x"}, {"TINOTIFY_SIGAC_CLAVE": "x"},
    {"DATABASE_URL": "x"}, {"SUPABASE_SERVICE_ROLE_KEY": "x"}, {"PGPASSWORD": "x"}, {"TINOTIFY_RR_OTRA": "x"},
    {"TINOTIFY_RR_MODO": "otro"}, {"TINOTIFY_RR_TOKEN": "corto"}, {"TINOTIFY_RR_TOKEN": "changeme" + "x" * 30},
    {"TINOTIFY_RR_TLS": "ninguno"}, {"TINOTIFY_RR_PROXIES_CONFIABLES": "0.0.0.0/0"}, {"TINOTIFY_RR_TTL_MIN": "0"},
    {"TINOTIFY_RR_TTL_MIN": "61"}, {"TINOTIFY_RR_TOTAL_CASOS": "0"}, {"TINOTIFY_RR_TIPO": "a b"},
    {"TINOTIFY_RR_MAX_LOGINS": "11"}, {"TINOTIFY_RR_ACREDITACION_FILE": "/no/existe"}, {"TINOTIFY_RR_REFERENCIA_FILE": ""},
])
def test_la_configuracion_insegura_o_ajena_no_arranca(tmp_path, cambio):
    with pytest.raises(ConfiguracionInsegura) as error:
        Config.desde_entorno({**entorno_valido(tmp_path), **cambio})
    assert "x" * 5 not in str(error.value) and TOKEN not in str(error.value)


def test_el_arranque_exige_acreditacion_referencia_y_expediente_acreditado(tmp_path, entorno):
    c = Config.desde_entorno(entorno_valido(tmp_path))
    with pytest.raises(ConfiguracionInsegura):  # archivos sin contenido válido
        crear_app(c)
    _, ref = entorno[0], entorno[1]
    otra, _ = referencia_de(entorno[0], numero=102)  # número no acreditado por la política de prueba
    with pytest.raises(ConfiguracionInsegura):
        crear_app(config(), politica=politica_de_prueba(), referencia=otra)
    assert crear_app(config(), politica=politica_de_prueba(), referencia=ref) is not None


# --- Listado estructural ----------------------------------------------------------------------------------------------

def test_el_listado_estructural_conserva_las_verificaciones_y_el_modo_normal_no_cambia():
    assert [c.numero for c in extraer_casos(LISTADO, estricto=True, estructural=True)] == [101]
    duplicado = LISTADO.replace("</table>", LISTADO.split("</tr>", 1)[1].split("<tr", 1)[0] + "</table>")
    fila = '<tr class="fila_enlace" onclick="abrir(101)"><td>101</td><td>C</td><td>E</td></tr>'
    for html in (LISTADO.replace("</table>", fila + "</table>"),                       # duplicado
                 LISTADO.replace("onclick=\"abrir(101)\"", "onclick=\"abrir(999)\""),   # onclick incoherente
                 LISTADO.replace("<th>Estado</th>", "<th>Otro</th>"),                   # columnas
                 LISTADO.replace(fila, "").replace('<tr class="fila_enlace" onclick="abrir(101)"><td>101</td><td>CLIENTE_FICTICIO</td><td>FICTICIO</td></tr>', ""),  # vacío
                 "<html><body>sin tabla</body></html>"):
        with pytest.raises(ValueError):
            extraer_casos(html, estricto=True, estructural=True)
    with pytest.raises(ValueError):
        extraer_casos(LISTADO, estricto=True, total_esperado=1, estructural=True)  # no admite un total
    with pytest.raises(ValueError):
        extraer_casos(LISTADO, estricto=True)                                       # sin total y sin opción: igual que antes
    with pytest.raises(ValueError):
        extraer_casos(LISTADO, estricto=True, total_esperado=2)


def test_el_cliente_exige_la_opcion_explicita_para_omitir_el_total():
    with cliente_sintetico([CONTENIDO]) as (cliente, llamadas):
        from tinotify.integrations.sigac.sigac_client import SigacClientError
        with pytest.raises(SigacClientError):
            cliente.autenticar(USUARIO, CLAVE, tipo="2", total_casos_esperado=None)
        with pytest.raises(SigacClientError):
            cliente.autenticar(USUARIO, CLAVE, tipo="2", total_casos_esperado=1, listado_estructural=True)
        assert llamadas == []  # ninguna solicitud con argumentos inválidos
        assert [c.numero for c in cliente.autenticar(USUARIO, CLAVE, tipo="2", total_casos_esperado=None, listado_estructural=True)] == [101]


# --- Rutas ---------------------------------------------------------------------------------------------------------------

def con_servidor(entorno, contenidos, **kwargs):
    """Contexto: (cliente HTTP de la app, historial, reloj, llamadas SIGAC)."""
    import contextlib

    @contextlib.contextmanager
    def ctx():
        reloj = kwargs.pop("reloj", None) or Reloj()
        historial = HistorialTemporal(reloj=reloj)
        with cliente_sintetico(contenidos) as (sigac, llamadas):
            app = crear_app(kwargs.pop("cfg", None) or config(), politica=politica_de_prueba(), referencia=entorno[1],
                            historial=historial, fabrica_cliente=lambda: sigac, reloj=reloj)
            yield cliente_http(app), historial, reloj, llamadas
    return ctx()


def test_el_flujo_completo_login_lista_historial_detalle_y_cierre(entorno):
    with con_servidor(entorno, [CONTENIDO, CONTENIDO]) as (c, h, reloj, llamadas):
        assert c.get("/health").json() == {"status": "ok"}
        assert c.get("/real/cases").status_code == 401
        assert c.get("/real/cases", headers={"Authorization": "Bearer " + "z" * 40}).status_code == 401
        casos = c.get("/real/cases", headers=CAB).json()
        assert len(casos) == 1 and casos[0]["ocurrencias_observadas"] == 4 and casos[0]["titulo"] == "Expediente local"
        assert casos[0]["id"] == entorno[1].caso_id and caso_local(101) not in json.dumps(casos)
        caso = casos[0]["id"]
        assert c.get(f"/real/cases/{caso}/historial", headers=CAB).status_code == 404  # sin sesión todavía
        r = login(c)
        assert r.status_code == 200 and r.json() == {"estado": "activa", "expira_en_s": 300, "actuaciones": 4,
                                                      "en_referencia": 4, "adicionales": 0}
        assert llamadas.count("casos.formCaso.con") == 1 and llamadas.count("sesion.validar.ses") == 1
        lista = c.get(f"/real/cases/{caso}/historial", headers=CAB).json()
        assert lista["total"] == 4 and lista["en_referencia"] == 4 and lista["formato_inesperado"] == 0
        sesion = lista["sesion"]
        d = c.get(f"/real/cases/{caso}/historial/2", params={"sesion": sesion}, headers=CAB)
        assert d.status_code == 200 and d.json()["indice"] == 2 and d.json()["en_referencia"] is True
        assert "CONTENIDO_SINTETICO" in d.json()["descripcion"] and d.headers["cache-control"] == "no-store"
        assert c.get("/real/sesion/estado", headers=CAB).json()["activa"] is True
        assert c.get("/real/observaciones", headers=CAB).json()["observaciones"] == []
        assert c.delete("/real/sesion", headers=CAB).json() == {"activa": False}
        assert c.get(f"/real/cases/{caso}/historial", headers=CAB).status_code == 404
        assert c.get(f"/real/cases/{caso}/historial/2", params={"sesion": sesion}, headers=CAB).status_code == 404
        assert c.get("/real/sesion/estado", headers=CAB).json() == {"activa": False, "actuaciones": 0, "expira_en_s": 0}


def test_la_sesion_expira_y_una_nueva_invalida_el_contenido_anterior(entorno):
    with con_servidor(entorno, [CONTENIDO, CONTENIDO]) as (c, h, reloj, _):
        caso = entorno[1].caso_id
        assert login(c).status_code == 200
        s1 = c.get(f"/real/cases/{caso}/historial", headers=CAB).json()["sesion"]
        assert login(c).status_code == 200
        s2 = c.get(f"/real/cases/{caso}/historial", headers=CAB).json()["sesion"]
        assert s1 != s2
        assert c.get(f"/real/cases/{caso}/historial/0", params={"sesion": s1}, headers=CAB).status_code == 404
        assert c.get(f"/real/cases/{caso}/historial/0", params={"sesion": s2}, headers=CAB).status_code == 200
        reloj.t += 300
        assert c.get(f"/real/cases/{caso}/historial/0", params={"sesion": s2}, headers=CAB).status_code == 404
        assert c.get(f"/real/cases/{caso}/historial", headers=CAB).status_code == 404
        assert h._sesion is None  # el contenido se soltó
        assert c.get(f"/real/cases/{caso_local(101)}/historial", headers=CAB).status_code == 404  # otro identificador


def test_transporte_origen_y_cuerpo_se_validan_antes_de_cualquier_acceso(entorno):
    with con_servidor(entorno, [CONTENIDO]) as (c, h, reloj, llamadas):
        app = c.app
        remoto = TestClient(app, base_url="http://127.0.0.1:8000", client=("203.0.113.9", 4000))
        assert remoto.get("/real/cases", headers=CAB).status_code == 403
        assert remoto.get("/health").status_code == 200
        assert c.get("/real/cases", headers={**CAB, "Origin": "https://pagina.example"}).status_code == 403
        cuerpo = json.dumps({"usuario": "u", "clave": "c"})
        assert c.post("/real/sesion", content=cuerpo, headers={**CAB, "Origin": "https://x.example"}).status_code == 403
        assert c.post("/real/sesion", content="x" * 5000, headers=CAB).status_code == 413
        for malo in ('{"usuario":"u"}', '{"usuario":"u","clave":"c","extra":1}', '{"usuario":"","clave":"c"}', "no json", "[]"):
            r = c.post("/real/sesion", content=malo, headers={**CAB, "Content-Type": "application/json"})
            assert r.status_code == 422 and r.json() == {"detail": "Entrada no valida"}
        assert llamadas == []


def test_el_modo_remoto_exige_https_de_un_proxy_confiable(entorno):
    from tinotify.real_remoto.comun import REDES_PRIVADAS
    huellas, ref = entorno
    cfg = config(modo="remoto", tls="proxy", proxies_confiables=REDES_PRIVADAS)
    with cliente_sintetico([CONTENIDO]) as (sigac, llamadas):
        app = crear_app(cfg, politica=politica_de_prueba(), referencia=ref, fabrica_cliente=lambda: sigac)
        privado = TestClient(app, base_url="http://127.0.0.1:8000", client=("10.1.2.3", 4000))
        assert privado.get("/real/cases", headers=CAB).status_code == 403                                  # sin X-Forwarded-Proto
        assert privado.get("/real/cases", headers={**CAB, "X-Forwarded-Proto": "http"}).status_code == 403
        assert privado.get("/real/cases", headers={**CAB, "X-Forwarded-Proto": "https"}).status_code == 200
        externo = TestClient(app, base_url="http://127.0.0.1:8000", client=("198.51.100.7", 4000))          # no es un proxy confiable
        assert externo.get("/real/cases", headers={**CAB, "X-Forwarded-Proto": "https"}).status_code == 403
        assert llamadas == []


# --- Errores sin filtraciones, límites y concurrencia -------------------------------------------------------------------

def sigac_con(manejador):
    return SigacClient(httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(manejador), follow_redirects=False))


def servidor_de_error(entorno, manejador, **kwargs):
    huellas, ref = entorno
    app = crear_app(kwargs.pop("cfg", None) or config(), politica=politica_de_prueba(), referencia=ref,
                    historial=HistorialTemporal(), fabrica_cliente=lambda: sigac_con(manejador))
    return cliente_http(app)


def test_credenciales_rechazadas_y_fallos_de_red_dan_errores_genericos(entorno):
    def rechaza(peticion):
        ruta = peticion.url.path.removeprefix("/sigac/")
        return httpx.Response(200, headers={"content-type": "text/html"}, text=FORMULARIO)  # el login vuelve al formulario

    def sin_red(peticion):
        raise httpx.ConnectError("fallo con URL https://sigac.udea.edu.co y cookie secreta")
    c = servidor_de_error(entorno, rechaza)
    r = login(c, "usuario-secreto", "clave-secreta")
    assert r.status_code == 403 and r.json() == {"detail": "Acceso no confirmado"}
    c2 = servidor_de_error(entorno, sin_red)
    r2 = login(c2, "usuario-secreto", "clave-secreta")
    assert r2.status_code == 502 and r2.json() == {"detail": "El servicio institucional no respondió como se esperaba"}
    for r in (r, r2):
        assert not any(s in r.text.lower() for s in ("usuario", "clave-secreta", "sigac", "udea", "cookie", "autenticacion", "codigo"))


def test_la_lectura_que_no_contiene_la_referencia_se_rechaza_y_no_deja_contenido(entorno):
    otro = pagina(*(bloque(f"OTRO_{n}") for n in range(4)))
    with con_servidor(entorno, [otro]) as (c, h, reloj, _):
        r = login(c)
        assert r.status_code == 422 and r.json() == {"detail": "La lectura no corresponde a la referencia acreditada"}
        assert h.estado()["activa"] is False


def test_actuaciones_nuevas_se_marcan_sin_aceptar_una_referencia_incompleta(entorno):
    mas = pagina(*(bloque(f"CONTENIDO_SINTETICO_{n}") for n in range(4)), bloque("POSTERIOR", fecha="2021-05-05 10:00:00"))
    with con_servidor(entorno, [mas]) as (c, h, reloj, _):
        r = login(c)
        assert r.status_code == 200 and r.json()["actuaciones"] == 5 and r.json()["adicionales"] == 1
        lista = c.get(f"/real/cases/{entorno[1].caso_id}/historial", headers=CAB).json()
        assert [a["en_referencia"] for a in lista["actuaciones"]].count(False) == 1
    menos = pagina(*(bloque(f"CONTENIDO_SINTETICO_{n}") for n in range(3)))
    with con_servidor(entorno, [menos]) as (c, h, reloj, _):
        assert login(c).status_code == 422 and h.estado()["activa"] is False


def test_un_total_de_casos_configurado_se_sigue_exigiendo_y_sin_el_no_hay_numero_fijo(entorno):
    with con_servidor(entorno, [CONTENIDO], cfg=config(total_casos=1)) as (c, _, _, _):
        assert login(c).status_code == 200
    with con_servidor(entorno, [CONTENIDO], cfg=config(total_casos=15)) as (c, h, _, _):
        r = login(c)
        assert r.status_code == 502 and h.estado()["activa"] is False   # no coincide: falla cerrado
    with con_servidor(entorno, [CONTENIDO]) as (c, _, _, _):             # sin total: verificación estructural
        assert login(c).status_code == 200


def test_el_presupuesto_de_intentos_limita_incluso_con_credenciales_correctas(entorno):
    llamadas_fabrica = []
    huellas, ref = entorno
    reloj = Reloj()
    with cliente_sintetico([CONTENIDO, CONTENIDO, CONTENIDO]) as (sigac, _):
        def fabrica():
            llamadas_fabrica.append(1)
            return sigac
        app = crear_app(config(max_logins=2, ventana_login_s=600), politica=politica_de_prueba(), referencia=ref,
                        historial=HistorialTemporal(reloj=reloj), fabrica_cliente=fabrica, reloj=reloj)
        c = cliente_http(app)
        assert login(c).status_code == 200 and login(c).status_code == 200
        r = login(c)
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and len(llamadas_fabrica) == 2
        reloj.t += 601
        assert login(c).status_code == 200


def test_un_segundo_login_simultaneo_se_rechaza_sin_tocar_siguiente_cliente(entorno):
    entro, seguir, creados = threading.Event(), threading.Event(), []
    huellas, ref = entorno
    with cliente_sintetico([CONTENIDO, CONTENIDO]) as (sigac, _):
        def fabrica():
            creados.append(1)
            entro.set()
            assert seguir.wait(10)
            return sigac
        app = crear_app(config(), politica=politica_de_prueba(), referencia=ref, historial=HistorialTemporal(),
                        fabrica_cliente=fabrica)
        resultado = {}
        hilo = threading.Thread(target=lambda: resultado.update(r=login(cliente_http(app))))
        hilo.start()
        assert entro.wait(10)
        assert login(cliente_http(app)).status_code == 409 and len(creados) == 1
        seguir.set()
        hilo.join(10)
        assert resultado["r"].status_code == 200


def test_las_credenciales_no_se_conservan_ni_se_registran(entorno, caplog):
    secreto_u, secreto_c = USUARIO, CLAVE
    caplog.set_level(logging.DEBUG)
    with con_servidor(entorno, [CONTENIDO]) as (c, h, reloj, _):
        app = c.app
        r = login(c, secreto_u, secreto_c)
        assert r.status_code == 200
        textos = [r.text, r.headers.__repr__()] + [rec.getMessage() for rec in caplog.records]
        assert not any(secreto_u in t or secreto_c in t for t in textos)
        # Nada en el estado de la aplicación contiene las credenciales (ni como texto ni como bytes).
        import gc
        estado = repr(vars(h)) + repr(c.app.state.__dict__) + repr(sorted(vars(c.app).keys()))
        assert secreto_u not in estado and secreto_c not in estado
        asignaciones = [o for o in gc.get_objects() if isinstance(o, dict) and any(
            isinstance(v, str) and v in (secreto_u, secreto_c) for v in list(o.values())[:50])]
        propios = [o for o in asignaciones if any(k in o for k in ("_sesion", "_config", "_referencia", "_historial"))]
        assert propios == []
        assert h._sesion is not None and secreto_c not in json.dumps(h._sesion.items)


def test_el_codigo_fuente_no_registra_ni_persiste_credenciales():
    from pathlib import Path
    import tinotify.real_remoto as paquete
    fuentes = "\n".join(p.read_text(encoding="utf-8") for p in Path(paquete.__file__).parent.glob("*.py"))
    assert "print(" not in fuentes and "open(" not in fuentes and "write_text" not in fuentes
    assert "psycopg" not in fuentes and "sqlite3" not in fuentes
    import re
    for linea in fuentes.splitlines():
        if re.search(r"registro\.|logging\.|log\.", linea) and re.search(r"usuario|clave|password|token", linea, re.I):
            assert "logging.getLogger" in linea or "setLevel" in linea or "nunca" in linea, linea


# --- Despliegue: variables, preflight, presupuesto y scripts ---------------------------------------------------------------

def test_las_variables_ajenas_se_informan_solo_por_nombre(tmp_path):
    from tinotify.real_remoto.config import VariablesAjenas
    e = {**entorno_valido(tmp_path), "TINOTIFY_SR_PG_PASSWORD": "valor-secreto-123", "TINOTIFY_SR_TOKEN": "otro-secreto",
         "DATABASE_URL": "cadena-de-conexion-ficticia", "SUPABASE_URL": "https://x", "PGSSLMODE": "disable"}
    with pytest.raises(VariablesAjenas) as error:
        Config.desde_entorno(e)
    assert error.value.nombres == ("DATABASE_URL", "PGSSLMODE", "SUPABASE_URL", "TINOTIFY_SR_PG_PASSWORD", "TINOTIFY_SR_TOKEN")
    texto = str(error.value)
    assert "TINOTIFY_SR_PG_PASSWORD" in texto and not any(v in texto for v in ("valor-secreto-123", "otro-secreto", "cadena-de-conexion-ficticia", "https://x", "disable"))
    # Las variables propias de Render no estorban.
    ok = {**entorno_valido(tmp_path), "RENDER": "true", "RENDER_SERVICE_NAME": "tinotify-api", "RENDER_EXTERNAL_URL": "https://x.onrender.com",
          "RENDER_GIT_COMMIT": "abc", "IS_PULL_REQUEST": "false", "PYTHONUNBUFFERED": "1"}
    assert Config.desde_entorno(ok).remoto


def test_el_preflight_valida_los_archivos_sin_imprimir_su_contenido(tmp_path, entorno):
    from tinotify.real_remoto import preflight
    clave = tmp_path / "clave.json"
    clave.write_text(json.dumps({"version": 1, "clave_hex": CLAVE_TEST.hex()}), encoding="utf-8")
    _, doc = referencia_de(entorno[0])
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps(doc), encoding="utf-8")
    e = {"TINOTIFY_RR_MODO": "remoto", "TINOTIFY_RR_TOKEN": TOKEN, "TINOTIFY_RR_TLS": "proxy",
         "TINOTIFY_RR_PROXIES_CONFIABLES": "privadas", "TINOTIFY_RR_ACREDITACION_FILE": str(clave),
         "TINOTIFY_RR_REFERENCIA_FILE": str(ref)}
    r = preflight.verificar(e)
    # Con los archivos de PRUEBA y el contrato de producción, la acreditación no coincide: falla cerrado y con código.
    assert r["configuracion"] and r["clave_acreditacion"] and not r["aplicacion"]
    assert r["fallo"] in ("referencia_portable_invalida", "clave_o_expediente_no_acreditado")
    salida = json.dumps(r)
    assert TOKEN not in salida and str(tmp_path) not in salida and CLAVE_TEST.hex() not in salida and doc["mac"] not in salida
    assert preflight.verificar({**e, "TINOTIFY_SR_TOKEN": "x"})["variables_a_retirar"] == ["TINOTIFY_SR_TOKEN"]
    assert preflight.verificar({**e, "TINOTIFY_RR_REFERENCIA_FILE": str(tmp_path / "no.json")})["fallo"] == "referencia_ausente"


def test_un_atacante_sin_token_no_consume_el_presupuesto_ni_bloquea_al_usuario_legitimo(entorno):
    huellas, ref = entorno
    fabricas = []
    with cliente_sintetico([CONTENIDO, CONTENIDO]) as (sigac, _):
        def fabrica():
            fabricas.append(1)
            return sigac
        app = crear_app(config(max_logins=3), politica=politica_de_prueba(), referencia=ref, historial=HistorialTemporal(),
                        fabrica_cliente=fabrica)
        c = cliente_http(app)
        cuerpo = json.dumps({"usuario": "u", "clave": "c"})
        for i in range(60):  # inundación sin token, con token erróneo, con Origin, desde fuera y con cuerpos inválidos
            c.post("/real/sesion", content=cuerpo, headers={"Content-Type": "application/json"})
            c.post("/real/sesion", content=cuerpo, headers={"Authorization": f"Bearer {'x' * 40}{i}", "Content-Type": "application/json"})
            c.post("/real/sesion", content=cuerpo, headers={**CAB, "Origin": "https://x.example"})
            TestClient(app, base_url="http://127.0.0.1:8000", client=("203.0.113.5", 1)).post("/real/sesion", content=cuerpo, headers=CAB)
            c.post("/real/sesion", content="no json", headers={**CAB, "Content-Type": "application/json"})
        assert fabricas == []                                  # ninguna llegó a SIGAC ni gastó presupuesto
        assert login(c).status_code == 200 and login(c).status_code == 200 and len(fabricas) == 2   # el usuario legítimo sigue entrando
        assert c.get("/real/cases", headers=CAB).status_code == 200
        assert c.get("/real/cases", headers={"Authorization": "Bearer " + "y" * 40}).status_code == 429  # el atacante sí se frena


def test_los_scripts_remotos_exigen_https_terminal_y_confirmacion(monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    def cargar(nombre):
        ruta = Path(__file__).resolve().parents[1] / "scripts" / nombre
        spec = importlib.util.spec_from_file_location(nombre[:-3], ruta)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    verificar, prueba = cargar("verificar_remoto_real.py"), cargar("prueba_login_remoto.py")
    monkeypatch.setattr(httpx.Client, "get", lambda *a, **k: pytest.fail("No debe conectar"))
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: pytest.fail("No debe conectar"))
    for modulo, extra in ((verificar, []), (prueba, [])):
        for url in ("http://tinotify.onrender.com", "https://u:p@tinotify.onrender.com", "https://x.com/?t=1"):
            with pytest.raises(SystemExit):
                modulo.main(["--url", url, *extra])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    real = "https://servicio-real.onrender.com"
    with pytest.raises(SystemExit):
        prueba.main(["--url", real])                                # sin terminal
    with pytest.raises(SystemExit):
        verificar.main(["--url", real, "--con-token"])
    for modulo in (verificar, prueba):
        with pytest.raises(SystemExit):                             # --url es obligatorio: nunca hay destino por defecto
            modulo.main([])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: "no")
    monkeypatch.setattr(prueba.getpass, "getpass", lambda *_: pytest.fail("No debe pedir credenciales sin confirmación"))
    assert prueba.main(["--url", real]) == 2                        # sin la confirmación no hay conexión ni credenciales
    fuente = (Path(prueba.__file__) if hasattr(prueba, "__file__") else Path("x")).read_text(encoding="utf-8") if hasattr(prueba, "__file__") else ""
    assert "print(usuario" not in fuente and "print(clave" not in fuente and "open(" not in fuente


def _respuestas(rutas):
    """Cliente httpx simulado (sin red) para los GET sin autenticación del destino."""
    def manejador(peticion):
        codigo, cuerpo = rutas.get(peticion.url.path, (404, {}))
        return httpx.Response(codigo, json=cuerpo)
    return httpx.Client(base_url="https://x.example", transport=httpx.MockTransport(manejador))


def test_el_login_remoto_solo_pide_credenciales_si_el_destino_es_el_backend_real(monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "prueba_login_remoto.py"
    spec = importlib.util.spec_from_file_location("prueba_login_remoto_t", ruta)
    prueba = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prueba)
    real = {"/health": (200, {"status": "ok"}), "/real/cases": (401, {}), "/sintetico/casos": (404, {})}
    sintetico = {"/health": (200, {"estado": "ok"}), "/real/cases": (404, {}), "/sintetico/casos": (401, {})}
    mixto = {"/health": (200, {"status": "ok"}), "/real/cases": (401, {}), "/sintetico/casos": (401, {})}
    abierto = {"/health": (200, {"status": "ok"}), "/real/cases": (200, []), "/sintetico/casos": (404, {})}
    monkeypatch.setattr(prueba.time, "sleep", lambda *_: None)
    assert prueba.es_backend_real(_respuestas(real), esperar_s=5) is True
    for malo in (sintetico, mixto, abierto):
        assert prueba.es_backend_real(_respuestas(malo), esperar_s=5) is False
    assert prueba.es_backend_real(_respuestas({"/health": (503, {})}), esperar_s=0) is False
    # main: ante un destino sintético se aborta SIN pedir token ni credenciales.
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: prueba.CONFIRMACION)
    monkeypatch.setattr(prueba.getpass, "getpass", lambda *_: pytest.fail("No debe pedir credenciales a un destino no real"))
    monkeypatch.setattr(prueba, "es_backend_real", lambda *a, **k: False)
    assert prueba.main(["--url", "https://sintetico.example"]) == 5


def test_los_secretos_se_ignoran_en_cualquier_carpeta_y_la_evidencia_saneada_no():
    import shutil
    import subprocess
    from pathlib import Path
    if shutil.which("git") is None:
        pytest.skip("git no disponible")
    raiz = Path(__file__).resolve().parents[2]
    def ignorado(ruta):
        return subprocess.run(["git", "check-ignore", "-q", ruta], cwd=raiz).returncode == 0
    for ruta in ("acreditacion_sigac.json", "backend/acreditacion_sigac.json", "docs/x/referencia_portable.json",
                 "referencia_portable.json", "backend/codigo_acceso_real.txt", "backend/.local/real_v2.sqlite3",
                 "backend/.local/referencia_portable.json", "backend/build/lib/x.py"):
        assert ignorado(ruta), ruta
    assert not ignorado("docs/evidencia/comparacion-v1-sigac-continuidad.json")


def test_la_definicion_sustituye_el_arranque_del_servicio_existente_sin_ejecutar_codigo_sintetico():
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[2]
    propuesta, activo = raiz / "render.real-remoto.propuesta.yaml", raiz / "render.yaml"
    # En el árbol de trabajo la definición real está en la propuesta y render.yaml sigue siendo el de main (sintético);
    # en la rama deploy/real-remoto render.yaml ES la definición real y no existe la propuesta.
    definicion = (propuesta if propuesta.exists() else activo).read_text(encoding="utf-8")
    if propuesta.exists():
        assert "real_remoto" not in activo.read_text(encoding="utf-8")  # el render.yaml de esta rama no se tocó
    lineas = [l.split("  #")[0] for l in definicion.splitlines() if not l.lstrip().startswith("#")]
    efectivo = chr(10).join(lineas)
    assert "name: tinotify-api" in efectivo and "tinotify-real" not in efectivo  # sustituye el servicio, no crea otro
    assert "branch: deploy/real-remoto" in efectivo and "branch: main" not in efectivo and "sintetico" not in efectivo
    assert "tinotify.real_remoto.app:crear_app --factory" in efectivo and "--workers 1" in efectivo and "--no-proxy-headers" in efectivo
    assert 'autoDeployTrigger: "off"' in efectivo and "healthCheckPath: /health" in efectivo and "rootDir: backend" in efectivo
    assert "TINOTIFY_SR_" not in efectivo and "DATABASE_URL" not in efectivo and "SUPABASE" not in efectivo and "PG" not in efectivo.replace("PYTHON", "")
    assert "/etc/secrets/acreditacion_sigac.json" in efectivo and "/etc/secrets/referencia_portable.json" in efectivo
    token = efectivo.split("TINOTIFY_RR_TOKEN", 1)[1]
    assert "sync: false" in token.splitlines()[1] and "value" not in token.splitlines()[1]


def _en_subproceso(codigo):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-B", "-c", codigo], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-300:]
    return json.loads(r.stdout)


def test_el_backend_real_no_carga_codigo_sintetico_ni_psycopg_en_ejecucion():
    datos = _en_subproceso(
        "import sys, json, tinotify.real_remoto.app, tinotify.real_remoto.preflight; "
        "print(json.dumps({'sinteticos': sorted(m for m in sys.modules if 'sintetico' in m),"
        " 'psycopg': any(m.startswith('psycopg') for m in sys.modules),"
        " 'api_demo': 'tinotify.api.demo' in sys.modules, 'demo_servicio': 'tinotify.demo.servicio' in sys.modules}))")
    assert datos == {"sinteticos": [], "psycopg": False, "api_demo": False, "demo_servicio": False}
    from pathlib import Path
    import tinotify.real_remoto as paquete
    for archivo in Path(paquete.__file__).parent.glob("*.py"):
        assert "sintetico_remoto" not in archivo.read_text(encoding="utf-8").replace("`tinotify.sintetico_remoto`", ""), archivo.name


def test_las_dependencias_de_terceros_del_backend_real_estan_en_requirements_con_hash():
    from importlib import metadata
    from pathlib import Path
    import re
    datos = _en_subproceso(
        "import sys, json, tinotify.real_remoto.app, tinotify.real_remoto.preflight; "
        "print(json.dumps(sorted({m.split('.')[0] for m in sys.modules if not m.startswith('_')"
        " and m.split('.')[0] not in sys.stdlib_module_names and m.split('.')[0] != 'tinotify'})))")
    mapa = metadata.packages_distributions()
    distribuciones = {re.sub(r"[-_.]+", "-", d).lower() for m in datos for d in mapa.get(m, [m])}
    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    declarados = {re.sub(r"[-_.]+", "-", l.split("==")[0].strip()).lower() for l in requirements.splitlines()
                  if "==" in l and not l.startswith((" ", "#"))}
    # httpx intenta importar su CLI opcional (`httpx._main`: pygments/rich) dentro de un try/except ImportError; Pygments solo está
    # en el entorno de desarrollo (pytest) y no es dependencia de ejecución ni forma parte de requirements.txt.
    opcionales = {"pygments", "rich"}
    assert distribuciones - opcionales <= declarados, sorted(distribuciones - opcionales - declarados)
    assert "--hash=sha256:" in requirements


def test_el_verificador_de_la_rama_detecta_rutas_secretos_y_texto_judicial():
    import importlib.util
    from pathlib import Path
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "verificar_rama_despliegue.py"
    spec = importlib.util.spec_from_file_location("verificar_rama_t", ruta)
    v = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v)
    contenidos = {
        "backend/src/ok.py": b"print('limpio')",
        "backend/.local/real_v2.sqlite3": b"x", "backend/.local/acreditacion_sigac.json": b"{}",
        "backend/datos.sqlite3": b"x", "mobile/app-release.apk": b"x", "backend/google-services.json": b"{}",
        "referencia_portable.json": b"{}", "backend/codigo_acceso_real.txt": b"x", "backend/.env": b"A=1",
        "backend/build/lib/x.py": b"x", "backend/llave.pem": b"x",
        "backend/src/clave.py": b"K = 'clave-secreta-conocida-123'",
        "backend/src/url.py": b"U = '" + b"postgresql" + b"://usuario:contrasena@host/db'",
        "backend/src/jwt.py": b"T = 'eyJ" + b"a" * 30 + b"." + b"b" * 30 + b"." + b"c" * 20 + b"'",
        "backend/src/llave.py": b"-----" + b"BEGIN PRIVATE KEY-----",
        "docs/nota.md": b"El texto judicial FRAGMENTO-JUDICIAL-FICTICIO-MUY-LARGO-PARA-LA-PRUEBA aparece aqui",
        "docs/grande.md": b"x" * (v.MAX_BYTES + 1),
        "backend/.env.example": b"A=",
    }
    problemas = v.evaluar(sorted(contenidos), lambda r: contenidos[r], secretos={"clave-secreta-conocida-123"},
                          fragmentos={"FRAGMENTO-JUDICIAL-FICTICIO-MUY-LARGO-PARA-LA-PRUEBA"})
    assert set(problemas["ruta_prohibida"]) == {
        "backend/.local/real_v2.sqlite3", "backend/.local/acreditacion_sigac.json", "backend/datos.sqlite3", "mobile/app-release.apk",
        "backend/google-services.json", "referencia_portable.json", "backend/codigo_acceso_real.txt", "backend/.env",
        "backend/build/lib/x.py", "backend/llave.pem"}
    assert problemas["secreto_conocido"] == ["backend/src/clave.py"]
    assert set(problemas["patron_de_secreto"]) == {"backend/src/url.py", "backend/src/jwt.py", "backend/src/llave.py"}
    assert problemas["texto_judicial"] == ["docs/nota.md"] and problemas["demasiado_grande"] == ["docs/grande.md"]
    assert "backend/src/ok.py" not in json.dumps(problemas) and "backend/.env.example" not in json.dumps(problemas)
    assert v.pertenece("backend/src/x.py") and v.pertenece("docs/a.md") and v.pertenece("render.yaml")
    assert not any(v.pertenece(r) for r in ("mobile/App.tsx", "supabase/config.toml", "package.json", "otra/cosa.py"))


def test_un_fallo_de_sigac_se_registra_solo_con_codigos_de_catalogo(entorno, caplog):
    def sin_red(peticion):
        raise httpx.ConnectError("detalle con https://sigac.udea.edu.co y cookie-secreta y usuario-secreto")
    c = servidor_de_error(entorno, sin_red)
    caplog.set_level(logging.WARNING)
    r = login(c, "usuario-secreto", "clave-secreta")
    assert r.status_code == 502
    mensajes = [x.getMessage() for x in caplog.records if x.name == "tinotify.real_remoto"]
    assert mensajes == ["sigac_fallo codigo=fallo_transporte_o_codificacion etapa=formulario_acceso causa=ConnectError"]
    todo = " ".join(x.getMessage() for x in caplog.records)
    assert not any(s in todo for s in ("sigac.udea", "cookie-secreta", "usuario-secreto", "clave-secreta"))
