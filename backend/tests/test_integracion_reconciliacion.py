from pathlib import Path

import pytest

from tinotify.domain.actuaciones import TipoCambio
from tinotify.persistence.monitor import MonitorActuaciones
from tinotify.services.sigac_service import SigacService


CASOS_FICTICIOS = """<table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr>
<tr class="fila_enlace" onclick="abrir(101)"><td>101</td><td>CLIENTE FICTICIO</td><td>FICTICIO</td></tr></table>"""


@pytest.mark.parametrize("anterior,nuevo", [
    ("ESTUDIANTE DE PRUEBA", "OTRO REMITENTE FICTICIO"),
    ("Seguimiento del caso", "OTRA ETAPA FICTICIA"),
    ("Documento de prueba", "OTRO ANEXO FICTICIO"),
])
def test_servicio_conserva_metadatos_antes_descartados(tmp_path, anterior, nuevo):
    html = (Path(__file__).parent / "fixtures/caso_prueba.html").read_text(encoding="utf-8")
    servicio = SigacService(MonitorActuaciones(tmp_path / "estado.json"))
    servicio.procesar(CASOS_FICTICIOS, {101: html})
    resultados = servicio.procesar(CASOS_FICTICIOS, {101: html.replace(anterior, nuevo)})
    assert resultados[0].reconciliacion.eventos[0].tipo == TipoCambio.CAMBIO_AMBIGUO
    assert resultados[0].notificaciones[0].tipo == TipoCambio.CAMBIO_AMBIGUO
    assert servicio.procesar(CASOS_FICTICIOS, {101: html.replace(anterior, nuevo)})[0].notificaciones == ()


def test_servicio_conserva_multiplicidad(tmp_path):
    html = (Path(__file__).parent / "fixtures/caso_prueba.html").read_text(encoding="utf-8")
    servicio = SigacService(MonitorActuaciones(tmp_path / "estado.json"))
    servicio.procesar(CASOS_FICTICIOS, {101: html})
    resultado = servicio.procesar(CASOS_FICTICIOS, {101: html + html})[0]
    assert len(resultado.reconciliacion.actuaciones) == 2
    assert len(resultado.reconciliacion.eventos) == 1
    assert resultado.reconciliacion.eventos[0].tipo == TipoCambio.PRIMERA_OBSERVACION
