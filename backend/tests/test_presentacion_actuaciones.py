"""Presentación legible de descripciones multi-fila. Solo fixtures ficticios; la huella no cambia."""

from datetime import datetime
import json

import pytest

from backend.tests.test_parser_historial import documento_con_presentacion, parsear
from tinotify.domain.actuaciones import Actuacion
from tinotify.parsers.parser import PREFIJO_FILAS
from tinotify.parsers.presentacion import TEXTO_ERROR, TITULO_ERROR, presentar, secciones, vista_previa
from tinotify.services.historial_temporal import HistorialTemporal, construir_items
from tinotify.services.consulta_real_local import caso_local


def con_descripcion(descripcion):
    return Actuacion("E", "O", "D", datetime(2020, 1, 1, 10), "R", descripcion)


def canonica(filas, version=1):
    return PREFIJO_FILAS + json.dumps({"parser_content_version": version, "filas": filas}, ensure_ascii=False,
                                      sort_keys=True, separators=(",", ":"))


def test_las_filas_se_muestran_como_titulos_y_parrafos_con_sus_saltos_de_linea():
    descripcion = canonica([["Actuación", "LINEA_A\nLINEA_B"], ["Reparto", "PARRAFO"], ["Campo ficticio", ""]])
    partes, legible, inesperado = presentar(descripcion)
    assert inesperado is False
    assert partes == [{"titulo": "Actuación", "texto": "LINEA_A\nLINEA_B"}, {"titulo": "Reparto", "texto": "PARRAFO"},
                      {"titulo": "Campo ficticio", "texto": ""}]
    assert legible == "Actuación\nLINEA_A\nLINEA_B\n\nReparto\nPARRAFO\n\nCampo ficticio"
    assert "TINOTIFY" not in legible and "{" not in legible and "parser_content_version" not in legible


def test_una_descripcion_simple_se_conserva_tal_cual():
    partes, legible, inesperado = presentar("Texto simple\ncon salto")
    assert legible == "Texto simple\ncon salto" and inesperado is False and partes[0]["titulo"] == "Actuación"


@pytest.mark.parametrize("descripcion", [
    PREFIJO_FILAS + "no es json", PREFIJO_FILAS + "[]", PREFIJO_FILAS + '{"filas":[["A","B"]]}',
    canonica([["A", "B"]], version=2), canonica([]), PREFIJO_FILAS + '{"filas":[["A"]],"parser_content_version":1}',
    PREFIJO_FILAS + '{"filas":[["A",1]],"parser_content_version":1}', PREFIJO_FILAS + '{"filas":"x","parser_content_version":1}',
    canonica([["A", PREFIJO_FILAS + "{}"]]), PREFIJO_FILAS + '{"extra":1,"filas":[["A","B"]],"parser_content_version":1}',
])
def test_un_formato_inesperado_no_se_oculta_ni_se_vuelca_crudo(descripcion):
    with pytest.raises(ValueError):
        secciones(descripcion)
    partes, legible, inesperado = presentar(descripcion)
    assert inesperado is True and partes == [{"titulo": TITULO_ERROR, "texto": TEXTO_ERROR}]
    assert "TINOTIFY" not in legible and "no es json" not in legible and "parser_content_version" not in legible


def test_la_vista_previa_no_incluye_titulos_ni_prefijo_y_se_trunca():
    partes, _, _ = presentar(canonica([["Actuación", "A " * 200], ["Reparto", "B"]]))
    previa, truncada = vista_previa(partes, 50)
    assert len(previa) == 50 and truncada and "Reparto" not in previa and "TINOTIFY" not in previa


def test_el_parser_real_con_fixture_ficticio_se_presenta_sin_cambiar_la_huella():
    actuaciones = parsear(documento_con_presentacion(), contenedor_id="historial_ficticio")
    assert any(a.descripcion.startswith(PREFIJO_FILAS) for a in actuaciones)
    huellas_antes = [a.huella_version for a in actuaciones]
    contenido_antes = [a.contenido_versionado() for a in actuaciones]
    referencia = [(f"L{i}", h) for i, h in enumerate(huellas_antes)]
    items = construir_items(actuaciones, referencia)
    assert [a.huella_version for a in actuaciones] == huellas_antes  # el contenido canónico sigue idéntico
    assert [a.contenido_versionado() for a in actuaciones] == contenido_antes
    assert [a.descripcion.startswith(PREFIJO_FILAS) for a in actuaciones].count(True) >= 1  # la actuación no se muta
    assert all(i["en_referencia"] for i in items) and [i["local_id"] for i in items] == [f"L{i}" for i in range(len(items))]
    h = HistorialTemporal()
    h.cargar(caso_local(101), items, 300)
    salida = json.dumps(h.listado(caso_local(101)), ensure_ascii=False)
    sesion = h._sesion.sesion
    for n in range(len(items)):
        salida += json.dumps(h.detalle(caso_local(101), sesion, n), ensure_ascii=False)
    assert "TINOTIFY_FILAS" not in salida and "parser_content_version" not in salida and '\\"filas\\"' not in salida
    assert "Reparto" in salida and "CONTENIDO_FICTICIO_A" in salida


def test_un_contenido_inesperado_se_marca_en_listado_y_detalle_sin_romper_la_asociacion():
    malo = con_descripcion(PREFIJO_FILAS + "roto")
    bueno = con_descripcion(canonica([["Actuación", "TEXTO"]]))
    items = construir_items([malo, bueno], [("L1", malo.huella_version), ("L2", bueno.huella_version)])
    assert [i["local_id"] for i in items] == ["L1", "L2"] and [i["formato_inesperado"] for i in items] == [True, False]
    h = HistorialTemporal()
    h.cargar(caso_local(101), items, 300)
    listado = h.listado(caso_local(101))
    assert listado["formato_inesperado"] == 1 and [a["formato_inesperado"] for a in listado["actuaciones"]] == [True, False]
    assert "roto" not in json.dumps(listado) and "TINOTIFY" not in json.dumps(listado)
    assert h.detalle(caso_local(101), h._sesion.sesion, 0)["formato_inesperado"] is True
