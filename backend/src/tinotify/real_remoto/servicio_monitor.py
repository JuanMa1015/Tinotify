"""Servicio del monitor: guarda las credenciales cifradas y ejecuta una revisión completa. Sin texto judicial en ningún punto."""

import json
import logging

from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.integrations.sigac.sigac_client import SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.real_remoto.almacen import AlmacenNoDisponible
from tinotify.real_remoto.cifrado import (
    CifradoNoValido, VERSION_LLAVE, cifrar_credenciales, cifrar_expediente, descifrar_credenciales, descifrar_expediente)
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
        """Un intento por aviso nuevo (el correo de Actions sigue siendo el respaldo con reintentos). Solo conteos: nunca radicados
        ni nombres, porque el texto se ve en la pantalla de bloqueo."""
        if self._fcm is None:
            return
        cuerpo, pestana = _texto_push(plan)
        self._enviar_a_dispositivos(cuerpo, {"tipo": "novedades", "pestana": pestana})

    def enviar_prueba(self):
        """Notificación de prueba a los dispositivos registrados. No toca expedientes, avisos ni estado. (enviados, inválidos) o None sin FCM."""
        if self._fcm is None:
            return None
        return self._enviar_a_dispositivos("Notificación de prueba: tu teléfono recibe los avisos de Tinotify.", {"tipo": "prueba", "pestana": "inicio"})

    def _enviar_a_dispositivos(self, cuerpo, datos):
        enviados = invalidos = 0
        try:
            for token in self._almacen.dispositivos():
                resultado = self._fcm.enviar(token, "Tinotify", cuerpo, datos)
                if resultado == "ok":
                    enviados += 1
                elif resultado == "token_invalido":
                    invalidos += 1
                    self._almacen.borrar_dispositivo(token)
        except AlmacenNoDisponible:
            registro.warning("push_sin_almacen")
        return enviados, invalidos

    # --- expedientes (listado cifrado) ---------------------------------------------------------------------------------
    def _guardar_expedientes(self, plan, metadatos):
        filas = []
        for cambio in plan.cambios:
            if cambio.caso_ref not in metadatos:
                continue
            numero, cliente, estado = metadatos[cambio.caso_ref]
            nonce, cifrado = cifrar_expediente(self._llave, cambio.caso_ref, numero, cliente, estado)
            sumar = cambio.novedades if cambio.accion == "novedades" else 0
            filas.append((cambio.caso_ref, VERSION_LLAVE, nonce, cifrado, sumar, cambio.accion == "nuevo" and not plan.primera_ejecucion))
        try:
            self._almacen.guardar_expedientes(filas)
        except AlmacenNoDisponible:
            registro.warning("expedientes_sin_almacen")  # el listado se reintenta en la próxima revisión

    def expedientes(self):
        salida = []
        for ref, version, nonce, cifrado, no_vistas, nuevo, ultima in self._almacen.expedientes():
            try:
                numero, cliente, estado = descifrar_expediente(self._llave, ref, nonce, cifrado)
            except CifradoNoValido:
                continue  # llave distinta o dato alterado: no se muestra
            salida.append({"id": ref, "numero": numero, "cliente": cliente, "estado": estado,
                           "novedades_no_vistas": no_vistas, "nuevo": nuevo, "ultima_novedad": ultima})
        salida.sort(key=lambda e: (-(e["novedades_no_vistas"] > 0), -e["numero"]))
        return salida

    def marcar_vistos(self, caso_ref=None):
        return self._almacen.marcar_vistos(caso_ref)

    def olvidar_credenciales(self):
        return self._almacen.olvidar_credenciales()

    def estado(self):
        return self._almacen.estado()

    def ejecuciones(self, limite=30):
        return self._almacen.ejecuciones_recientes(limite)

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
            lecturas, fallidos, listados, errores, diagnosticos, metadatos = self._sesiones.con_cliente(lambda cliente: leer_expedientes(
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
        self._guardar_expedientes(plan, metadatos)
        if aviso:
            self._notificar_push(plan)
        self._cerrar(ejecucion, plan.resultado, expedientes=min(plan.expedientes, 1000), novedades=min(plan.novedades, 100000),
                     codigo="casos_fallidos" if fallidos else None)
        return {"resultado": plan.resultado, "expedientes": plan.expedientes, "novedades": plan.novedades,
                "expedientes_con_novedades": plan.expedientes_con_novedades, "expedientes_nuevos": plan.expedientes_nuevos,
                "anomalias": plan.anomalias, "casos_fallidos": fallidos, "linea_base": plan.primera_ejecucion,
                "aviso_nuevo": aviso, "avisos": self._almacen.avisos_pendientes()}


def _plural(n, uno, varios):
    return f"{n} {uno if n == 1 else varios}"


def _texto_push(plan):
    """Texto genérico con conteos y la pestaña a abrir al tocar la notificación."""
    if plan.novedades:
        texto = f"{_plural(plan.novedades, 'actuación nueva', 'actuaciones nuevas')} en {_plural(plan.expedientes_con_novedades, 'expediente', 'expedientes')}"
        if plan.expedientes_nuevos:
            texto += f" y {_plural(plan.expedientes_nuevos, 'expediente nuevo', 'expedientes nuevos')}"
        return texto, "casos"
    if plan.expedientes_nuevos:
        return ("Apareció un expediente nuevo en tu cuenta" if plan.expedientes_nuevos == 1
                else f"Aparecieron {plan.expedientes_nuevos} expedientes nuevos en tu cuenta"), "casos"
    return "Una lectura necesita tu revisión en SIGAC", "actividad"
