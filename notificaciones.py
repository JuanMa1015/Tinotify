
from dataclasses import dataclass
from enum import Enum


class Prioridad(str, Enum):
    ALTA = "alta"
    NORMAL = "normal"


DIRECCIONES_PRIORITARIAS = {
    "ASESOR-->ESTUDIANTE",
    "DIRECCION-->ESTUDIANTE",
}


@dataclass(frozen=True)
class Notificacion:
    caso: int
    direccion: str
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
) -> Notificacion:
    prioridad = clasificar_prioridad(direccion)

    if prioridad == Prioridad.ALTA:
        titulo = "Nueva actuación importante"
    else:
        titulo = "Nueva actuación registrada"

    return Notificacion(
        caso=caso,
        direccion=direccion,
        prioridad=prioridad,
        titulo=titulo,
        mensaje=f"Hay una nueva actuación en el caso {caso}.",
    )
