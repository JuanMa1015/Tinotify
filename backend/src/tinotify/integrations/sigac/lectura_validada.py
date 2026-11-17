"""Capacidad local efímera: valida el recorrido HTTP, no firma identidad institucional.

No existe fábrica pública desde HTML/actuaciones. Inyección de transportes,
monkeypatch, introspección y acceso SQL son código privilegiado fuera de esta
frontera de aplicación. No es un aislamiento frente a Python hostil en el proceso.
"""

from weakref import WeakKeyDictionary


class HistorialSigac(tuple):
    """Etiqueta solo de RECHAZO en entradas sintéticas; no concede confianza."""

    def __repr__(self):
        return 'HistorialSigac(contenido_no_mostrado)'


def _frontera():
    registros = WeakKeyDictionary()

    class LecturaSigacValidada:
        __slots__ = ('__weakref__',)

        def __new__(cls, *args, **kwargs):
            raise TypeError('Solo el recorrido HTTP validado puede emitir una lectura')

        def __repr__(self):
            return 'LecturaSigacValidada()'

        def __reduce_ex__(self, protocolo):
            raise TypeError('Lectura efimera no serializable')

    def leer(cliente, numero, *, total_esperado=None, contenedor_id=None):
        from tinotify.integrations.sigac.sigac_client import SigacClient
        if type(cliente) is not SigacClient:
            raise PermissionError('Se requiere el cliente SIGAC estricto')
        # Invocar la implementación auditada, no un override del llamador.
        actuaciones = SigacClient.consultar_historial(
            cliente, numero, total_esperado=total_esperado, contenedor_id=contenedor_id,
        )
        lectura = object.__new__(LecturaSigacValidada)
        registros[lectura] = (numero, tuple(actuaciones))
        return lectura

    def resolver(lectura):
        if type(lectura) is not LecturaSigacValidada or lectura not in registros:
            raise PermissionError('Lectura SIGAC no acreditada por el recorrido validado')
        return registros[lectura]

    return LecturaSigacValidada, leer, resolver


LecturaSigacValidada, leer_historial_validado, _resolver_lectura = _frontera()
del _frontera


def _referencia_local(lectura):
    # Reutiliza SOLO el direccionamiento local preexistente. El UUID NO prueba
    # estabilidad institucional; las entradas reales de monitor siguen cerradas.
    from tinotify.services.consulta_real_local import caso_local
    numero, _ = _resolver_lectura(lectura)
    return caso_local(numero)
