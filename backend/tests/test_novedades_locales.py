"""Novedades sintéticas persistidas localmente (SQLite de desarrollo). Sin SIGAC, sin red, sin credenciales."""

import socket
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from tinotify.api.demo import crear_app
from tinotify.demo.novedades import (
    CASO_OBSERVADO, ObservacionRechazada, ServicioNovedadesLocal, html_historial_sintetico,
)
from tinotify.demo.push import ExpoPush
from tinotify.demo.servicio import ServicioDemo
from tinotify.domain.actuaciones import TipoCambio
from tinotify.parsers.parser import parse_actuaciones
from tinotify.persistence.sqlite_local import (
    BINDING_LOCAL, CREDENCIAL_LOCAL, WORKER_LOCAL, AlmacenLocalNoDisponible, AlmacenSqliteLocal,
    ConflictoPersistenciaLocal,
)
from tinotify.services.avisos_persistentes import ServicioAvisos
from tinotify.services.reconciliacion import reconciliar
from tinotify.services.seguimiento import ServicioSeguimiento


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "novedades_local.py"


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("Estas pruebas no deben abrir conexiones")
    # No se bloquea socket.connect: en Windows asyncio crea su canal interno con un socketpair local.
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "novedades.sqlite3"


def servicio_de(ruta):
    return ServicioNovedadesLocal(AlmacenSqliteLocal(ruta))


def observar(servicio, n):
    return servicio.observar_html(CASO_OBSERVADO, html_historial_sintetico(n))


def pendientes(ruta):
    return ServicioAvisos(AlmacenSqliteLocal(ruta)).pendientes(CREDENCIAL_LOCAL, binding=BINDING_LOCAL)


# --- Escenario funcional ------------------------------------------------------------------------------

def test_baseline_con_tres_actuaciones_sin_avisos(ruta):
    s = servicio_de(ruta)
    r = observar(s, 3)
    assert r == {"baseline": True, "novedades_nuevas": 0, "actuaciones": 3, "generacion": 1}
    assert pendientes(ruta) == () and s.novedades() == []
    caso = s.listar_casos()[0]
    assert caso["id"] == CASO_OBSERVADO and caso["total_actuaciones"] == 3 and caso["novedades_pendientes"] == 0


def test_cuarta_actuacion_produce_exactamente_una_novedad(ruta):
    s = servicio_de(ruta)
    observar(s, 3)
    r = observar(s, 4)
    assert r["baseline"] is False and r["novedades_nuevas"] == 1 and r["generacion"] == 2
    (novedad,) = s.novedades()
    assert novedad["caso"] == CASO_OBSERVADO and novedad["tipo"] == TipoCambio.PRIMERA_OBSERVACION.value
    assert novedad["actuacion"]["descripcion"] == "Actuación sintética número 4."
    assert novedad["prioridad"] == "alta"  # ASESOR-->ESTUDIANTE
    assert set(novedad) == {"id", "caso", "tipo", "prioridad", "titulo", "mensaje", "actuacion"}
    detalle = s.detalle(CASO_OBSERVADO)
    assert [a["nueva"] for a in detalle["actuaciones"]] == [False, False, False, True]
    assert detalle["total_actuaciones"] == 4 and detalle["novedades_pendientes"] == 1 and detalle["baseline"] is True


def test_repetir_la_segunda_observacion_no_agrega_novedades(ruta):
    s = servicio_de(ruta)
    observar(s, 3), observar(s, 4)
    for _ in range(3):
        assert observar(s, 4)["novedades_nuevas"] == 0
    assert len(s.novedades()) == 1 and len(pendientes(ruta)) == 1
    assert s.listar_casos()[0]["total_actuaciones"] == 4


def test_reinicio_conserva_baseline_actuaciones_y_avisos_sin_duplicar(ruta):
    observar(servicio_de(ruta), 3), observar(servicio_de(ruta), 4)
    reiniciado = servicio_de(ruta)  # instancia nueva sobre el mismo archivo = proceso reiniciado
    assert reiniciado.listar_casos()[0]["total_actuaciones"] == 4
    assert [a["nueva"] for a in reiniciado.detalle(CASO_OBSERVADO)["actuaciones"]] == [False, False, False, True]
    assert len(pendientes(ruta)) == 1
    assert observar(reiniciado, 4)["novedades_nuevas"] == 0
    assert len(pendientes(ruta)) == 1
    assert observar(reiniciado, 5)["novedades_nuevas"] == 1 and len(pendientes(ruta)) == 2


def test_el_escenario_completo_sobrevive_a_procesos_reales_separados(ruta):
    import json
    def correr(*args):
        r = subprocess.run([sys.executable, "-B", str(SCRIPT), "--db", str(ruta), *args], capture_output=True, text=True,
                           timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)
    assert correr("observar", "--actuaciones", "3")["baseline"] is True
    assert correr("observar", "--actuaciones", "4")["novedades_nuevas"] == 1
    assert correr("observar", "--actuaciones", "4")["novedades_nuevas"] == 0
    estado = correr("estado")
    assert estado["novedades_pendientes"] == 1 and estado["casos"][0]["total_actuaciones"] == 4


def test_consultar_no_marca_los_avisos_como_procesados(ruta):
    s = servicio_de(ruta)
    observar(s, 3), observar(s, 4)
    for _ in range(3):
        s.novedades(), s.detalle(CASO_OBSERVADO), s.listar_casos()
    assert len(pendientes(ruta)) == 1


def test_procesar_un_aviso_es_una_accion_explicita_y_no_reaparece(ruta):
    s = servicio_de(ruta)
    observar(s, 3), observar(s, 4)
    (aviso,) = pendientes(ruta)
    ServicioAvisos(AlmacenSqliteLocal(ruta)).procesar(CREDENCIAL_LOCAL, aviso.id, binding=BINDING_LOCAL)
    assert pendientes(ruta) == () and s.novedades() == []
    assert observar(s, 4)["novedades_nuevas"] == 0 and pendientes(ruta) == ()
    assert [a["nueva"] for a in s.detalle(CASO_OBSERVADO)["actuaciones"]] == [False] * 4


# --- Extracciones incompletas o rechazadas no crean baseline ----------------------------------------------

def test_una_primera_extraccion_rechazada_no_crea_baseline(ruta):
    s = servicio_de(ruta)
    malformado = html_historial_sintetico(3).replace('<tr><td colspan="2"><hr></td></tr>',
                                                     '<tr><td colspan="2"><hr><input type="hidden"></td></tr>', 1)
    with pytest.raises(ObservacionRechazada):
        s.observar_html(CASO_OBSERVADO, malformado)
    assert s.listar_casos() == []
    with pytest.raises(KeyError):
        s.detalle(CASO_OBSERVADO)
    assert observar(s, 3)["baseline"] is True  # el primer baseline válido sigue siendo el primero


@pytest.mark.parametrize("html", ["", "<html><body>nada</body></html>"])
def test_observacion_vacia_no_crea_baseline(ruta, html):
    s = servicio_de(ruta)
    with pytest.raises(ObservacionRechazada):
        s.observar_html(CASO_OBSERVADO, html)
    assert s.listar_casos() == []


def test_una_extraccion_rechazada_posterior_conserva_el_estado(ruta):
    s = servicio_de(ruta)
    observar(s, 3), observar(s, 4)
    antes = (s.listar_casos(), s.novedades(), s.detalle(CASO_OBSERVADO))
    malformado = html_historial_sintetico(5).replace('<tr><td colspan="2"><hr></td></tr>',
                                                     '<tr><td colspan="2"><hr><input type="hidden"></td></tr>', 1)
    with pytest.raises(ObservacionRechazada):
        s.observar_html(CASO_OBSERVADO, malformado)
    assert (s.listar_casos(), s.novedades(), s.detalle(CASO_OBSERVADO)) == antes


def test_una_observacion_con_menos_actuaciones_se_rechaza_como_incompleta(ruta):
    s = servicio_de(ruta)
    observar(s, 4)
    with pytest.raises(ObservacionRechazada):
        observar(s, 3)
    assert s.listar_casos()[0]["total_actuaciones"] == 4 and s.novedades() == []


def test_identificador_de_caso_invalido(ruta):
    with pytest.raises(ValueError):
        servicio_de(ruta).observar_html("no-es-uuid", html_historial_sintetico(1))


def test_el_html_no_se_guarda_en_el_archivo(ruta):
    observar(servicio_de(ruta), 3)
    contenido = ruta.read_bytes()
    for marca in (b"<table", b"<form", b"form1", b"<hr>"):
        assert marca not in contenido


# --- Reutilización: el estado equivale al del motor existente -----------------------------------------------

def test_el_estado_exportado_coincide_con_el_del_motor_de_reconciliacion(ruta):
    s = servicio_de(ruta)
    primera, segunda = (parse_actuaciones(html_historial_sintetico(n), CASO_OBSERVADO) for n in (3, 4))
    observar(s, 3), observar(s, 4)
    estado, _ = reconciliar(None, primera, caso=CASO_OBSERVADO, instancia="demo-local")
    siguiente, resultado = reconciliar(estado, segunda, caso=CASO_OBSERVADO, instancia="demo-local")
    exportado = s.seguimiento.estado(CREDENCIAL_LOCAL, binding=BINDING_LOCAL)
    guardados = exportado["cases"][CASO_OBSERVADO]["records"]
    assert sorted(r["version_hash"] for r in guardados) == sorted(r["version_hash"] for r in siguiente["records"])
    assert [r["status"] for r in guardados].count("primera_observacion") == [
        r["status"] for r in siguiente["records"]].count("primera_observacion") == 1
    assert len(resultado.eventos) == 1


# --- Adaptador: misma semántica que las funciones SQL -------------------------------------------------------------

def test_credencial_y_binding_locales_son_los_unicos_aceptados(ruta):
    almacen = AlmacenSqliteLocal(ruta)
    with pytest.raises(PermissionError):
        with almacen.transaccion("otra-credencial"):
            pass
    servicio = ServicioSeguimiento(almacen, instancia="demo-local")
    with pytest.raises(PermissionError):
        servicio.estado(CREDENCIAL_LOCAL, binding=uuid4())


def test_misma_clave_de_idempotencia_devuelve_el_recibo_sin_duplicar(ruta):
    almacen = AlmacenSqliteLocal(ruta)
    servicio = ServicioSeguimiento(almacen, instancia="demo-local")
    actuaciones = parse_actuaciones(html_historial_sintetico(3), CASO_OBSERVADO)
    clave = uuid4()
    primero = servicio.sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, actuaciones, clave=clave,
                                   worker=WORKER_LOCAL, binding=BINDING_LOCAL)
    segundo = servicio.sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, actuaciones, clave=clave,
                                   worker=WORKER_LOCAL, binding=BINDING_LOCAL)
    assert primero.repetido is False and segundo.repetido is True and segundo.generacion == primero.generacion == 1


def test_reserva_con_token_equivocado_o_generacion_vieja_no_confirma(ruta):
    almacen = AlmacenSqliteLocal(ruta)
    with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
        seguimiento = unidad.seguir("demo-local", CASO_OBSERVADO, "politica")
        reserva = unidad.reservar(seguimiento, uuid4(), WORKER_LOCAL, BINDING_LOCAL)
    from dataclasses import replace
    for mala in (replace(reserva, token=uuid4()), replace(reserva, generacion=7), replace(reserva, token=None)):
        with pytest.raises(ConflictoPersistenciaLocal):
            with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
                unidad.confirmar(mala, [], [], "politica")
    with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:  # la reserva original sigue vigente
        assert unidad.confirmar(reserva, [], [], "politica") == 1


def test_una_reserva_vencida_no_confirma(ruta):
    ahora = [1000.0]
    almacen = AlmacenSqliteLocal(ruta, reloj=lambda: ahora[0])
    with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
        reserva = unidad.reservar(unidad.seguir("demo-local", CASO_OBSERVADO, "p"), uuid4(), WORKER_LOCAL, BINDING_LOCAL)
    ahora[0] += 3600
    with pytest.raises(ConflictoPersistenciaLocal):
        with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
            unidad.confirmar(reserva, [], [], "p")


def test_no_se_eliminan_actuaciones_por_ausencia_ni_se_cambia_su_identidad(ruta):
    almacen = AlmacenSqliteLocal(ruta)
    registro = {"local_id": str(uuid4()), "source_id": None, "contract_ref": None, "origin_scope": None,
                "version_hash": "a" * 64, "status": "primera_observacion"}
    with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
        seg = unidad.seguir("demo-local", CASO_OBSERVADO, "p")
        unidad.confirmar(unidad.reservar(seg, uuid4(), WORKER_LOCAL, BINDING_LOCAL), [registro], [], "p")
    with pytest.raises(ValueError):
        with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
            seg = unidad.seguir("demo-local", CASO_OBSERVADO, "p")
            unidad.confirmar(unidad.reservar(seg, uuid4(), WORKER_LOCAL, BINDING_LOCAL), [], [], "p")
    with pytest.raises(ValueError):  # identidad persistente inmutable
        with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
            seg = unidad.seguir("demo-local", CASO_OBSERVADO, "p")
            unidad.confirmar(unidad.reservar(seg, uuid4(), WORKER_LOCAL, BINDING_LOCAL),
                             [{**registro, "source_id": "OTRO"}], [], "p")
    with pytest.raises(ValueError):  # evento sin registro asociado
        with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
            seg = unidad.seguir("demo-local", CASO_OBSERVADO, "p")
            unidad.confirmar(unidad.reservar(seg, uuid4(), WORKER_LOCAL, BINDING_LOCAL), [registro],
                             [{"local_id": str(uuid4()), "tipo": "primera_observacion", "prioridad": "normal"}], "p")
    with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:  # los fallos se revirtieron: queda el registro original
        guardado = unidad.leer_caso(unidad.seguir("demo-local", CASO_OBSERVADO, "p"), BINDING_LOCAL)
        assert [r["local_id"] for r in guardado["records"]] == [registro["local_id"]]
        assert guardado["records"][0]["source_id"] is None


def test_cambiar_la_politica_exige_transicion_explicita(ruta):
    almacen = AlmacenSqliteLocal(ruta)
    with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
        unidad.seguir("demo-local", CASO_OBSERVADO, "politica-1")
    with pytest.raises(ConflictoPersistenciaLocal):
        with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
            unidad.seguir("demo-local", CASO_OBSERVADO, "politica-2")


def test_una_transaccion_de_lectura_no_puede_escribir(ruta):
    almacen = AlmacenSqliteLocal(ruta)
    with pytest.raises(PermissionError):
        with almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
            unidad.seguir("demo-local", CASO_OBSERVADO, "p")


def test_un_fallo_dentro_de_la_transaccion_revierte_todo(ruta):
    almacen = AlmacenSqliteLocal(ruta)
    with pytest.raises(RuntimeError):
        with almacen.transaccion(CREDENCIAL_LOCAL) as unidad:
            unidad.seguir("demo-local", CASO_OBSERVADO, "p")
            raise RuntimeError("fallo_ficticio")
    with almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
        assert unidad.exportar("demo-local", BINDING_LOCAL) is None


def test_archivo_ilegible_o_esquema_incompatible_es_un_error_controlado(tmp_path):
    corrupto = tmp_path / "corrupto.sqlite3"
    corrupto.write_bytes(b"esto no es una base SQLite" * 50)
    with pytest.raises(AlmacenLocalNoDisponible):
        AlmacenSqliteLocal(corrupto)
    incompatible = tmp_path / "otro.sqlite3"
    AlmacenSqliteLocal(incompatible)
    import sqlite3
    c = sqlite3.connect(incompatible)
    c.execute("UPDATE meta SET valor='99' WHERE clave='esquema'"), c.commit(), c.close()
    with pytest.raises(AlmacenLocalNoDisponible):
        AlmacenSqliteLocal(incompatible)


# --- API de solo lectura --------------------------------------------------------------------------------------------

def cliente_de(servicio):
    push = ExpoPush(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    return TestClient(crear_app(ServicioDemo(("A" * 32, "B" * 32)), push, novedades=servicio))


def test_endpoints_de_consulta_reflejan_baseline_y_novedad(ruta):
    s = servicio_de(ruta)
    with cliente_de(s) as c:
        assert c.get("/demo/local/cases").json() == []
        assert c.get("/demo/local/novedades").json() == []
        observar(s, 3)
        assert c.get("/demo/local/novedades").json() == []
        assert c.get(f"/demo/local/cases/{CASO_OBSERVADO}").json()["novedades_pendientes"] == 0
        observar(s, 4)
        lista = c.get("/demo/local/cases").json()
        assert lista[0]["id"] == CASO_OBSERVADO and lista[0]["novedades_pendientes"] == 1
        detalle = c.get(f"/demo/local/cases/{CASO_OBSERVADO}").json()
        assert [a["nueva"] for a in detalle["actuaciones"]] == [False, False, False, True]
        (n,) = c.get("/demo/local/novedades").json()
        assert n["actuacion"]["descripcion"] == "Actuación sintética número 4."
        texto = c.get("/demo/local/novedades").text + c.get(f"/demo/local/cases/{CASO_OBSERVADO}").text
        # SQLite v2 vincula ocurrencias y eventos a identidades locales públicas.
        for a in detalle['actuaciones']:
            UUID(a['local_id'])
            assert a['generacion'] == detalle['generacion']
        for prohibido in ("huella", "version_hash", "source_id", "referencia"):
            assert prohibido not in texto


def test_consultar_por_la_api_nunca_procesa_los_avisos(ruta):
    s = servicio_de(ruta)
    observar(s, 3), observar(s, 4)
    with cliente_de(s) as c:
        for _ in range(3):
            c.get("/demo/local/novedades"), c.get(f"/demo/local/cases/{CASO_OBSERVADO}"), c.get("/demo/local/cases")
    assert len(pendientes(ruta)) == 1


def test_la_api_sigue_respondiendo_igual_tras_reiniciar_el_servicio(ruta):
    observar(servicio_de(ruta), 3), observar(servicio_de(ruta), 4)
    with cliente_de(servicio_de(ruta)) as c:  # servicio y almacén nuevos
        assert len(c.get("/demo/local/novedades").json()) == 1
        assert c.get(f"/demo/local/cases/{CASO_OBSERVADO}").json()["total_actuaciones"] == 4


def test_caso_inexistente_e_identificador_invalido(ruta):
    s = servicio_de(ruta)
    observar(s, 3)
    with cliente_de(s) as c:
        r = c.get(f"/demo/local/cases/{uuid4()}")
        assert r.status_code == 404 and r.json() == {"detail": "Proceso no disponible"}
        r = c.get("/demo/local/cases/no-es-uuid")
        assert r.status_code == 422 and r.json() == {"detail": "Entrada demo no valida"}


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("ruta_api", ["/demo/local/cases", f"/demo/local/cases/{CASO_OBSERVADO}", "/demo/local/novedades"])
def test_no_hay_endpoints_de_escritura(ruta, metodo, ruta_api):
    with cliente_de(servicio_de(ruta)) as c:
        assert getattr(c, metodo)(ruta_api).status_code == 405


def test_sin_persistencia_configurada_responde_503_generico(monkeypatch):
    monkeypatch.delenv("TINOTIFY_LOCAL_DB", raising=False)
    with cliente_de(None) as c:
        for ruta_api in ("/demo/local/cases", f"/demo/local/cases/{CASO_OBSERVADO}", "/demo/local/novedades"):
            r = c.get(ruta_api)
            assert r.status_code == 503 and r.json() == {"detail": "Persistencia local no configurada"}


def test_la_variable_de_entorno_activa_el_almacen_local(ruta, monkeypatch):
    observar(servicio_de(ruta), 3), observar(servicio_de(ruta), 4)
    monkeypatch.setenv("TINOTIFY_LOCAL_DB", str(ruta))
    with cliente_de(None) as c:
        assert len(c.get("/demo/local/novedades").json()) == 1


def test_un_fallo_del_almacen_es_503_controlado_sin_detalles(ruta, monkeypatch):
    s = servicio_de(ruta)
    def falla(*args, **kwargs):
        raise AlmacenLocalNoDisponible("detalle_interno_ficticio")
    monkeypatch.setattr(s, "listar_casos", falla)
    with cliente_de(s) as c:
        r = c.get("/demo/local/cases")
        assert r.status_code == 503 and "detalle_interno" not in r.text


def test_las_rutas_locales_son_solo_get_y_la_api_de_produccion_no_las_tiene():
    from tinotify.api import app
    assert not any(r.path.startswith("/demo") for r in app.routes)
    demo = crear_app(ServicioDemo(("A" * 32, "B" * 32)), ExpoPush(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    locales = [r for r in demo.routes if getattr(r, "path", "").startswith("/demo/local")]
    assert locales and all(r.methods == {"GET"} for r in locales)


def test_las_rutas_de_demo_y_catalogo_existentes_no_cambian():
    with cliente_de(None) as c:
        assert c.get("/health").json() == {"status": "ok"}
        assert c.get("/demo/cases").status_code == 401
        assert c.get("/demo/catalog/cases").status_code == 200
