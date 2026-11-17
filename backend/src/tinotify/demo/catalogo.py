"""Catálogo sintético de solo lectura para la app local.

No usa SIGAC, red, credenciales ni estado: todo es ficticio, inmutable y se reconstruye
en cada consulta. No importa el cliente SIGAC ni el parser real.
"""

from copy import deepcopy
from datetime import datetime
from uuid import UUID

from tinotify.domain.actuaciones import Actuacion, Anexo


def _actuacion(minutos, direccion, remitente, descripcion, anexos=()):
    origen, destino = direccion.split("-->")
    return Actuacion("SINTETICO", origen, destino, datetime(2026, 1, 15, 9, minutos),
                     remitente, descripcion, anexos=tuple(anexos))


# Identificadores fijos y ficticios: permiten pruebas deterministas y no corresponden a ningún expediente.
CASO_VARIAS = "00000000-0000-4000-8000-0000000000a1"
CASO_UNA = "00000000-0000-4000-8000-0000000000a2"
CASO_VACIO = "00000000-0000-4000-8000-0000000000a3"

CASOS_SINTETICOS = {
    CASO_VARIAS: ("Proceso sintético A (varias actuaciones)", (
        _actuacion(0, "ESTUDIANTE-->ASESOR", "REMITENTE SINTETICO UNO", "Actuación sintética número uno."),
        _actuacion(10, "ASESOR-->ESTUDIANTE", "REMITENTE SINTETICO DOS", "Actuación sintética número dos.",
                   (Anexo("Documento sintético con enlace", "documento_sintetico.pdf",
                          "general.descargarAnexo.con?codigo=SINTETICO"),)),
        _actuacion(20, "ASESOR-->ESTUDIANTE", "REMITENTE SINTETICO DOS", "Actuación sintética número tres.",
                   (Anexo("Descripción sintética sin enlace", "", "", sin_enlace=True),)),
    )),
    CASO_UNA: ("Proceso sintético B (una actuación)", (
        _actuacion(0, "DIRECCION-->ESTUDIANTE", "REMITENTE SINTETICO TRES", "Única actuación sintética."),
    )),
    CASO_VACIO: ("Proceso sintético C (sin actuaciones)", ()),
}


class CatalogoSintetico:
    def __init__(self, casos=None):
        self._casos = dict(CASOS_SINTETICOS if casos is None else casos)
        for caso in self._casos:
            UUID(caso)

    def listar(self):
        return [{"id": caso, "titulo": titulo, "total_actuaciones": len(actuaciones), "demo": True}
                for caso, (titulo, actuaciones) in self._casos.items()]

    def actuaciones(self, caso):
        """KeyError si el caso no existe; nunca devuelve referencias de descarga ni huellas."""
        titulo, actuaciones = self._casos[caso]
        return deepcopy({
            "id": caso, "titulo": titulo, "demo": True, "sintetico": True,
            "actuaciones": [{
                "fecha": a.fecha.isoformat(), "direccion": a.direccion, "remitente": a.remitente,
                "descripcion": a.descripcion,
                "anexos": [{"descripcion": x.descripcion, "sin_enlace": x.sin_enlace} for x in a.anexos],
            } for a in sorted(actuaciones, key=lambda a: a.fecha)],
        })
