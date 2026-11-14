"""Reconciliacion existente y eventos se confirman en una unica transaccion."""

from uuid import UUID

from tinotify.domain.actuaciones import adaptar_observacion
from tinotify.domain.identificadores import PoliticaConfianza
from tinotify.domain.notificaciones import clasificar_prioridad
from tinotify.persistence.codec_postgres import binario, validar_confianza
from tinotify.persistence.interfaces import AlmacenSeguimiento, Recibo
from tinotify.persistence.monitor import _caso, _nuevo_estado
from tinotify.services.reconciliacion import reconciliar


class ServicioSeguimiento:
    def __init__(self, almacen: AlmacenSeguimiento, *, instancia="local", politica=None, max_registros=20000):
        binario(instancia)
        if not 1 <= max_registros <= 100000:
            raise ValueError("Cuota no valida")
        self.almacen, self.instancia = almacen, instancia
        self.politica = politica if politica is not None else PoliticaConfianza()
        self.max_registros = max_registros

    def sincronizar(self, credencial, caso, observaciones, *, clave: UUID, worker: UUID, binding: UUID) -> Recibo:
        caso = _caso(caso)
        observaciones = [adaptar_observacion(a) for a in observaciones]
        if len(observaciones) > self.max_registros:
            raise ValueError("Lote demasiado grande; no se ha truncado")
        with self.almacen.transaccion(credencial) as unidad:
            seguimiento = unidad.seguir(self.instancia, caso, self.politica.firma(self.instancia))
            reserva = unidad.reservar(seguimiento, clave, worker, binding)
            if reserva.estado == "confirmada":
                return Recibo(reserva.trabajo_id, reserva.generacion, True)
            anterior = unidad.leer_caso(seguimiento, binding)
            validacion = _nuevo_estado(politica=self.politica, instancia=self.instancia)
            if anterior is not None:
                validacion["cases"][caso] = anterior
            validar_confianza(validacion, self.politica, self.instancia)
            siguiente, resultado = reconciliar(
                anterior, observaciones, caso=caso, instancia=self.instancia,
                politica_confianza=self.politica,
            )
            if len(siguiente["records"]) > self.max_registros:
                raise ValueError("Estado demasiado grande; no se ha purgado")
            validacion["cases"][caso] = siguiente
            validar_confianza(validacion, self.politica, self.instancia)
            eventos = [{"local_id": e.identidad_local, "tipo": e.tipo.value,
                        "prioridad": clasificar_prioridad(e.direccion).value} for e in resultado.eventos]
            generacion = unidad.confirmar(reserva, siguiente["records"], eventos, self.politica.firma(self.instancia))
            return Recibo(reserva.trabajo_id, generacion, False)

    def estado(self, credencial, *, binding: UUID):
        with self.almacen.transaccion(credencial, lectura=True) as unidad:
            return unidad.exportar(self.instancia, binding)
