
from dataclasses import dataclass
from enum import Enum

from tinotify.domain.actuaciones import TipoCambio


class Prioridad(str, Enum):
    ALTA = "alta"
    NORMAL = "normal"


DIRECCIONES_PRIORITARIAS = {
    "ASESOR-->ESTUDIANTE",
    "DIRECCION-->ESTUDIANTE",
}


@dataclass(frozen=True)
class Notificacion:
    tipo: TipoCambio
    prioridad: Prioridad
    titulo: str
    mensaje: str


def normalizar_direccion(direccion: str) -> str:
    return (
        direccion.strip()
        .upper()
        .replace(" ", "")
        .replace("→", "-->")
    )


def clasificar_prioridad(direccion: str) -> Prioridad:
    direccion = normalizar_direccion(direccion)

    if direccion in DIRECCIONES_PRIORITARIAS:
        return Prioridad.ALTA

    return Prioridad.NORMAL


def crear_notificacion(
    caso: int,
    direccion: str,
    tipo: TipoCambio = TipoCambio.PRIMERA_OBSERVACION,
) -> Notificacion:
    """El caso se acepta por compatibilidad, pero no forma parte del aviso."""
    tipo = TipoCambio(tipo)
    prioridad = clasificar_prioridad(direccion)
    if tipo == TipoCambio.CAMBIO_AMBIGUO:
        titulo = "Cambios pendientes de clasificar"
        mensaje = "Se observaron diferencias que requieren revisión."
    elif tipo == TipoCambio.MODIFICACION_CONFIRMADA:
        titulo = "Información actualizada"
        mensaje = "Se detectó una modificación. Revisa la aplicación."
    else:
        titulo = "Nueva información importante" if prioridad == Prioridad.ALTA else "Nueva información disponible"
        mensaje = "Hay información observada por primera vez. Revisa la aplicación."

    return Notificacion(
        tipo=tipo,
        prioridad=prioridad,
        titulo=titulo,
        mensaje=mensaje,
    )
