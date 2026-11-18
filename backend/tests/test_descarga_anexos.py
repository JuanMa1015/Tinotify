"""Descarga de anexos a través del servidor: cliente SIGAC (transporte simulado), servicio y ruta. Datos ficticios; sin red ni SIGAC real."""

from datetime import datetime

import httpx
import pytest

from backend.tests.test_monitor_real import Mundo, casos_base
from backend.tests.test_real_remoto import CAB
from backend.tests.test_servicio_cuentas import AlmacenMemoria as CuentasMemoria
from tinotify.domain.actuaciones import Actuacion, Anexo
from tinotify.integrations.sigac import sigac_client
from tinotify.integrations.sigac.sigac_client import BASE_URL, SigacClient, SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial
import tinotify.real_remoto.servicio_monitor as modulo

REF = "general.descargarAnexo.con?codigo=CODIGO_FICTICIO"
PDF = b"%PDF-1.4 contenido ficticio"


def cliente(respuesta):
    return SigacClient(httpx.Client(base_url=BASE_URL, follow_redirects=False, transport=httpx.MockTransport(respuesta)))


def ok(contenido=PDF, tipo="application/pdf", cabeceras=None):
    return lambda p: httpx.Response(200, content=contenido, headers={"content-type": tipo, **(cabeceras or {})})


# --- Cliente SIGAC -------------------------------------------------------------------------------------------------

def test_descarga_el_archivo_con_su_tipo_y_nombre_sugerido():
    c = cliente(ok(cabeceras={"content-disposition": 'attachment; filename="informe ficticio.pdf"'}))
    assert c.descargar_anexo(REF) == (PDF, "application/pdf", "informe ficticio.pdf")
    assert cliente(ok()).descargar_anexo(REF)[2] is None


@pytest.mark.parametrize("ref", ["", "otra.ruta?codigo=X", "general.descargarAnexo.con", "general.descargarAnexo.con?x=1",
                                 "https://ajeno.example/general.descargarAnexo.con?codigo=X", "/general.descargarAnexo.con?codigo=X",
                                 "../general.descargarAnexo.con?codigo=X", "general.descargarAnexo.con?codigo=" + "A" * 500])
def test_solo_se_aceptan_referencias_de_anexo_y_nunca_se_llega_a_la_red(ref):
    llamadas = []
    c = cliente(lambda p: (llamadas.append(p), httpx.Response(200, content=PDF))[1])
    with pytest.raises(SigacClientError) as e:
        c.descargar_anexo(ref)
    assert e.value.codigo is CodigoHistorial.ANEXO_REFERENCIA_INVALIDA and llamadas == []


def test_html_redireccion_o_acceso_denegado_son_sesion_vencida_nunca_un_archivo():
    for r in (httpx.Response(200, content=b"<html>Ingreso</html>", headers={"content-type": "text/html; charset=utf-8"}),
              httpx.Response(302, headers={"location": "login"}), httpx.Response(401), httpx.Response(403)):
        with pytest.raises(SigacSessionExpired):
            cliente(lambda p, r=r: r).descargar_anexo(REF)


def test_otros_estados_vacio_y_exceso_de_tamano(monkeypatch):
    with pytest.raises(SigacClientError) as e:
        cliente(lambda p: httpx.Response(500)).descargar_anexo(REF)
    assert e.value.codigo is CodigoHistorial.HTTP_INVALIDO
    with pytest.raises(SigacClientError):
        cliente(ok(b"")).descargar_anexo(REF)
    monkeypatch.setattr(sigac_client, "MAX_DESCARGA_BYTES", 10)
    with pytest.raises(SigacClientError) as e:
        cliente(ok(b"x" * 11)).descargar_anexo(REF)
    assert e.value.codigo is CodigoHistorial.LIMITE_RESPUESTA


def test_un_fallo_de_red_no_filtra_la_url():
    def cae(p):
        raise httpx.ConnectError("sin red")
    with pytest.raises(SigacClientError) as e:
        cliente(cae).descargar_anexo(REF)
    assert e.value.codigo is CodigoHistorial.TRANSPORTE and "CODIGO_FICTICIO" not in str(e.value)


# --- Servicio y ruta -----------------------------------------------------------------------------------------------

def actuaciones_con_anexos():
    base = dict(etapa="Etapa", origen="ESTUDIANTE", destino="ASESOR", remitente="R", descripcion="D")
    return [Actuacion(fecha=datetime(2026, 1, 1), **base, anexos=(Anexo("Sin archivo", "", "", sin_enlace=True),)),
            Actuacion(fecha=datetime(2026, 2, 1), **base, anexos=(Anexo("Evidencia", "epm.png", REF),))]   # la más reciente va primero


@pytest.fixture
def mundo(monkeypatch):
    llamadas = []
    monkeypatch.setattr(modulo, "leer_un_expediente", lambda *a, **k: actuaciones_con_anexos())
    monkeypatch.setattr(modulo, "descargar_un_anexo", lambda cliente_, usuario, clave, **k: (llamadas.append(k["referencia"]) or (PDF, "application/pdf", None)))
    m = Mundo(casos_base(), cuentas=CuentasMemoria())
    m.guardar_credenciales()
    m.ejecutar()
    m.llamadas = llamadas
    m.ref = next(iter({f["numero"]: f["id"] for f in m.c.get("/real/expedientes", headers=CAB).json()["expedientes"]}.values()))
    return m


def url(m, i, j):
    return f"/real/expedientes/{m.ref}/actuaciones/{i}/anexos/{j}"


def test_se_descarga_el_anexo_que_el_usuario_ve_sin_exponer_la_referencia(mundo):
    r = mundo.c.get(f"/real/expedientes/{mundo.ref}/actuaciones", headers=CAB)
    anexos = [a for x in r.json()["actuaciones"] for a in x["anexos"]]
    assert [a["con_enlace"] for a in anexos] == [True, False] and "CODIGO_FICTICIO" not in r.text and "descargarAnexo" not in r.text
    d = mundo.c.get(url(mundo, 0, 0), headers=CAB)                              # la actuación más reciente, primer anexo
    assert d.status_code == 200 and d.content == PDF and d.headers["content-type"] == "application/pdf"
    assert d.headers["content-disposition"] == 'attachment; filename="epm.png"' and mundo.llamadas == [REF]


def test_no_hay_descarga_sin_abrir_el_expediente_ni_para_anexos_sin_enlace_o_inexistentes(mundo):
    assert mundo.c.get(url(mundo, 0, 0), headers=CAB).status_code == 404            # aún no se abrió el expediente
    mundo.c.get(f"/real/expedientes/{mundo.ref}/actuaciones", headers=CAB)
    for i, j in ((1, 0), (0, 5), (9, 0)):                                            # sin enlace, anexo y actuación inexistentes
        assert mundo.c.get(url(mundo, i, j), headers=CAB).status_code == 404
    assert mundo.llamadas == []


def test_exige_el_token_valida_los_indices_y_no_cruza_cuentas(mundo):
    mundo.c.get(f"/real/expedientes/{mundo.ref}/actuaciones", headers=CAB)
    assert mundo.c.get(url(mundo, 0, 0)).status_code == 401
    assert mundo.c.get(f"/real/expedientes/{mundo.ref}/actuaciones/-1/anexos/0", headers=CAB).status_code == 422
    assert mundo.c.get(f"/real/expedientes/no-es-un-id/actuaciones/0/anexos/0", headers=CAB).status_code == 422
    inv = mundo.c.post("/auth/invitaciones", headers=CAB).json()["codigo"]
    t = mundo.c.post("/auth/registro", json={"correo": "a@ejemplo.com", "clave": "una-clave-ficticia-1", "invitacion": inv,
                                             "consentimiento": "consentimiento-v1"}).json()["token"]
    assert mundo.c.get(url(mundo, 0, 0), headers={"Authorization": f"Bearer {t}"}).status_code == 404   # no ve el expediente de otra cuenta


def test_el_nombre_del_archivo_se_sanea_en_la_cabecera(mundo, monkeypatch):
    monkeypatch.setattr(modulo, "descargar_un_anexo", lambda *a, **k: (PDF, "application/pdf", 'raro"\r\nX-Inyeccion: 1/../a.pdf'))
    mundo.c.get(f"/real/expedientes/{mundo.ref}/actuaciones", headers=CAB)
    d = mundo.c.get(url(mundo, 0, 0), headers=CAB)
    assert "\r" not in d.headers["content-disposition"] and "x-inyeccion" not in d.headers and "/" not in d.headers["content-disposition"]


def test_los_errores_de_sigac_se_traducen_y_no_se_filtran_datos(mundo, monkeypatch):
    def vence(*a, **k):
        raise SigacSessionExpired("vencida", codigo=CodigoHistorial.SESION_NO_CONFIRMADA)
    monkeypatch.setattr(modulo, "descargar_un_anexo", vence)
    mundo.c.get(f"/real/expedientes/{mundo.ref}/actuaciones", headers=CAB)
    r = mundo.c.get(url(mundo, 0, 0), headers=CAB)
    assert r.status_code >= 400 and "CODIGO_FICTICIO" not in r.text
