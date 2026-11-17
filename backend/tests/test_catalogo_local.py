"""Endpoints locales de solo lectura con datos sintéticos. Sin SIGAC, sin red, sin credenciales."""

import inspect
import socket
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

import tinotify.demo.catalogo as catalogo_modulo
from tinotify.api.demo import crear_app
from tinotify.demo.catalogo import CASO_UNA, CASO_VACIO, CASO_VARIAS, CatalogoSintetico
from tinotify.demo.push import ExpoPush
from tinotify.demo.servicio import ServicioDemo


CODIGOS = ("A" * 32, "B" * 32)
LISTA = "/demo/catalog/cases"


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("Estas pruebas no deben abrir conexiones")
    # No se bloquea socket.connect: en Windows asyncio crea su canal interno con un socketpair local.
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)


def cliente_de(catalogo=None):
    push = ExpoPush(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    return TestClient(crear_app(ServicioDemo(CODIGOS), push, catalogo))


@pytest.fixture
def cliente():
    with cliente_de() as c:
        yield c


def test_lista_de_casos_sinteticos_sin_credenciales(cliente):
    r = cliente.get(LISTA)
    assert r.status_code == 200
    casos = r.json()
    assert [c["id"] for c in casos] == [CASO_VARIAS, CASO_UNA, CASO_VACIO]
    assert [c["total_actuaciones"] for c in casos] == [3, 1, 0]
    assert all(set(c) == {"id", "titulo", "total_actuaciones", "demo"} and c["demo"] is True for c in casos)
    assert "set-cookie" not in r.headers


def test_actuaciones_de_un_caso_en_orden_cronologico(cliente):
    r = cliente.get(f"{LISTA}/{CASO_VARIAS}/actuaciones")
    assert r.status_code == 200
    datos = r.json()
    assert datos["id"] == CASO_VARIAS and datos["demo"] is True and datos["sintetico"] is True
    fechas = [a["fecha"] for a in datos["actuaciones"]]
    assert len(fechas) == 3 and fechas == sorted(fechas)
    for a in datos["actuaciones"]:
        assert set(a) == {"fecha", "direccion", "remitente", "descripcion", "anexos"}
    assert datos["actuaciones"][0]["direccion"] == "ESTUDIANTE-->ASESOR"


def test_anexos_solo_exponen_descripcion_y_marca_sin_enlace(cliente):
    anexos = [x for a in cliente.get(f"{LISTA}/{CASO_VARIAS}/actuaciones").json()["actuaciones"] for x in a["anexos"]]
    assert [x["sin_enlace"] for x in anexos] == [False, True]
    assert all(set(x) == {"descripcion", "sin_enlace"} for x in anexos)
    texto = cliente.get(f"{LISTA}/{CASO_VARIAS}/actuaciones").text
    for prohibido in ("descargarAnexo", "referencia", "huella", "codigo=", "archivo"):
        assert prohibido not in texto


def test_caso_sin_actuaciones_devuelve_lista_vacia(cliente):
    r = cliente.get(f"{LISTA}/{CASO_VACIO}/actuaciones")
    assert r.status_code == 200 and r.json()["actuaciones"] == []


def test_caso_inexistente_es_404_generico(cliente):
    r = cliente.get(f"{LISTA}/{uuid4()}/actuaciones")
    assert r.status_code == 404 and r.json() == {"detail": "Proceso no disponible"}


def test_un_caso_de_la_demo_con_sesion_no_aparece_en_el_catalogo():
    servicio = ServicioDemo(CODIGOS)
    push = ExpoPush(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with TestClient(crear_app(servicio, push)) as c:
        token = c.post("/demo/sessions", json={"codigo": CODIGOS[0]}).json()["token"]
        caso = c.get("/demo/cases", headers={"Authorization": "Bearer " + token}).json()[0]["id"]
        assert c.get(f"{LISTA}/{caso}/actuaciones").status_code == 404
        assert caso not in [x["id"] for x in c.get(LISTA).json()]


@pytest.mark.parametrize("ruta", ["no-es-uuid", "123", "00000000-0000-4000-8000-00000000000z", "%00"])
def test_identificador_invalido_es_422_generico(cliente, ruta):
    r = cliente.get(f"{LISTA}/{ruta}/actuaciones")
    assert r.status_code in (404, 422)
    if r.status_code == 422:
        assert r.json() == {"detail": "Entrada demo no valida"}


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("ruta", [LISTA, f"{LISTA}/{CASO_VARIAS}/actuaciones"])
def test_no_hay_endpoints_de_escritura(cliente, metodo, ruta):
    r = getattr(cliente, metodo)(ruta)
    assert r.status_code == 405


def test_catalogo_vacio_inyectado_devuelve_lista_vacia():
    with cliente_de(CatalogoSintetico({})) as c:
        r = c.get(LISTA)
        assert r.status_code == 200 and r.json() == []
        assert c.get(f"{LISTA}/{CASO_VARIAS}/actuaciones").status_code == 404


def test_las_respuestas_no_se_pueden_usar_para_alterar_el_catalogo():
    catalogo = CatalogoSintetico()
    primera = catalogo.actuaciones(CASO_VARIAS)
    primera["actuaciones"].clear()
    primera["titulo"] = "alterado"
    assert len(catalogo.actuaciones(CASO_VARIAS)["actuaciones"]) == 3
    assert catalogo.actuaciones(CASO_VARIAS)["titulo"] != "alterado"
    assert catalogo.listar() == catalogo.listar()


def test_el_catalogo_exige_identificadores_uuid():
    with pytest.raises(ValueError):
        CatalogoSintetico({"no-uuid": ("t", ())})


def test_el_catalogo_esta_separado_del_cliente_sigac_y_del_parser_real():
    fuente = inspect.getsource(catalogo_modulo)
    for prohibido in ("integrations", "sigac_client", "parsers", "httpx", "requests", "os.environ", "socket"):
        assert prohibido not in fuente


def test_la_api_de_produccion_sigue_separada_del_modo_demo():
    from tinotify.api import app
    rutas = {ruta.path for ruta in app.routes}
    assert "/health" in rutas
    assert not any(ruta.startswith("/demo") for ruta in rutas)


def test_health_y_rutas_demo_existentes_no_cambian(cliente):
    assert cliente.get("/health").json() == {"status": "ok"}
    assert cliente.get("/demo/cases").status_code == 401  # las rutas con sesión siguen exigiendo token
