"""Origen ficticio sin HTTP, credenciales institucionales ni IDs verificados."""

from datetime import datetime, timedelta

from tinotify.domain.actuaciones import Actuacion


class SigacSimulado:
    def __init__(self):
        self._historiales = {}

    def crear(self, caso):
        self._historiales[caso] = [self._actuacion(0)]

    @staticmethod
    def _actuacion(numero):
        return Actuacion("DEMOSTRACION", "ASESOR", "ESTUDIANTE",
                         datetime(2026, 1, 1, 12) + timedelta(minutes=numero),
                         "RESPONSABLE FICTICIO", f"Actuacion sintetica numero {numero}.")

    def agregar(self, caso):
        historial = self._historiales[caso]
        historial.append(self._actuacion(len(historial)))

    def observar(self, caso):
        return tuple(self._historiales[caso])
