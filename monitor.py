
import hashlib
import json
from pathlib import Path

from notificaciones import crear_notificacion


class MonitorActuaciones:
    def __init__(self, archivo_estado="estado_monitor.json"):
        self.archivo_estado = Path(archivo_estado)
        self.estado = self._cargar_estado()

    def _cargar_estado(self):
        if not self.archivo_estado.exists():
            return {}

        with self.archivo_estado.open(
            "r", encoding="utf-8"
        ) as archivo:
            return json.load(archivo)

    def _guardar_estado(self):
        temporal = self.archivo_estado.with_suffix(".tmp")

        with temporal.open(
            "w", encoding="utf-8"
        ) as archivo:
            json.dump(
                self.estado,
                archivo,
                indent=2,
                ensure_ascii=False,
            )

        temporal.replace(self.archivo_estado)

    @staticmethod
    def identificar_actuacion(actuacion):
        """
        Identificador provisional basado en el contenido.

        En producción sería preferible un ID estable
        proporcionado por SIGAC.
        """
        contenido = {
            "fecha": actuacion["fecha"],
            "direccion": actuacion["direccion"],
            "descripcion": actuacion["descripcion"],
        }

        serializado = json.dumps(
            contenido,
            ensure_ascii=False,
            sort_keys=True,
        )

        return hashlib.sha256(
            serializado.encode("utf-8")
        ).hexdigest()

    def sincronizar(self, caso, actuaciones):
        clave_caso = str(caso)

        actuales = {
            self.identificar_actuacion(actuacion)
            for actuacion in actuaciones
        }

        # Primera sincronización: registrar sin notificar.
        if clave_caso not in self.estado:
            self.estado[clave_caso] = sorted(actuales)
            self._guardar_estado()
            return []

        conocidos = set(self.estado[clave_caso])
        nuevos = actuales - conocidos

        notificaciones = []

        for actuacion in actuaciones:
            identificador = self.identificar_actuacion(
                actuacion
            )

            if identificador not in nuevos:
                continue

            notificaciones.append(
                crear_notificacion(
                    caso=caso,
                    direccion=actuacion["direccion"],
                )
            )

            nuevos.remove(identificador)

        # Conservamos el historial de identificadores.
        self.estado[clave_caso] = sorted(
            conocidos | actuales
        )
        self._guardar_estado()

        return notificaciones
