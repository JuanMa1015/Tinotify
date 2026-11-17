"""Servicio del monitor: guarda las credenciales cifradas y ejecuta una revisión completa. Sin texto judicial en ningún punto."""

import json
import logging

from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.integrations.sigac.sigac_client import SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.real_remoto.almacen import AlmacenNoDisponible
from tinotify.real_remoto.cifrado import VERSION_LLAVE, cifrar_credenciales, descifrar_credenciales
from tinotify.real_remoto.monitor import caso_ref, leer_expedientes
from tinotify.real_remoto.sesiones import DemasiadosIntentosLogin, SesionOcupada

registro = logging.getLogger("tinotify.real_remoto")
_ACCESO_RECHAZADO = {CodigoHistorial.AUTENTICACION_NO_CONFIRMADA, CodigoHistorial.SESION_NO_CONFIRMADA,
                     CodigoHistorial.ACCESO_INCOMPLETO}


class SinCredenciales(Exception):
    """No hay credenciales guardadas: hay que iniciar sesión desde la app con «recordar»."""


class ServicioMonitor:
    def __init__(self, *, config, almacen, sesiones, referencia, clave_acreditacion, fcm=None):
        self._config, self._almacen, self._sesiones, self._fcm = config, almacen, sesiones, fcm
        self._referencia, self._clave = referencia, clave_acreditacion
        self._llave = config.monitor.clave_cifrado

    def guardar_credenciales(self, usuario, clave, caso_login=None):
        nonce, cifrado = cifrar_credenciales(self._llave, usuario, clave, caso_login)
        self._almacen.guardar_credenciales(VERSION_LLAVE, nonce, cifrado)

    def registrar_dispositivo(self, token):
        self._almacen.registrar_dispositivo(token)

    def borrar_dispositivo(self, token):
        return self._almacen.borrar_dispositivo(token)

    def _notificar_push(self, plan):
        """Un intento por aviso nuevo (el correo de Actions sigue siendo el respaldo con reintentos). Mensaje genérico, sin datos del caso."""
        if self._fcm is None:
            return
        cuerpo = ("Hay actuaciones nuevas en SIGAC" if plan.novedades else
                  "Apareció un expediente nuevo en tu cuenta" if plan.expedientes_nuevos else "Hay una lectura por revisar en SIGAC")
        try:
            for token in self._almacen.dispositivos():
                if self._fcm.enviar(token, "Tinotify", cuerpo) == "token_invalido":
                    self._almacen.borrar_dispositivo(token)
        except AlmacenNoDisponible:
            registro.warning("push_sin_almacen")

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
            lecturas, fallidos, listados, errores, diagnosticos = self._sesiones.con_cliente(lambda cliente: leer_expedientes(
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
        if errores:
            # Para quien opera el servicio: cuántos expedientes fallaron y con qué código/etapa de catálogo.
            registro.warning("monitor_casos_fallidos listados=%s leidos=%s detalle=%s", listados, len(lecturas), json.dumps(
                sorted([{"codigo": c, "etapa": e, "n": n} for (c, e), n in errores.items()], key=lambda d: (-d["n"], d["codigo"]))))
        if diagnosticos:
            registro.warning("monitor_diagnostico_anexos conteos=%s", json.dumps(diagnosticos, sort_keys=True))
        semillas = {caso_ref(self._clave, INSTANCIA_REAL, self._referencia.numero): self._referencia.multiconjunto()}
        try:
            plan, aviso = self._almacen.aplicar(lecturas, semillas)
        except AlmacenNoDisponible:
            self._cerrar(ejecucion, "error_estado")
            raise
        if aviso:
            self._notificar_push(plan)
        self._cerrar(ejecucion, plan.resultado, expedientes=min(plan.expedientes, 1000), novedades=min(plan.novedades, 100000),
                     codigo="casos_fallidos" if fallidos else None)
        return {"resultado": plan.resultado, "expedientes": plan.expedientes, "novedades": plan.novedades,
                "expedientes_con_novedades": plan.expedientes_con_novedades, "expedientes_nuevos": plan.expedientes_nuevos,
                "anomalias": plan.anomalias, "casos_fallidos": fallidos, "linea_base": plan.primera_ejecucion,
                "aviso_nuevo": aviso, "avisos": self._almacen.avisos_pendientes()}
