
import pytest

from tinotify.persistence.monitor import MonitorActuaciones
from tinotify.domain.notificaciones import Prioridad
from tinotify.services.sigac_service import SigacService


HTML_CASOS = """
<table class="tabla">
    <tr>
        <th>Caso</th>
        <th>Cliente</th>
        <th>Estado</th>
    </tr>
    <tr onclick="abrir(12345)" class="fila_enlace">
        <td>12345</td>
        <td>Cliente Ficticio</td>
        <td>En proceso</td>
    </tr>
</table>
"""


def html_actuacion(
    fecha="2026-11-10 10:00:00",
    direccion="ESTUDIANTE-->ASESOR",
    descripcion="Seguimiento de prueba",
):
    return f"""
    <table>
        <tr>
            <td colspan="2"><hr/></td>
        </tr>
        <tr>
            <td>Pendiente Firma Poder</td>
            <td>{direccion}</td>
        </tr>
        <tr>
            <td>{fecha}</td>
            <td>Remitente Ficticio</td>
        </tr>
        <tr>
            <td>Actuación :</td>
            <td>{descripcion}</td>
        </tr>
    </table>
    """


def crear_servicio(tmp_path):
    monitor = MonitorActuaciones(
        tmp_path / "estado.json"
    )
    return SigacService(monitor)


def test_integracion_primera_sincronizacion(tmp_path):
    servicio = crear_servicio(tmp_path)

    resultados = servicio.procesar(
        HTML_CASOS,
        {12345: html_actuacion()},
    )

    assert len(resultados) == 1
    assert resultados[0].caso.numero == 12345
    assert len(resultados[0].actuaciones) == 1
    assert resultados[0].notificaciones == ()


def test_integracion_detecta_nueva_actuacion(tmp_path):
    servicio = crear_servicio(tmp_path)

    historial_inicial = html_actuacion()

    servicio.procesar(
        HTML_CASOS,
        {12345: historial_inicial},
    )

    nueva = html_actuacion(
        fecha="2026-11-11 11:00:00",
        direccion="ASESOR-->ESTUDIANTE",
        descripcion="Nueva observación ficticia",
    )

    resultados = servicio.procesar(
        HTML_CASOS,
        {12345: historial_inicial + nueva},
    )

    notificaciones = resultados[0].notificaciones

    assert len(notificaciones) == 1
    assert notificaciones[0].prioridad == (
        Prioridad.ALTA
    )


def test_integracion_no_duplica_notificaciones(
    tmp_path,
):
    servicio = crear_servicio(tmp_path)

    inicial = html_actuacion()
    nueva = html_actuacion(
        fecha="2026-11-11 12:00:00",
        direccion="DIRECCION-->ESTUDIANTE",
        descripcion="Revisión ficticia",
    )

    servicio.procesar(
        HTML_CASOS,
        {12345: inicial},
    )

    servicio.procesar(
        HTML_CASOS,
        {12345: inicial + nueva},
    )

    resultados = servicio.procesar(
        HTML_CASOS,
        {12345: inicial + nueva},
    )

    assert resultados[0].notificaciones == ()


def test_rechaza_html_de_expediente_vacio(tmp_path):
    servicio = crear_servicio(tmp_path)

    with pytest.raises(ValueError):
        servicio.procesar(
            HTML_CASOS,
            {12345: ""},
        )


def test_rechaza_expediente_sin_actuaciones(
    tmp_path,
):
    servicio = crear_servicio(tmp_path)

    with pytest.raises(ValueError):
        servicio.procesar(
            HTML_CASOS,
            {12345: "<html><body></body></html>"},
        )
