"""Nombre de la persona en SIGAC (banner) para el saludo de la app. Todo ficticio."""

from backend.tests.test_monitor_real import Mundo, casos_base
from backend.tests.test_real_remoto import CAB
from tinotify.integrations.sigac.sigac_perfil import extraer_nombre


def test_el_extractor_acepta_un_nombre_unico_y_rechaza_lo_dudoso():
    caja = lambda *spans: "<html><body>" + "".join(spans) + "</body></html>"  # noqa: E731
    assert extraer_nombre(caja('<span class="nombre">  ANA   MARIA\n LOPEZ </span>')) == "ANA MARIA LOPEZ"
    assert extraer_nombre(caja('<span class="nombre">Ñandú Pérez</span>')) == "Ñandú Pérez"
    for dudoso in (caja(), caja('<span class="nombre">A</span>'), caja('<span class="nombre">X1 Y2</span>'),
                   caja('<span class="nombre">Uno</span><span class="nombre">Dos</span>'), caja('<span class="nombre"><b>x</b>&lt;script&gt;</span>'), None):
        assert extraer_nombre(dudoso) is None


def test_el_perfil_exige_token_y_credenciales_guardadas():
    m = Mundo(casos_base())
    assert m.c.get("/real/perfil").status_code == 401
    assert m.c.get("/real/perfil", headers=CAB).status_code == 412


def test_el_perfil_devuelve_el_nombre_lo_pide_a_sigac_una_sola_vez_y_no_lo_guarda():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    antes = m.sim.logins
    assert m.c.get("/real/perfil", headers=CAB).json() == {"nombre": "MARIA FICTICIA PEREZ DIAZ"}
    assert m.c.get("/real/perfil", headers=CAB).json() == {"nombre": "MARIA FICTICIA PEREZ DIAZ"}
    assert m.sim.logins == antes + 1                                   # la segunda vez sale de la memoria del servidor
    assert "FICTICIA" not in repr(m.almacen.__dict__)                  # el nombre no llega al almacén


def test_si_el_banner_falla_el_nombre_es_nulo_y_no_es_un_error():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    m.sim.sin_banner = True
    r = m.c.get("/real/perfil", headers=CAB)
    assert r.status_code == 200 and r.json() == {"nombre": None}
