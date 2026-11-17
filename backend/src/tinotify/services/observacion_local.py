"""Operación local v2. HTTP y autorización institucional quedan fuera."""

from collections import Counter, defaultdict, deque
from dataclasses import asdict
from uuid import UUID

from tinotify.domain.actuaciones import Actuacion, VERSION_HUELLA, resumir, serializar
from tinotify.domain.identificadores import ContextoOrigen
from tinotify.domain.notificaciones import clasificar_prioridad
from tinotify.persistence.codec_postgres import validar_confianza
from tinotify.persistence.interfaces import Recibo
from tinotify.persistence.monitor import _nuevo_estado
from tinotify.persistence.sqlite_local import (
    BINDING_LOCAL, CREDENCIAL_LOCAL, WORKER_LOCAL,
    ConflictoPersistenciaLocal, ResultadoCommitIncierto,
)
from tinotify.services.reconciliacion import reconciliar


class ObservacionRechazada(ValueError):
    """No adelanta la base ni genera eventos."""


def contenido_logico(instancia, caso, perfil, politica, actuaciones, titulo, generacion):
    contexto = ContextoOrigen(instancia, caso)
    lote = []
    for a in actuaciones:
        identidad = politica.aplicar(a.identificador_origen, contexto)
        lote.append({'contenido': a.contenido_versionado(),
                     'identidad': asdict(identidad) if identidad is not None else None})
    return {
        'operacion_version': 1, 'fingerprint_version': VERSION_HUELLA,
        'instancia': instancia, 'caso': caso, 'perfil': perfil, 'politica': politica.firma(instancia),
        'generacion_esperada': generacion, 'titulo': titulo if perfil == 'sintetico' else 'Expediente local',
        'observaciones': sorted(lote, key=serializar),
    }


class ObservadorLocal:
    def __init__(self, almacen, instancia):
        self.almacen, self.instancia = almacen, instancia
        self.politica = almacen._politica

    def generacion(self, caso):
        if str(UUID(caso)) != caso:
            raise ValueError('Identificador local no canonico')
        with self.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
            seguimiento = unidad.buscar_seguimiento(self.instancia, caso)
            return unidad.generacion(seguimiento) if seguimiento else 0

    def consultar_recibo(self, caso, clave, digest):
        """Cada llamada abre otra conexión; no reenvía la operación."""
        with self.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
            seguimiento = unidad.buscar_seguimiento(self.instancia, caso)
            return unidad.recibo_operacion(seguimiento, clave, digest)

    def observar(self, caso, actuaciones, *, clave, generacion_esperada, titulo, contenido_vista):
        from tinotify.integrations.sigac.lectura_validada import HistorialSigac, LecturaSigacValidada
        if isinstance(actuaciones, (HistorialSigac, LecturaSigacValidada)):
            raise PermissionError('Usar observar_validada para origen SIGAC')
        if self.almacen.perfil == 'real' or self.instancia == 'sigac-real':
            raise PermissionError('Observaciones reales requieren una respuesta SIGAC validada')
        return self._observar(caso, actuaciones, clave=clave, generacion_esperada=generacion_esperada,
                              titulo=titulo, contenido_vista=contenido_vista)

    def observar_validada(self, lectura, *, clave, generacion_esperada):
        from tinotify.integrations.sigac.lectura_validada import _resolver_lectura, _referencia_local
        if self.almacen.perfil != 'real' or self.instancia != 'sigac-real':
            raise PermissionError('Una respuesta SIGAC no puede reclasificarse como sintetica')
        _, actuaciones = _resolver_lectura(lectura)
        caso = _referencia_local(lectura)
        recibo, novedades = self._observar(caso, actuaciones, clave=clave,
            generacion_esperada=generacion_esperada, titulo='Expediente local',
            contenido_vista=lambda _: {}, lectura=lectura)
        return caso, recibo, novedades, len(actuaciones)

    def _observar(self, caso, actuaciones, *, clave, generacion_esperada, titulo, contenido_vista, lectura=None):
        if self.almacen.perfil == 'real':
            from tinotify.integrations.sigac.lectura_validada import _resolver_lectura, _referencia_local
            _, verificadas = _resolver_lectura(lectura)
            if caso != _referencia_local(lectura) or tuple(actuaciones) != verificadas or self.instancia != 'sigac-real':
                raise PermissionError('Lectura y observacion no corresponden')
        if str(UUID(caso)) != caso:
            raise ValueError('Identificador local no canonico')
        if not isinstance(clave, UUID) or type(generacion_esperada) is not int or generacion_esperada < 0:
            raise ValueError('Operacion y generacion esperada explicitas requeridas')
        actuaciones = list(actuaciones)
        if not actuaciones or len(actuaciones) > 20000 or any(not isinstance(a, Actuacion) for a in actuaciones):
            raise ObservacionRechazada('Lote vacio, invalido o fuera de cuota')
        digest = resumir(contenido_logico(self.instancia, caso, self.almacen.perfil, self.politica,
                                        actuaciones, titulo, generacion_esperada))
        try:
            transaccion = (self.almacen._transaccion_sigac(lectura, caso) if lectura is not None
                           else self.almacen.transaccion(CREDENCIAL_LOCAL))
            with transaccion as unidad:
                seguimiento = unidad.seguir(self.instancia, caso, self.politica.firma(self.instancia))
                repetido = unidad.recibo_operacion(seguimiento, clave, digest)
                if repetido:
                    return repetido, 0
                if unidad.generacion(seguimiento) != generacion_esperada:
                    raise ConflictoPersistenciaLocal('Conflicto de generacion; no se fusiona ni reintenta')
                anterior = unidad.leer_caso(seguimiento, BINDING_LOCAL)
                validacion = _nuevo_estado(politica=self.politica, instancia=self.instancia)
                if anterior is not None:
                    validacion['cases'][caso] = anterior
                validar_confianza(validacion, self.politica, self.instancia)
                # La base autoritativa, nunca la vista, decide la conservación.
                previas = Counter(r['version_hash'] for r in anterior['records']) if anterior else Counter()
                actuales = Counter(a.huella_version for a in actuaciones)
                if previas - actuales:
                    raise ObservacionRechazada('Ausencias o cambios ambiguos; base sin cambios')
                reserva = unidad.reservar(seguimiento, clave, WORKER_LOCAL, BINDING_LOCAL)
                unidad.asociar_digest(reserva, digest)
                siguiente, resultado = reconciliar(anterior, actuaciones, caso=caso, instancia=self.instancia,
                                                    politica_confianza=self.politica)
                if len(siguiente['records']) > 20000:
                    raise ObservacionRechazada('Estado fuera de cuota; no se purga')
                validacion['cases'][caso] = siguiente
                validar_confianza(validacion, self.politica, self.instancia)
                eventos = [{'local_id': e.identidad_local, 'tipo': e.tipo.value,
                            'prioridad': clasificar_prioridad(e.direccion).value} for e in resultado.eventos]
                generacion = unidad.confirmar(reserva, siguiente['records'], eventos, self.politica.firma(self.instancia))
                # Ocurrencias exactas, sin suponer identidad física de duplicados.
                identidades = defaultdict(deque)
                for a in resultado.actuaciones:
                    identidades[a.huella_version].append(a.identidad_local)
                filas = [(identidades[a.huella_version].popleft(), a.huella_version,
                          contenido_vista(a) if self.almacen.perfil == 'sintetico' else {}) for a in actuaciones]
                unidad.guardar_vista(caso, titulo, filas)
                recibo = Recibo(reserva.trabajo_id, generacion, False)
            return recibo, len(eventos)
        except ResultadoCommitIncierto:
            confirmado = self.consultar_recibo(caso, clave, digest)
            if confirmado is None:
                raise ResultadoCommitIncierto('Recibo no confirmado; conservar clave y lote, sin reintento automatico') from None
            return confirmado, 0
