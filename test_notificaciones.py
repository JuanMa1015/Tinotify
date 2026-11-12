
from notificaciones import (
    Prioridad,
    clasificar_prioridad,
    crear_notificacion,
)


def test_asesor_estudiante_prioridad_alta():
    prioridad = clasificar_prioridad(
        "ASESOR-->ESTUDIANTE"
    )
    assert prioridad == Prioridad.ALTA


def test_direccion_estudiante_prioridad_alta():
    prioridad = clasificar_prioridad(
        "DIRECCION-->ESTUDIANTE"
    )
    assert prioridad == Prioridad.ALTA


def test_otras_actuaciones_prioridad_normal():
    direcciones = [
        "ESTUDIANTE-->ASESOR",
        "ESTUDIANTE-->DIRECCION",
        "ASESOR-->DIRECCION",
        "OTRO",
    ]

    for direccion in direcciones:
        assert (
            clasificar_prioridad(direccion)
            == Prioridad.NORMAL
        )


def test_normalizacion_de_direccion():
    prioridad = clasificar_prioridad(
        " asesor → estudiante "
    )
    assert prioridad == Prioridad.ALTA


def test_crear_notificacion():
    notificacion = crear_notificacion(
        caso=12345,
        direccion="ASESOR-->ESTUDIANTE",
    )

    assert notificacion.caso == 12345
    assert notificacion.prioridad == Prioridad.ALTA
    assert notificacion.titulo == (
        "Nueva actuación importante"
    )
    assert "12345" in notificacion.mensaje
