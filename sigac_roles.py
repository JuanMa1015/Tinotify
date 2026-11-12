
from enum import Enum


class RolSigac(str, Enum):
    ESTUDIANTE = "ESTUDIANTE"
    ASISTENTE_ASESOR = "ASISTENTE_ASESOR"


def datos_seleccion_rol(rol: RolSigac) -> dict[str, str]:
    if not isinstance(rol, RolSigac):
        raise ValueError("Rol SIGAC no válido.")

    return {
        "chkTipoUsuario": rol.value,
        "cmdAceptar": "Aceptar",
    }
