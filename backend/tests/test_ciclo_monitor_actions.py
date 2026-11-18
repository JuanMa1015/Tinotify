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


def servicio(avisos, ejecutar=200, entregado=200, usuarios=None):
    llamadas = []

    def h(p):
        llamadas.append((p.method, p.url.path + (("?" + p.url.query.decode()) if p.url.query else "")))
        if p.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if p.url.path == "/real/monitor/ejecutar":
            return httpx.Response(ejecutar, json={})
        if p.url.path == "/real/monitor/usuarios":
            return httpx.Response(404, json={}) if usuarios is None else httpx.Response(200, json={"propietario": True, "usuarios": usuarios})
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


def test_la_revision_fallida_se_reporta_pero_no_impide_enviar_los_avisos_pendientes(capsys):
    c, llamadas = servicio([AVISO], ejecutar=502)
    enviados = []
    assert ciclo.main(ENV, enviar=lambda m, u, k: enviados.append(m), cliente=c) == 3    # termina con error, pero...
    assert len(enviados) == 1 and any(p.endswith("/entregado") for _, p in llamadas)     # ...no deja de avisar lo ya pendiente
    assert "revision_http_502" in capsys.readouterr().out


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


UID_A, UID_B = "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002"


def test_revisa_a_cada_usuario_por_separado_y_un_fallo_no_detiene_a_los_demas(capsys):
    c, llamadas = servicio([], usuarios=[UID_A, UID_B])
    assert ciclo.main(ENV, cliente=c) == 0
    revisadas = [p for m, p in llamadas if p.startswith("/real/monitor/ejecutar")]
    assert revisadas == ["/real/monitor/ejecutar", f"/real/monitor/ejecutar?usuario={UID_A}", f"/real/monitor/ejecutar?usuario={UID_B}"]
    assert UID_A not in capsys.readouterr().out                                          # el registro público no lleva identificadores


def test_el_fallo_de_un_usuario_no_corta_el_ciclo(capsys):
    def h(p):
        if p.url.path == "/health":
            return httpx.Response(200, json={})
        if p.url.path == "/real/monitor/usuarios":
            return httpx.Response(200, json={"usuarios": [UID_A, UID_B]})
        if p.url.path == "/real/monitor/ejecutar":
            return httpx.Response(502 if p.url.params.get("usuario") == UID_A else 200, json={})
        return httpx.Response(200, json={"avisos": []})
    c = httpx.Client(base_url="https://x.example", transport=httpx.MockTransport(h))
    assert ciclo.main(ENV, cliente=c) == 3
    salida = capsys.readouterr().out
    assert "revision_usuario_http_502" in salida and UID_A not in salida


def test_cada_aviso_va_a_su_propio_correo_y_sin_destino_se_marca_desactivado():
    de_usuario = dict(AVISO, id="22222222-2222-2222-2222-222222222222", usuario=UID_A, destino="otra@ejemplo.com")
    sin_correo = dict(AVISO, id="33333333-3333-3333-3333-333333333333", usuario=UID_B)
    c, llamadas = servicio([AVISO, de_usuario, sin_correo])
    enviados = []
    assert ciclo.main(ENV, enviar=lambda m, u, k: enviados.append(m["To"]), cliente=c) == 0
    assert enviados == ["d@example.com", "otra@ejemplo.com"]                              # propietario con su secreto; usuario con el suyo
    assert ("POST", f"/real/monitor/avisos/{sin_correo['id']}/canal") in llamadas            # sin correo: queda anotado, no se envía
    assert ("POST", f"/real/monitor/avisos/{sin_correo['id']}/entregado") in llamadas               # y no queda pendiente para siempre
    assert "d@example.com" not in [e for e in enviados if e != "d@example.com"]                      # el correo del propietario no recibe avisos ajenos
    assert enviados.count("d@example.com") == 1


def test_un_envio_fallido_no_impide_enviar_los_demas():
    otro = dict(AVISO, id="44444444-4444-4444-4444-444444444444", usuario=UID_A, destino="otra@ejemplo.com")
    c, llamadas = servicio([AVISO, otro])
    intentos = []

    def a_medias(m, u, k):
        intentos.append(m["To"])
        if m["To"] == "d@example.com":
            raise smtplib.SMTPException
    assert ciclo.main(ENV, enviar=a_medias, cliente=c) == 4
    assert intentos == ["d@example.com", "otra@ejemplo.com"]
    assert any(p == f"/real/monitor/avisos/{otro['id']}/entregado" for _, p in llamadas)
    assert not any(p == f"/real/monitor/avisos/{AVISO['id']}/entregado" for _, p in llamadas)
