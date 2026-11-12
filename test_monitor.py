
from monitor import MonitorActuaciones
from notificaciones import Prioridad


def actuacion(fecha, direccion, descripcion):
    return {
        "fecha": fecha,
        "direccion": direccion,
        "descripcion": descripcion,
    }


def test_primera_sincronizacion_no_notifica(tmp_path):
    monitor = MonitorActuaciones(
        tmp_path / "estado.json"
    )

    resultado = monitor.sincronizar(
        12345,
        [
            actuacion(
                "2026-11-01 10:00:00",
                "ASESOR-->ESTUDIANTE",
                "Actuación histórica",
            )
        ],
    )

    assert resultado == []


def test_detecta_actuacion_nueva(tmp_path):
    monitor = MonitorActuaciones(
        tmp_path / "estado.json"
    )

    monitor.sincronizar(12345, [])

    resultado = monitor.sincronizar(
        12345,
        [
            actuacion(
                "2026-11-02 10:00:00",
                "ASESOR-->ESTUDIANTE",
                "Nueva actuación",
            )
        ],
    )

    assert len(resultado) == 1
    assert resultado[0].prioridad == Prioridad.ALTA


def test_no_notifica_duplicados(tmp_path):
    monitor = MonitorActuaciones(
        tmp_path / "estado.json"
    )

    datos = [
        actuacion(
            "2026-11-02 10:00:00",
            "ESTUDIANTE-->ASESOR",
            "Seguimiento",
        )
    ]

    monitor.sincronizar(12345, [])

    primera = monitor.sincronizar(12345, datos)
    segunda = monitor.sincronizar(12345, datos)

    assert len(primera) == 1
    assert segunda == []


def test_detecta_actuacion_antigua_insertada(tmp_path):
    monitor = MonitorActuaciones(
        tmp_path / "estado.json"
    )

    reciente = actuacion(
        "2026-11-10 10:00:00",
        "ESTUDIANTE-->ASESOR",
        "Actuación reciente",
    )

    anterior = actuacion(
        "2026-11-01 10:00:00",
        "DIRECCION-->ESTUDIANTE",
        "Actuación registrada posteriormente",
    )

    monitor.sincronizar(12345, [reciente])

    resultado = monitor.sincronizar(
        12345,
        [anterior, reciente],
    )

    assert len(resultado) == 1
    assert resultado[0].prioridad == Prioridad.ALTA


def test_estado_persiste_entre_ejecuciones(tmp_path):
    archivo = tmp_path / "estado.json"

    datos = [
        actuacion(
            "2026-11-02 10:00:00",
            "ASESOR-->ESTUDIANTE",
            "Observación",
        )
    ]

    primer_monitor = MonitorActuaciones(archivo)
    primer_monitor.sincronizar(12345, datos)

    segundo_monitor = MonitorActuaciones(archivo)

    assert segundo_monitor.sincronizar(
        12345, datos
    ) == []
