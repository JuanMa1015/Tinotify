"""Feed de Novedades: fichas cifradas de cada actuación nueva, push y correo con el detalle. Todo ficticio."""

from collections import Counter
from types import SimpleNamespace

from backend.tests.test_expedientes_monitor import META, _plan_con
from backend.tests.test_monitor_real import Mundo, casos_base
from backend.tests.test_real_remoto import CAB
from tinotify.real_remoto import cifrado
from tinotify.real_remoto.monitor import _extracto, planificar, EstadoPrevio
from tinotify.real_remoto.servicio_monitor import _texto_push


def novedades(m):
    return m.c.get("/real/novedades", headers=CAB)


def _con_una_actuacion_nueva():
    casos = casos_base()
    m = Mundo(casos)
    m.guardar_credenciales()
    m.ejecutar()                                   # línea base: ninguna novedad
    casos[101] = list(casos[101]) + ["TEXTO_DE_LA_ACTUACION_NUEVA_FICTICIA"]
    m.ejecutar()
    return m


def test_sin_novedades_el_feed_esta_vacio_y_exige_token():
    m = Mundo(casos_base())
    m.guardar_credenciales()
    m.ejecutar()
    assert novedades(m).json() == {"novedades": []}
    assert m.c.get("/real/novedades").status_code == 401


def test_una_actuacion_nueva_aparece_en_el_feed_con_su_expediente_y_se_guarda_cifrada():
    m = _con_una_actuacion_nueva()
    filas = novedades(m).json()["novedades"]
    assert len(filas) == 1
    n = filas[0]
    assert n["numero"] == 101 and n["vista"] is False and n["resumen"] == "TEXTO_DE_LA_ACTUACION_NUEVA_FICTICIA"
    assert {"id", "expediente", "cliente", "detectada_en", "fecha", "etapa", "origen", "destino", "remitente", "anexos"} <= set(n)
    assert n["origen"] == "ASESOR" and n["destino"] == "ESTUDIANTE"
    brutos = b"".join(f["cifrado"] for f in m.almacen.__dict__["novedades_cifradas"])
    assert b"TEXTO_DE_LA_ACTUACION" not in brutos


def test_marcar_vistos_tambien_marca_sus_novedades_y_no_hay_novedades_en_la_linea_base():
    m = _con_una_actuacion_nueva()
    ref = novedades(m).json()["novedades"][0]["expediente"]
    assert m.c.post("/real/expedientes/vistos", headers=CAB, json={"id": ref}).status_code == 200
    assert novedades(m).json()["novedades"][0]["vista"] is True


def test_una_ficha_alterada_o_de_otro_expediente_no_se_muestra():
    m = _con_una_actuacion_nueva()
    m.almacen.__dict__["novedades_cifradas"][0]["cifrado"] = bytes(40)
    assert novedades(m).json() == {"novedades": []}


def test_el_cifrado_de_la_ficha_la_liga_a_su_expediente_y_rechaza_campos_extra():
    llave, ref, otra = b"k" * 32, "a" * 64, "b" * 64
    ficha = {"fecha": "2026-11-18T10:00:00", "etapa": "ETAPA_FICTICIA", "origen": "ASESOR", "destino": "ESTUDIANTE", "remitente": "R", "resumen": "X", "anexos": 0}
    nonce, c = cifrado.cifrar_novedad(llave, ref, ficha)
    assert cifrado.descifrar_novedad(llave, ref, nonce, c) == ficha
    for args in ((llave, otra, nonce, c), (b"z" * 32, ref, nonce, c)):
        try:
            cifrado.descifrar_novedad(*args)
        except cifrado.CifradoNoValido:
            continue
        raise AssertionError("debía rechazarse")
    try:
        cifrado.cifrar_novedad(llave, ref, {**ficha, "dato_extra": 1})
    except cifrado.CifradoNoValido:
        pass
    else:
        raise AssertionError("campos fuera de la lista blanca")


def test_planificar_entrega_las_huellas_nuevas():
    previo = {"r" * 64: EstadoPrevio(Counter({"h1": 1}))}
    plan = planificar(previo, {"r" * 64: Counter({"h1": 1, "h2": 2})})
    assert plan.cambios[0].nuevas == Counter({"h2": 2})


def test_el_extracto_resume_formularios_y_acorta_textos_largos():
    assert _extracto('TINOTIFY_FILAS_V1:{"filas":[["Hechos","Uno   dos"],["Estado","Aprobado"]]}') == "Hechos: Uno dos · Estado: Aprobado"
    largo = _extracto("palabra " * 100)
    assert len(largo) <= 240 and largo.endswith("…")
    assert _extracto("TINOTIFY_FILAS_V1:{roto") == "TINOTIFY_FILAS_V1:{roto"


def _cambio(ref, huellas):
    return SimpleNamespace(caso_ref=ref, accion="novedades", novedades=len(huellas), nuevas=Counter(huellas))


def test_el_push_dice_la_etapa_y_el_sentido_de_la_unica_actuacion_nueva():
    ref = "a" * 64
    fichas = {ref: {"h1": {"fecha": "2026-11-18T09:00:00", "etapa": "Aprobacion de informe", "origen": "ASESOR", "destino": "ESTUDIANTE"}}}
    texto, pestana, expediente = _texto_push(_plan_con([_cambio(ref, ["h1"])]), META, fichas)
    assert texto == "1 actuación nueva en el radicado 91256: Aprobacion de informe (ASESOR → ESTUDIANTE)"
    assert (pestana, expediente) == ("casos", ref)
    # sin fichas conserva el texto de siempre; con varias actuaciones usa la más reciente
    assert _texto_push(_plan_con([_cambio(ref, ["h1"])]), META)[0] == "1 actuación nueva en el radicado 91256"
    fichas[ref]["h2"] = {"fecha": "2026-11-18T11:00:00", "etapa": "Segunda", "origen": "", "destino": ""}
    assert _texto_push(_plan_con([_cambio(ref, ["h1", "h2"])]), META, fichas)[0] == "2 actuaciones nuevas en el radicado 91256: Segunda"
