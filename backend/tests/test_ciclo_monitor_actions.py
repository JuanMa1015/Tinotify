"""Ciclo de Actions con servicio simulado (sin red, sin SMTP real)."""

import importlib.util
from pathlib import Path
import smtplib

import httpx

ruta = Path(__file__).resolve().parents[1] / "scripts" / "ciclo_monitor_actions.py"
spec = importlib.util.spec_from_file_location("ciclo_t", ruta)
ciclo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ciclo)

AVISO = {"id": "11111111-1111-1111-1111-111111111111", "novedades": 2, "expedientes_con_novedades": 1,
         "expedientes_nuevos": 0, "anomalias": 0, "intentos": 0}
ENV = {"TINOTIFY_URL": "https://x.example", "TINOTIFY_MONITOR_TOKEN": "tok", "TINOTIFY_CORREO_ACTIVO": "1",
       "TINOTIFY_CORREO_DESTINO": "d@example.com", "TINOTIFY_SMTP_USUARIO": "u@example.com", "TINOTIFY_SMTP_CLAVE": "c"}


def servicio(avisos, ejecutar=200, entregado=200):
    llamadas = []

    def h(p):
        llamadas.append((p.method, p.url.path))
        if p.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if p.url.path == "/real/monitor/ejecutar":
            return httpx.Response(ejecutar, json={})
        if p.url.path == "/real/monitor/avisos":
            return httpx.Response(200, json={"avisos": avisos})
        return httpx.Response(200 if p.url.path.endswith('/canal') else entregado, json={})
    return httpx.Client(base_url="https://x.example", transport=httpx.MockTransport(h)), llamadas


def test_configuracion_incompleta():
    assert ciclo.main({"TINOTIFY_URL": "http://x"}) == 2


def test_sin_avisos_no_envia(capsys):
    c, _ = servicio([])
    assert ciclo.main(ENV, enviar=lambda *a: (_ for _ in ()).throw(AssertionError), cliente=c) == 0
    assert capsys.readouterr().out.strip() == "ok: sin_avisos"


def test_correo_desactivado_deja_el_aviso_pendiente():
    c, llamadas = servicio([AVISO])
    assert ciclo.main({**ENV, "TINOTIFY_CORREO_ACTIVO": "0"}, enviar=lambda *a: (_ for _ in ()).throw(AssertionError), cliente=c) == 0
    assert not any(p.endswith("/entregado") for _, p in llamadas)


def test_envia_y_confirma(capsys):
    c, llamadas = servicio([AVISO])
    enviados = []
    assert ciclo.main(ENV, enviar=lambda m, u, k: enviados.append(m), cliente=c) == 0
    assert len(enviados) == 1 and enviados[0]["To"] == "d@example.com"
    assert "2 actuación(es)" in enviados[0].get_content()
    assert ("POST", f"/real/monitor/avisos/{AVISO['id']}/entregado") in llamadas
    salida = capsys.readouterr().out
    assert salida.strip() == "ok: avisos_enviados" and "2" not in salida


def test_si_falla_el_correo_no_confirma():
    c, llamadas = servicio([AVISO])

    def falla(*a):
        raise smtplib.SMTPException
    assert ciclo.main(ENV, enviar=falla, cliente=c) == 4
    assert not any(p.endswith("/entregado") for _, p in llamadas)


def test_revision_fallida_no_sigue():
    c, llamadas = servicio([AVISO], ejecutar=502)
    assert ciclo.main(ENV, enviar=lambda *a: None, cliente=c) == 3
    assert not any(p.endswith("/avisos") for _, p in llamadas)


def test_informa_al_servidor_como_salio_el_correo():
    c, llamadas = servicio([AVISO])
    assert ciclo.main(ENV, enviar=lambda m, u, k: None, cliente=c) == 0
    assert ("POST", f"/real/monitor/avisos/{AVISO['id']}/canal") in llamadas
    c, llamadas = servicio([AVISO])

    def falla(*a):
        raise smtplib.SMTPException
    assert ciclo.main(ENV, enviar=falla, cliente=c) == 4
    assert ("POST", f"/real/monitor/avisos/{AVISO['id']}/canal") in llamadas
    c, llamadas = servicio([AVISO])
    assert ciclo.main({**ENV, "TINOTIFY_CORREO_ACTIVO": "0"}, cliente=c) == 0
    assert ("POST", f"/real/monitor/avisos/{AVISO['id']}/canal") in llamadas
