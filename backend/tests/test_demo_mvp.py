"""Recorrido demo con Expo simulado; ninguna prueba acredita un telefono real."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from tinotify.api.demo import crear_app
from tinotify.demo.push import ExpoPush
from tinotify.demo.servicio import ServicioDemo
from tinotify.demo.sigac_simulado import SigacSimulado


CODIGOS = ("A"*32, "B"*32)
TOKEN = "ExpoPushToken[dispositivo_ficticio]"


@pytest.fixture
def demo():
    llamadas = []

    def proveedor(request):
        import json
        llamadas.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("send"):
            return httpx.Response(200, json={"data": {"status": "ok", "id": "ticket-ficticio"}})
        return httpx.Response(200, json={"data": {"ticket-ficticio": {"status": "ok"}}})

    servicio = ServicioDemo(CODIGOS)
    push = ExpoPush(transport=httpx.MockTransport(proveedor))
    with TestClient(crear_app(servicio, push)) as cliente:
        yield cliente, servicio, llamadas


def acceso(cliente, codigo=CODIGOS[0]):
    r = cliente.post("/demo/sessions", json={"codigo": codigo})
    assert r.status_code == 200
    headers = {"Authorization": "Bearer " + r.json()["token"]}
    caso = cliente.get("/demo/cases", headers=headers).json()[0]["id"]
    return headers, caso


def agregar(cliente, headers, caso, solicitud=None):
    return cliente.post(f"/demo/cases/{caso}/actuaciones", headers=headers,
                        json={"solicitud": solicitud or str(uuid4())})


def test_recorrido_baseline_novedad_push_y_apertura_autorizada(demo):
    cliente, _, llamadas = demo
    headers, caso = acceso(cliente)
    assert cliente.post(f"/demo/cases/{caso}/sync", headers=headers).json()["avisos"] == []
    assert cliente.post("/demo/device", headers=headers, json={"token": TOKEN}).status_code == 204
    solicitud = str(uuid4())
    nueva = agregar(cliente, headers, caso, solicitud)
    assert nueva.status_code == 200
    assert len(nueva.json()["historial"]) == 2
    assert nueva.json()["avisos"][0]["estado"] == "aceptado_expo"
    assert nueva.json()["avisos"][0]["prioridad"] == "alta"
    agregar(cliente, headers, caso, solicitud)
    cliente.post(f"/demo/cases/{caso}/sync", headers=headers)
    assert len(llamadas) == 1
    contenido = llamadas[0][1]
    assert contenido["data"]["caseId"] == caso and contenido["data"]["demo"] is True
    assert "sintetica numero" not in contenido["body"]
    assert cliente.get(f'/demo/cases/{contenido["data"]["caseId"]}', headers=headers).status_code == 200
    cliente.post("/demo/push/receipts", headers=headers)
    assert cliente.get(f"/demo/cases/{caso}", headers=headers).json()["avisos"][0]["estado"] == "aceptado_fcm"


def test_aislamiento_autorizacion_y_validacion_sin_secretos(demo):
    cliente, _, llamadas = demo
    a, caso_a = acceso(cliente)
    b, caso_b = acceso(cliente, CODIGOS[1])
    assert agregar(cliente, {}, caso_a).status_code == 401
    assert agregar(cliente, b, caso_a).status_code == 404
    assert cliente.get(f"/demo/cases/{caso_b}", headers=a).status_code == 404
    assert cliente.post("/demo/sessions", json={"codigo": "C"*32}).status_code == 401
    secreto_ficticio = "entrada_ficticia_que_no_debe_reflejarse"
    r = cliente.post("/demo/device", headers=a, json={"token": secreto_ficticio})
    assert r.status_code == 422 and secreto_ficticio not in r.text
    assert cliente.get(f"/demo/cases/{caso_a}", headers=a).json()["avisos"] == []
    assert not llamadas


def test_fallo_del_origen_conserva_estado_y_vista(demo, monkeypatch):
    cliente, servicio, llamadas = demo
    headers, caso = acceso(cliente)
    anterior = cliente.post(f"/demo/cases/{caso}/sync", headers=headers).json()

    def fallo(_):
        raise ConnectionError

    monkeypatch.setattr(servicio._origen, "observar", fallo)
    assert cliente.post(f"/demo/cases/{caso}/sync", headers=headers).status_code == 503
    assert cliente.get(f"/demo/cases/{caso}", headers=headers).json() == anterior
    assert not llamadas


@pytest.mark.parametrize("error,estado,reenvios",[
    (httpx.ConnectError("fallo ficticio"), "reintentable", 2),
    (httpx.ReadTimeout("respuesta perdida ficticia"), "incierto", 1),
])
def test_fallo_push_no_borra_evento_ni_repite_envios_inciertos(error, estado, reenvios):
    intentos = []

    def proveedor(_):
        intentos.append(1)
        if len(intentos) == 1:
            raise error
        return httpx.Response(200, json={"data": {"status": "ok", "id": "ticket-ficticio"}})

    with TestClient(crear_app(ServicioDemo(CODIGOS), ExpoPush(transport=httpx.MockTransport(proveedor)))) as cliente:
        headers, caso = acceso(cliente)
        cliente.post("/demo/device", headers=headers, json={"token": TOKEN})
        primera = agregar(cliente, headers, caso).json()
        assert primera["avisos"][0]["estado"] == estado
        siguiente = cliente.post(f"/demo/cases/{caso}/sync", headers=headers).json()
        assert siguiente["historial"] == primera["historial"]
        assert len(siguiente["avisos"]) == 1 and len(intentos) == reenvios


def test_dispositivo_no_se_comparte_y_logout_revoca_sesion(demo):
    cliente, _, _ = demo
    a, _ = acceso(cliente)
    b, _ = acceso(cliente, CODIGOS[1])
    assert cliente.post("/demo/device", headers=a, json={"token": TOKEN}).status_code == 204
    assert cliente.post("/demo/device", headers=b, json={"token": TOKEN}).status_code == 409
    assert cliente.delete("/demo/session", headers=a).status_code == 204
    assert cliente.get("/demo/cases", headers=a).status_code == 401
    assert cliente.post("/demo/device", headers=b, json={"token": TOKEN}).status_code == 204


def test_caducidad_y_generacion_concurrente_idempotente():
    tiempo = [0]
    servicio = ServicioDemo(CODIGOS, reloj=lambda: tiempo[0])
    token = servicio.ingresar(CODIGOS[0])
    caso = servicio.listar(token)[0]["id"]
    solicitud = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(lambda _: servicio.agregar(token, caso, solicitud), range(2)))
    vista = servicio.detalle(token, caso)
    assert len(vista["historial"]) == 2 and len(vista["avisos"]) == 1
    tiempo[0] = 3601
    from tinotify.demo.servicio import AccesoDemo
    with pytest.raises(AccesoDemo): servicio.listar(token)


def test_demo_no_se_activa_por_defecto(monkeypatch):
    monkeypatch.delenv("TINOTIFY_MODE", raising=False)
    with pytest.raises(RuntimeError): crear_app()
    with pytest.raises(ValueError): ServicioDemo(["corto", "corto"])


def test_origen_simulado_no_inventa_identidad_estable():
    origen = SigacSimulado()
    origen.crear("caso-ficticio")
    assert origen.observar("caso-ficticio")[0].identificador_origen is None
