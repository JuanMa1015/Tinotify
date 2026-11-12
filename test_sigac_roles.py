
import pytest

from sigac_roles import RolSigac, datos_seleccion_rol


def test_datos_rol_estudiante():
    assert datos_seleccion_rol(
        RolSigac.ESTUDIANTE
    ) == {
        "chkTipoUsuario": "ESTUDIANTE",
        "cmdAceptar": "Aceptar",
    }


def test_datos_rol_asistente_asesor():
    assert datos_seleccion_rol(
        RolSigac.ASISTENTE_ASESOR
    ) == {
        "chkTipoUsuario": "ASISTENTE_ASESOR",
        "cmdAceptar": "Aceptar",
    }


def test_rechazar_rol_no_valido():
    with pytest.raises(ValueError):
        datos_seleccion_rol("ADMINISTRADOR")


def test_roles_disponibles():
    assert RolSigac.ESTUDIANTE.value == "ESTUDIANTE"
    assert (
        RolSigac.ASISTENTE_ASESOR.value
        == "ASISTENTE_ASESOR"
    )
