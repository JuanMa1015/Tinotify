"""Historial temporal en memoria: correspondencia con la línea base, expiración, invalidación y rutas locales.

Todo el contenido es ficticio y existe solo para ejercitar código; no acredita nada sobre SIGAC real.
"""

from datetime import datetime
import json

from fastapi.testclient import TestClient
import pytest

from backend.tests.test_contrato_expediente import USUARIO, CLAVE, bloque, cliente_sintetico, pagina, politica_de_prueba, servicio_real
from tinotify.api.demo import crear_app
from tinotify.api.real_local import AccesoLocal
from tinotify.demo.servicio import ServicioDemo
from tinotify.domain.actuaciones import Actuacion, Anexo
from tinotify.services.consulta_real_local import IdentidadExpedienteNoVerificada, caso_local, consultar_caso_acreditado
from tinotify.services.historial_temporal import (
    HistorialNoCorresponde, HistorialTemporal, VISTA_PREVIA, construir_items, leer_historial_temporal, referencia_v2,
)

CODIGO = "c" * 40
CASO = caso_local(101)


def act(texto, *, anexos=(), dia=1):
    return Actuacion("ETAPA", "ORIGEN", "DESTINO", datetime(2020, 1, dia, 10), "REMITENTE", texto, anexos=anexos)


class Reloj:
    t = 1000.0

    def __call__(self):
        return self.t


# --- Correspondencia ---------------------------------------------------------------------------------------------------

def test_cada_actuacion_se_asocia_a_su_huella_respetando_multiplicidades():
    a, b = act("A"), act("B")
    referencia = [("L1", a.huella_version), ("L2", a.huella_version), ("L3", b.huella_version)]
    items = construir_items([b, a, act("NUEVA"), a], referencia)
    por_texto = {}
    for i in items:
        por_texto.setdefault(i["descripcion"], []).append(i)
    assert [i["local_id"] for i in por_texto["B"]] == ["L3"]
    assert sorted(i["local_id"] for i in por_texto["A"]) == ["L1", "L2"]  # duplicado exacto: dos identidades distintas
    assert por_texto["NUEVA"][0]["local_id"] is None and por_texto["NUEVA"][0]["en_referencia"] is False
    assert [i["indice"] for i in items] == [0, 1, 2, 3]
    assert sum(i["en_referencia"] for i in items) == 3


def test_si_falta_alguna_huella_de_la_linea_base_no_se_conserva_nada():
    a = act("A")
    referencia = [("L1", a.huella_version), ("L2", a.huella_version)]
    with pytest.raises(HistorialNoCorresponde):
        construir_items([a], referencia)  # falta una copia del duplicado
    with pytest.raises(HistorialNoCorresponde):
        construir_items([act("OTRA")], referencia)
    with pytest.raises(HistorialNoCorresponde):
        construir_items([], referencia)


def test_los_anexos_solo_exponen_descripcion_nunca_archivo_ni_referencia():
    anexo = Anexo("DESCRIPCION ANEXO", "archivo_secreto.pdf", "general.descargarAnexo.con?codigo=SECRETO")
    items = construir_items([act("X", anexos=(anexo,))], [("L1", act("X", anexos=(anexo,)).huella_version)])
    assert items[0]["anexos"] == [{"descripcion": "DESCRIPCION ANEXO", "sin_enlace": False}]
    assert "archivo_secreto" not in json.dumps(items) and "SECRETO" not in json.dumps(items)


# --- Ciclo de vida -----------------------------------------------------------------------------------------------------

def cargar(almacen, ttl=300, texto="D" * 400):
    items = construir_items([act(texto)], [("L1", act(texto).huella_version)])
    return almacen.cargar(CASO, items, ttl)


def test_la_sesion_expira_y_el_contenido_deja_de_estar_disponible():
    reloj = Reloj()
    h = HistorialTemporal(reloj=reloj)
    s = cargar(h, 300)
    assert h.estado() == {"activa": True, "actuaciones": 1, "expira_en_s": 300}
    listado = h.listado(CASO)
    assert listado["total"] == 1 and listado["actuaciones"][0]["truncada"] is True
    assert len(listado["actuaciones"][0]["vista_previa"]) == VISTA_PREVIA
    assert h.detalle(CASO, s["sesion"], 0)["descripcion"] == "D" * 400
    reloj.t += 299
    assert h.detalle(CASO, s["sesion"], 0) is not None
    reloj.t += 1
    assert h.listado(CASO) is None and h.detalle(CASO, s["sesion"], 0) is None
    assert h.estado() == {"activa": False, "actuaciones": 0, "expira_en_s": 0}
    assert h._sesion is None  # no quedan referencias al contenido


def test_invalidar_y_una_sesion_nueva_dejan_inservible_el_contenido_anterior():
    h = HistorialTemporal(reloj=Reloj())
    vieja = cargar(h, texto="VIEJO")
    nueva = cargar(h, texto="NUEVO")
    assert h.detalle(CASO, vieja["sesion"], 0) is None  # el identificador anterior ya no sirve
    assert h.detalle(CASO, nueva["sesion"], 0)["descripcion"] == "NUEVO"
    assert h.detalle(caso_local(202), nueva["sesion"], 0) is None  # otro expediente
    assert h.detalle(CASO, nueva["sesion"], 1) is None and h.detalle(CASO, nueva["sesion"], -1) is None
    assert h.detalle(CASO, nueva["sesion"], True) is None
    h.invalidar()
    assert h.listado(CASO) is None and h.detalle(CASO, nueva["sesion"], 0) is None and h._sesion is None


@pytest.mark.parametrize("ttl", [0, 59, 3601, "300", None, 300.0])
def test_la_duracion_debe_estar_en_el_rango_permitido(ttl):
    items = construir_items([act("A")], [("L1", act("A").huella_version)])
    with pytest.raises(ValueError):
        HistorialTemporal().cargar(CASO, items, ttl)


# --- Rutas locales -----------------------------------------------------------------------------------------------------

def app_con_historial(tmp_path, historial):
    real = servicio_real(tmp_path, politica_de_prueba())
    return crear_app(servicio=ServicioDemo(["a" * 24, "b" * 24]), real=real, acceso_real=AccesoLocal(CODIGO), historial=historial)


def test_las_rutas_exigen_codigo_y_loopback_y_nunca_guardan_cache(tmp_path):
    h = HistorialTemporal(reloj=Reloj())
    sesion = cargar(h, texto="TEXTO COMPLETO")["sesion"]
    app = app_con_historial(tmp_path, h)
    local = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    remoto = TestClient(app, base_url="http://127.0.0.1:8000", client=("192.168.1.9", 50000))
    cab = {"Authorization": f"Bearer {CODIGO}"}
    ruta = f"/real/cases/{CASO}/historial"
    assert local.get(ruta).status_code == 401
    assert local.get(ruta, headers={"Authorization": "Bearer " + "x" * 40}).status_code == 401
    assert remoto.get(ruta, headers=cab).status_code == 403
    assert local.get(ruta, headers={**cab, "X-Forwarded-For": "1.2.3.4"}).status_code == 403
    assert TestClient(app, base_url="http://tunel.example", client=("127.0.0.1", 1)).get(ruta, headers=cab).status_code == 403
    r = local.get(ruta, headers=cab)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["actuaciones"][0]["vista_previa"] == "TEXTO COMPLETO"
    d = local.get(f"{ruta}/0", params={"sesion": sesion}, headers=cab)
    assert d.status_code == 200 and d.json()["descripcion"] == "TEXTO COMPLETO" and d.headers["cache-control"] == "no-store"
    assert local.get(f"{ruta}/0", params={"sesion": "00000000-0000-4000-8000-000000000000"}, headers=cab).status_code == 404
    assert local.get(f"{ruta}/0", headers=cab).status_code == 422  # la sesión es obligatoria
    assert remoto.get(f"{ruta}/0", params={"sesion": sesion}, headers=cab).status_code == 403
    assert local.get(f"/real/cases/{caso_local(202)}/historial", headers=cab).status_code == 404
    assert local.get("/real/historial/estado", headers=cab).json()["activa"] is True
    assert remoto.delete("/real/historial", headers=cab).status_code == 403
    assert local.delete("/real/historial", headers=cab).json() == {"activa": False}
    assert local.get(ruta, headers=cab).status_code == 404 and local.get(f"{ruta}/0", params={"sesion": sesion}, headers=cab).status_code == 404
    assert "TEXTO COMPLETO" not in local.get("/real/historial/estado", headers=cab).text


def test_sin_historial_configurado_las_rutas_no_existen(tmp_path):
    app = crear_app(servicio=ServicioDemo(["a" * 24, "b" * 24]), real=servicio_real(tmp_path), acceso_real=AccesoLocal(CODIGO))
    c = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1))
    assert c.get(f"/real/cases/{CASO}/historial", headers={"Authorization": f"Bearer {CODIGO}"}).status_code == 404
    assert c.get("/real/historial/estado", headers={"Authorization": f"Bearer {CODIGO}"}).status_code == 404


def test_el_historial_exige_los_datos_reales_protegidos():
    with pytest.raises(RuntimeError):
        crear_app(servicio=ServicioDemo(["a" * 24, "b" * 24]), historial=HistorialTemporal())


# --- Operación de lectura (HTTP simulado; no es SIGAC) ------------------------------------------------------------------

def establecer_linea_base(servicio, contenido):
    with cliente_sintetico([contenido]) as (cliente, _):
        return consultar_caso_acreditado(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=101, servicio=servicio)


def test_la_lectura_verifica_la_linea_base_conserva_solo_en_memoria_y_no_toca_v2(tmp_path):
    servicio = servicio_real(tmp_path, politica_de_prueba())
    contenido = pagina(*(bloque(f"CONTENIDO_SINTETICO_{n}") for n in range(4)))
    assert establecer_linea_base(servicio, contenido)["generacion"] == 1
    caso = caso_local(101)
    antes = (servicio.generacion(caso), servicio.detalle(caso)["ocurrencias_observadas"], servicio.observaciones())
    h = HistorialTemporal(reloj=Reloj())
    with cliente_sintetico([contenido]) as (cliente, llamadas):
        r = leer_historial_temporal(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=101, servicio=servicio, historial=h)
        assert llamadas.count("casos.formCaso.con") == 1 and llamadas.count("sesion.validar.ses") == 1
    assert r["persistencia"] == "solo_memoria" and r["linea_base_modificada"] is False and r["actuaciones"] == 4
    assert r["adicionales_a_la_referencia"] == 0 and "CONTENIDO_SINTETICO" not in json.dumps(r)
    listado = h.listado(caso)
    assert listado["total"] == 4 and listado["en_referencia"] == 4
    locales = {f["local_id"] for f in servicio.detalle(caso)["ocurrencias"]}
    assert {i["local_id"] for i in h._sesion.items} == locales  # cada actuación quedó asociada a una identidad v2
    assert (servicio.generacion(caso), servicio.detalle(caso)["ocurrencias_observadas"], servicio.observaciones()) == antes
    assert "CONTENIDO_SINTETICO" not in json.dumps(servicio.detalle(caso)) + json.dumps(servicio.observaciones())
    with open(tmp_path / "real.sqlite3", "rb") as f:
        assert b"CONTENIDO_SINTETICO" not in f.read()  # el texto nunca llegó al archivo SQLite


def test_una_lectura_que_no_contiene_la_linea_base_se_rechaza_sin_conservar_ni_modificar(tmp_path):
    servicio = servicio_real(tmp_path, politica_de_prueba())
    establecer_linea_base(servicio, pagina(*(bloque(f"CONTENIDO_SINTETICO_{n}") for n in range(4))))
    caso = caso_local(101)
    generacion = servicio.generacion(caso)
    h = HistorialTemporal(reloj=Reloj())
    with cliente_sintetico([pagina(*(bloque(f"OTRO_{n}") for n in range(4)))]) as (cliente, _):
        with pytest.raises(HistorialNoCorresponde):
            leer_historial_temporal(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=101, servicio=servicio, historial=h)
    assert h.estado()["activa"] is False and servicio.generacion(caso) == generacion


def test_actuaciones_nuevas_se_muestran_marcadas_sin_entrar_en_la_linea_base(tmp_path):
    servicio = servicio_real(tmp_path, politica_de_prueba())
    base = [bloque(f"CONTENIDO_SINTETICO_{n}") for n in range(3)]
    establecer_linea_base(servicio, pagina(*base))
    h = HistorialTemporal(reloj=Reloj())
    with cliente_sintetico([pagina(*base, bloque("POSTERIOR", fecha="2021-05-05 10:00:00"))]) as (cliente, _):
        r = leer_historial_temporal(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=101, servicio=servicio, historial=h)
    assert r["adicionales_a_la_referencia"] == 1
    marcadas = [i for i in h._sesion.items if not i["en_referencia"]]
    assert len(marcadas) == 1 and marcadas[0]["local_id"] is None and "POSTERIOR" in marcadas[0]["descripcion"]
    assert servicio.generacion(caso_local(101)) == 1


def test_la_lectura_no_conecta_sin_acreditacion_sin_linea_base_ni_en_perfil_sintetico(tmp_path):
    class SinRed:
        def __getattr__(self, nombre):
            pytest.fail("No debe autenticar ni conectar")
    h = HistorialTemporal()
    servicio = servicio_real(tmp_path, politica_de_prueba())
    with pytest.raises(IdentidadExpedienteNoVerificada):  # expediente no acreditado
        leer_historial_temporal(SinRed(), "u", "c", tipo="2", total_casos=1, caso_numero=102, servicio=servicio, historial=h)
    with pytest.raises(HistorialNoCorresponde):  # acreditado pero sin línea base v2
        leer_historial_temporal(SinRed(), "u", "c", tipo="2", total_casos=1, caso_numero=101, servicio=servicio, historial=h)
    from tinotify.demo.novedades import ServicioNovedadesLocal
    from tinotify.persistence.sqlite_local import AlmacenSqliteLocal
    sintetico = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "s.sqlite3"))
    with pytest.raises(IdentidadExpedienteNoVerificada):
        leer_historial_temporal(SinRed(), "u", "c", tipo="2", total_casos=1, caso_numero=101, servicio=sintetico, historial=h)
    assert h.estado()["activa"] is False
