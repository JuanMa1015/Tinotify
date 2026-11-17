"""Huellas golden de casos previamente válidos, capturadas con el código ANTERIOR a `sin_enlace`.

Todos los datos son sintéticos. Si alguno de estos valores cambia, la representación
versionada dejó de ser compatible con los estados ya guardados (VERSION_HUELLA = 1).
"""

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import unicodedata

import pytest

from tinotify.domain.actuaciones import VERSION_HUELLA, Actuacion, Anexo
from tinotify.parsers.parser import parse_actuaciones, ErrorParseoHistorial
from tinotify.parsers.diagnostico_historial import CodigoHistorial


FIXTURES = Path(__file__).parent / "fixtures"
BASE = Actuacion("ETAPA FICTICIA", "ASESOR", "ESTUDIANTE", datetime(2020, 1, 1, 10),
                 "REMITENTE FICTICIO", "DESCRIPCIÓN FICTICIA")
A1 = Anexo("ANEXO FICTICIO", "archivo_ficticio.txt", "general.descargarAnexo.con?codigo=FICTICIO")
A2 = replace(A1, archivo="segundo_ficticio.txt")
# Archivo vacío pero con referencia: ya era válido y debe conservar su huella.
A3 = Anexo("ANEXO SIN ARCHIVO FICTICIO", "", "general.descargarAnexo.con?codigo=OTRO")

GOLDEN = {
    "sin_anexos": (BASE, "04e01e2daa6ac3fae252e896d15fc45bc004c4c5ff1514b168f5429451c6dac4"),
    "un_anexo": (replace(BASE, anexos=(A1,)), "6d8c72534d5810abb244f682081d7020b05504b8c4f54ad0321269a94a90aa62"),
    "dos_anexos": (replace(BASE, anexos=(A1, A2)), "a84a1a628e192ea92e3d6e1983a1b17e3243ed8ef66e7466df21f914d6ebd49a"),
    "dos_anexos_invertidos": (replace(BASE, anexos=(A2, A1)), "a84a1a628e192ea92e3d6e1983a1b17e3243ed8ef66e7466df21f914d6ebd49a"),
    "anexo_duplicado": (replace(BASE, anexos=(A1, A1)), "1a1c963d35e13541a4e5f12e68721cba2557159d4d1185d2d424469933461753"),
    "archivo_vacio_con_referencia": (replace(BASE, anexos=(A3,)), "d15dc4271b887f2768aa21e11a6d3792310b7248f76a6e71ce73dcbaac70554a"),
    "unicode_nfd": (replace(BASE, anexos=(replace(A1, descripcion=unicodedata.normalize("NFD", "Revisión ficticia")),)),
                    "21c0c4f2fa00309796fe64b5ba0b50348564cc18b71a7ae64abd3e261b3ba801"),
}

GOLDEN_FIXTURES = {
    "caso_prueba.html": ("219c139644c6d27e93032ccee43647bf23b6ffb91f364df68d13664327c92c39",),
    "historial_dom_sintetico.html": (
        "d06c04f612a9116e3d1c3255f9d4d5318295b7ac68971dad5da1446d86771eb4",
        "003b209bbb0aaf3b26b563704f1c3a89e8e93cc12123e8bae62aed22011bf795",
        "de0be1e8c5de7f0d2b83891b6a5edfada75eede7ce2a36d63c995e5a73d621ee",
    ),
}


def test_version_de_huella_no_cambia():
    assert VERSION_HUELLA == 1


@pytest.mark.parametrize("actuacion,esperada", GOLDEN.values(), ids=GOLDEN.keys())
def test_huellas_de_anexos_normales_son_identicas_a_las_anteriores(actuacion, esperada):
    assert actuacion.huella_version == esperada


@pytest.mark.parametrize("nombre", GOLDEN_FIXTURES)
def test_fixtures_golden_conservan_huella_o_rechazan_la_historia_anidada_ambigua(nombre):
    html = (FIXTURES / nombre).read_text(encoding="utf-8")
    contexto = {"contenedor_id": "historial_ficticio"} if nombre == "historial_dom_sintetico.html" else {}
    if nombre == "historial_dom_sintetico.html":
        # Sus hashes históricos se mantienen como referencia, sin recalcularlos.
        # Contiene la misma historia anidada que motivó la corrección: el lote
        # debe rechazarse; no emitir otra huella para legitimar esa ambigüedad.
        with pytest.raises(ErrorParseoHistorial) as error:
            parse_actuaciones(html, "CASO_FICTICIO", **contexto)
        assert error.value.codigo is CodigoHistorial.AMBITO_NO_VERIFICADO
        return
    obtenidas = tuple(a.huella_version for a in parse_actuaciones(html, "CASO_FICTICIO", **contexto))
    assert obtenidas == GOLDEN_FIXTURES[nombre]


# --- Representación del anexo sin enlace -------------------------------------------------

SIN = Anexo("ANEXO DESCRIPTIVO FICTICIO", "", "", sin_enlace=True)


def test_huellas_golden_de_anexos_sin_enlace():
    assert replace(BASE, anexos=(SIN,)).huella_version == "d37087b6769a91b0b6aa21f6e15617f98a5653666e424495a8241c624a8889ae"
    assert replace(BASE, anexos=(SIN, SIN)).huella_version == "28366df93b386b946c39c51e5becaa36191a5ab688c57e63ea3c8071222042a1"


def test_la_representacion_sin_enlace_es_inequivoca():
    # Misma descripción y campos vacíos o con referencia: nunca coinciden con la marca.
    con_referencia = Anexo("ANEXO DESCRIPTIVO FICTICIO", "", "x")
    assert replace(BASE, anexos=(SIN,)).huella_version != replace(BASE, anexos=(con_referencia,)).huella_version
    assert replace(BASE, anexos=(SIN,)).huella_version != BASE.huella_version
    assert replace(BASE, anexos=(SIN,)).contenido_versionado()["anexos"] == [
        {"descripcion": "ANEXO DESCRIPTIVO FICTICIO", "archivo": "", "referencia": "", "sin_enlace": True}]


def test_anexos_normales_conservan_exactamente_tres_claves_en_el_contenido_versionado():
    for _, (actuacion, _) in GOLDEN.items():
        for anexo in actuacion.contenido_versionado()["anexos"]:
            assert set(anexo) == {"descripcion", "archivo", "referencia"}


def test_orden_no_afecta_y_duplicados_si_con_anexos_sin_enlace():
    assert replace(BASE, anexos=(SIN, A1)).huella_version == replace(BASE, anexos=(A1, SIN)).huella_version
    assert replace(BASE, anexos=(SIN, SIN, A1)).huella_version != replace(BASE, anexos=(SIN, A1)).huella_version


def test_transicion_de_sin_enlace_a_con_enlace_cambia_la_huella():
    con = Anexo(SIN.descripcion, "archivo_ficticio.pdf", "general.descargarAnexo.con?codigo=FICTICIO")
    assert replace(BASE, anexos=(SIN,)).huella_version != replace(BASE, anexos=(con,)).huella_version
