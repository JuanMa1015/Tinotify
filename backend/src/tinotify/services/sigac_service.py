
from dataclasses import dataclass
from typing import Mapping

from tinotify.parsers.casos_parser import Caso, extraer_casos
from tinotify.parsers.parser import Actuacion, parse_actuaciones
from tinotify.persistence.monitor import MonitorActuaciones
from tinotify.domain.notificaciones import Notificacion


@dataclass(frozen=True)
class ResultadoCaso:
    caso: Caso
    actuaciones: tuple[Actuacion, ...]
    notificaciones: tuple[Notificacion, ...]


class SigacService:
    def __init__(self, monitor: MonitorActuaciones):
        self.monitor = monitor

    @staticmethod
    def convertir_actuacion(
        actuacion: Actuacion,
    ) -> dict[str, str]:
        """
        Adapta el modelo del parser a la interfaz
        que espera el monitor existente.
        """
        return {
            "fecha": actuacion.fecha.isoformat(
                sep=" ",
                timespec="seconds",
            ),
            "direccion": (
                f"{actuacion.origen}-->"
                f"{actuacion.destino}"
            ),
            "descripcion": actuacion.descripcion,
        }

    def procesar(
        self,
        html_casos: str,
        html_expedientes: Mapping[int, str],
    ) -> list[ResultadoCaso]:
        if not html_casos.strip():
            raise ValueError(
                "El HTML del listado está vacío."
            )

        casos = extraer_casos(html_casos)

        if not casos:
            raise ValueError(
                "No se encontraron casos. "
                "Comprueba el HTML antes de sincronizar."
            )

        # Validamos todos los expedientes antes de
        # modificar el estado del monitor.
        preparados = []

        for caso in casos:
            if caso.numero not in html_expedientes:
                raise ValueError(
                    f"Falta el HTML del caso {caso.numero}."
                )

            html = html_expedientes[caso.numero]

            if not html.strip():
                raise ValueError(
                    f"HTML vacío para el caso {caso.numero}."
                )

            actuaciones = parse_actuaciones(
                html,
                str(caso.numero),
            )

            # Un resultado vacío podría significar
            # un fallo del parser o un caso sin historial.
            # Por seguridad, no sincronizamos ese caso.
            if not actuaciones:
                raise ValueError(
                    f"No se pudieron extraer actuaciones "
                    f"del caso {caso.numero}."
                )

            preparados.append((caso, actuaciones))

        resultados = []

        for caso, actuaciones in preparados:
            datos_monitor = [
                self.convertir_actuacion(actuacion)
                for actuacion in actuaciones
            ]

            notificaciones = self.monitor.sincronizar(
                caso.numero,
                datos_monitor,
            )

            resultados.append(
                ResultadoCaso(
                    caso=caso,
                    actuaciones=tuple(actuaciones),
                    notificaciones=tuple(notificaciones),
                )
            )

        return resultados
