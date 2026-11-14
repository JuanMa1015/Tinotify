"""Lectura y acuse de eventos; no implementa entrega push ni exactly-once."""

from dataclasses import dataclass, replace
from uuid import UUID

from tinotify.domain.actuaciones import TipoCambio
from tinotify.domain.notificaciones import Notificacion, Prioridad, crear_notificacion
from tinotify.persistence.interfaces import AlmacenSeguimiento


@dataclass(frozen=True)
class AvisoPendiente:
    id: UUID
    notificacion: Notificacion


class ServicioAvisos:
    def __init__(self, almacen: AlmacenSeguimiento):
        self.almacen = almacen

    def pendientes(self, credencial, *, binding: UUID, limite=100) -> tuple[AvisoPendiente, ...]:
        with self.almacen.transaccion(credencial,lectura=True) as unidad:
            filas = unidad.pendientes(binding,limite)
        # Solo tipo y prioridad persistidos. No reconstruir direcciones ni datos
        # juridicos inexistentes; el titulo generico puede ser el de prioridad normal.
        return tuple(AvisoPendiente(UUID(f["id"]),replace(
            crear_notificacion(0,"",TipoCambio(f["tipo"])),prioridad=Prioridad(f["prioridad"]),
        )) for f in filas)

    def procesar(self, credencial, evento: UUID, *, binding: UUID) -> None:
        with self.almacen.transaccion(credencial) as unidad:
            unidad.procesar_aviso(evento,binding)
