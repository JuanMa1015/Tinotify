"""Servicio del monitor: guarda las credenciales cifradas y ejecuta una revisión completa. Sin texto judicial en ningún punto."""

from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.integrations.sigac.sigac_client import SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.real_remoto.almacen import AlmacenNoDisponible
from tinotify.real_remoto.cifrado import VERSION_LLAVE, cifrar_credenciales, descifrar_credenciales
from tinotify.real_remoto.monitor import caso_ref, leer_expedientes
from tinotify.real_remoto.sesiones import DemasiadosIntentosLogin, SesionOcupada

_ACCESO_RECHAZADO = {CodigoHistorial.AUTENTICACION_NO_CONFIRMADA, CodigoHistorial.SESION_NO_CONFIRMADA,
                     CodigoHistorial.ACCESO_INCOMPLETO}


class SinCredenciales(Exception):
    """No hay credenciales guardadas: hay que iniciar sesión desde la app con «recordar»."""


class ServicioMonitor:
    def __init__(self, *, config, almacen, sesiones, referencia, clave_acreditacion):
        self._config, self._almacen, self._sesiones = config, almacen, sesiones
        self._referencia, self._clave = referencia, clave_acreditacion
        self._llave = config.monitor.clave_cifrado

    def guardar_credenciales(self, usuario, clave, caso_login=None):
        nonce, cifrado = cifrar_credenciales(self._llave, usuario, clave, caso_login)
        self._almacen.guardar_credenciales(VERSION_LLAVE, nonce, cifrado)

    def olvidar_credenciales(self):
        return self._almacen.olvidar_credenciales()

    def estado(self):
        return self._almacen.estado()

    def avisos_pendientes(self):
        return self._almacen.avisos_pendientes()

    def marcar_entregado(self, aviso):
        return self._almacen.marcar_entregado(aviso)

    def _cerrar(self, ejecucion, resultado, **datos):
        try:
            self._almacen.cerrar_ejecucion(ejecucion, resultado, **datos)
        except AlmacenNoDisponible:
            pass  # el resultado ya se informa a quien llamó; no se oculta el error original

    def ejecutar(self):
        fila = self._almacen.credenciales()
        if fila is None:
            raise SinCredenciales
        usuario, clave, caso_login = descifrar_credenciales(self._llave, fila[1], fila[2])  # CifradoNoValido si la llave no coincide
        ejecucion = self._almacen.iniciar_ejecucion()
        cfg = self._config
        try:
            lecturas, fallidos, listados = self._sesiones.con_cliente(lambda cliente: leer_expedientes(
                cliente, usuario, clave, tipo=cfg.tipo, total_casos=cfg.total_casos, caso_login=caso_login,
                clave_acreditacion=self._clave, instancia=INSTANCIA_REAL))
        except SesionOcupada:
            self._cerrar(ejecucion, "error_interno", codigo="sesion_ocupada")
            raise
        except DemasiadosIntentosLogin:
            self._cerrar(ejecucion, "error_interno", codigo="presupuesto_agotado")
            raise
        except SigacClientError as error:
            rechazado = isinstance(error, SigacSessionExpired) or error.codigo in _ACCESO_RECHAZADO
            self._cerrar(ejecucion, "error_acceso" if rechazado else "error_sigac", codigo=error.codigo.value[:64])
            raise
        finally:
            del usuario, clave, caso_login  # las credenciales no sobreviven a la lectura
        semillas = {caso_ref(self._clave, INSTANCIA_REAL, self._referencia.numero): self._referencia.multiconjunto()}
        try:
            plan, aviso = self._almacen.aplicar(lecturas, semillas)
        except AlmacenNoDisponible:
            self._cerrar(ejecucion, "error_estado")
            raise
        self._cerrar(ejecucion, plan.resultado, expedientes=min(plan.expedientes, 1000), novedades=min(plan.novedades, 100000),
                     codigo="casos_fallidos" if fallidos else None)
        return {"resultado": plan.resultado, "expedientes": plan.expedientes, "novedades": plan.novedades,
                "expedientes_con_novedades": plan.expedientes_con_novedades, "expedientes_nuevos": plan.expedientes_nuevos,
                "anomalias": plan.anomalias, "casos_fallidos": fallidos, "linea_base": plan.primera_ejecucion,
                "aviso_nuevo": aviso, "avisos": self._almacen.avisos_pendientes()}
