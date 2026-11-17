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

    def sincronizar(self, credencial, caso, observaciones, *, clave: UUID, worker: UUID, binding: UUID,
                    generacion_esperada: int = 0) -> Recibo:
        """SQLite sintético delega al observador atómico; gen=0 solo es base inicial.

        Reenvíos conservan clave, contenido y generación original. La rama
        PostgreSQL conserva su contrato existente y no se modifica aquí.
        """
        caso = _caso(caso)
        from tinotify.persistence.sqlite_local import AlmacenSqliteLocal, CREDENCIAL_LOCAL, WORKER_LOCAL, BINDING_LOCAL
        if isinstance(self.almacen, AlmacenSqliteLocal):
            from tinotify.integrations.sigac.lectura_validada import HistorialSigac, LecturaSigacValidada
            if isinstance(observaciones, (HistorialSigac, LecturaSigacValidada)):
                raise PermissionError('Seguimiento generico no admite respuestas SIGAC')
            if self.almacen.perfil == 'real' or self.instancia == 'sigac-real':
                raise PermissionError('Seguimiento generico no admite origen SIGAC real')
            if credencial != CREDENCIAL_LOCAL or worker != WORKER_LOCAL or binding != BINDING_LOCAL:
                raise PermissionError('Contexto local no autorizado')
            if self.politica.firma(self.instancia) != self.almacen._politica.firma(self.instancia):
                raise PermissionError('Politica local incompatible')
            from tinotify.services.observacion_local import ObservadorLocal
            observaciones = [adaptar_observacion(a) for a in observaciones]
            if len(observaciones) > self.max_registros:
                raise ValueError('Lote demasiado grande; no se ha truncado')
            recibo, _ = ObservadorLocal(self.almacen, self.instancia).observar(
                caso, observaciones, clave=clave, generacion_esperada=generacion_esperada,
                titulo='Expediente local', contenido_vista=lambda _: {})
            return recibo
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
