"""Sesión SIGAC temporal, en memoria, para UN usuario y UN proceso (desarrollo local por USB).

Reutiliza el monitor existente (`monitorear`) en un hilo y el almacén real: no hay una segunda implementación de
consultas periódicas. Las credenciales llegan una vez, se pasan a `SigacClient.autenticar` y se descartan en
cuanto se usan; no se guardan en ningún archivo, base, variable ni registro. Si la sesión expira o el acceso se
restringe, el monitor se detiene y hay que autorizar de nuevo: no hay reautenticación automática. Reiniciar el
proceso elimina la sesión y conserva el historial en SQLite.

Este módulo solo se carga cuando la API local activa explícitamente la sesión (nunca en la API de producción).
"""

from collections import deque
from enum import Enum
import threading
import time

from tinotify.services.consulta_real_local import etiqueta_valida
from tinotify.services.monitor_local import (
    INTERVALO_MAXIMO_S, INTERVALO_MINIMO_S, BloqueoMonitor, Motivo, MonitorEnEjecucion, monitorear,
)

MAX_FALLOS_ACCESO = 3
VENTANA_FALLOS_ACCESO_S = 900.0
ESPERA_LOGIN_S = 45.0       # cuánto espera el POST a que se confirme (o falle) la autenticación
ESPERA_CIERRE_S = 25.0      # una consulta en curso termina sola; no se cierra el cliente a media solicitud


class Estado(str, Enum):
    SIN_SESION = "sin_sesion"
    AUTENTICACION_PENDIENTE = "autenticacion_pendiente"
    AUTENTICACION_CONFIRMADA = "autenticacion_confirmada"   # acceso confirmado; primera consulta en curso
    MONITOR_ACTIVO = "monitor_activo"                       # al menos un ciclo completado
    DETENIENDO = "deteniendo"
    DETENIDO = "detenido"
    SESION_EXPIRADA = "sesion_expirada"
    ERROR = "error"


_ACTIVOS = {Estado.AUTENTICACION_PENDIENTE, Estado.AUTENTICACION_CONFIRMADA, Estado.MONITOR_ACTIVO, Estado.DETENIENDO}


class SesionEnCurso(RuntimeError):
    pass


class DemasiadosIntentosAcceso(RuntimeError):
    pass


def _cliente_sigac():
    from tinotify.integrations.sigac.sigac_client import SigacClient  # solo cuando se activa la sesión
    return SigacClient()


def _pausa_cooperativa(segundos, parar):
    parar.wait(segundos)


class GestorSesionSigac:
    def __init__(self, servicio, *, fabrica_cliente=_cliente_sigac, pausa=_pausa_cooperativa, reloj=time.monotonic,
                 espera_login_s=ESPERA_LOGIN_S, espera_cierre_s=ESPERA_CIERRE_S):
        if getattr(servicio, "sintetico", True):
            raise ValueError("La sesion SIGAC exige un almacen de perfil real")
        self._servicio, self._fabrica, self._pausa, self._reloj = servicio, fabrica_cliente, pausa, reloj
        self._espera_login_s, self._espera_cierre_s = espera_login_s, espera_cierre_s
        self._lock = threading.RLock()
        self._hilo = None
        self._parar = threading.Event()
        self._login = threading.Event()
        self._bloqueo = None
        self._fallos_acceso = deque()
        self._reiniciar_estado()

    # --- Estado observable (sin datos sensibles) -------------------------------------------------------------
    def _reiniciar_estado(self):
        self._estado, self._motivo, self._intervalo_s = Estado.SIN_SESION, None, None
        self._correctos = self._fallidos = 0
        self._ultimo_ciclo = self._ultimo_fallo = None
        self._detencion_pedida = False

    def snapshot(self):
        with self._lock:
            terminal = self._estado in (Estado.SESION_EXPIRADA, Estado.ERROR)
            return {
                "estado": self._estado.value, "motivo": self._motivo,
                "requiere_autorizacion": terminal, "intervalo_s": self._intervalo_s,
                "ciclos_correctos": self._correctos, "ciclos_fallidos": self._fallidos,
                "ultimo_ciclo": dict(self._ultimo_ciclo) if self._ultimo_ciclo else None,
                "ultimo_fallo": dict(self._ultimo_fallo) if self._ultimo_fallo else None,
            }

    def _emitir(self, evento):
        with self._lock:
            if evento["evento"] == "ciclo":
                self._correctos += 1
                self._ultimo_ciclo = {k: evento[k] for k in ("hora", "actuaciones", "novedades_nuevas", "generacion")}
                if self._estado is Estado.AUTENTICACION_CONFIRMADA:
                    self._estado = Estado.MONITOR_ACTIVO
                    self._login.set()
            elif evento["evento"] == "fallo":
                self._fallidos += 1
                self._ultimo_fallo = {k: evento.get(k) for k in ("hora", "tipo", "codigo")}

    # --- Inicio -----------------------------------------------------------------------------------------------
    def iniciar(self, *, usuario, clave, tipo, total_casos, indice_caso, intervalo_s, etiqueta=None, caso_login=None):
        """Devuelve el estado tras esperar (acotado) la confirmación de la autenticación.

        Nunca devuelve «monitor_activo» antes de confirmar la autenticación. Lanza SesionEnCurso,
        DemasiadosIntentosAcceso o ValueError (parámetros) sin tocar SIGAC.
        """
        if not all(isinstance(v, str) and v for v in (usuario, clave, tipo)):
            raise ValueError("Faltan datos de acceso")
        if type(intervalo_s) is not int or not INTERVALO_MINIMO_S <= intervalo_s <= INTERVALO_MAXIMO_S:
            raise ValueError("Intervalo fuera del rango permitido")
        if type(total_casos) is not int or total_casos < 1 or type(indice_caso) is not int \
                or not 1 <= indice_caso <= total_casos:
            raise ValueError("Total o posicion del listado no validos")
        titulo = etiqueta_valida(etiqueta)
        with self._lock:
            if self._estado in _ACTIVOS or (self._hilo is not None and self._hilo.is_alive()):
                raise SesionEnCurso("Ya hay una sesion o un monitor en curso")
            ahora = self._reloj()
            while self._fallos_acceso and ahora - self._fallos_acceso[0] >= VENTANA_FALLOS_ACCESO_S:
                self._fallos_acceso.popleft()
            if len(self._fallos_acceso) >= MAX_FALLOS_ACCESO:
                raise DemasiadosIntentosAcceso("Demasiados intentos de autenticacion")
            bloqueo = BloqueoMonitor(self._servicio.almacen.ruta)
            try:
                bloqueo.__enter__()
            except MonitorEnEjecucion:
                raise SesionEnCurso("Hay otro monitor activo sobre este almacen") from None
            self._bloqueo = bloqueo
            self._reiniciar_estado()
            self._estado, self._intervalo_s = Estado.AUTENTICACION_PENDIENTE, intervalo_s
            self._parar, self._login = threading.Event(), threading.Event()
            secretos = {"usuario": usuario, "clave": clave, "caso_login": caso_login}
            self._hilo = threading.Thread(
                target=self._ejecutar, name="sesion-sigac", daemon=True,
                args=(secretos, tipo, total_casos, indice_caso, intervalo_s, titulo, self._parar, self._login))
            self._hilo.start()
        del usuario, clave, caso_login
        self._login.wait(self._espera_login_s)
        return self.snapshot()

    def _ejecutar(self, secretos, tipo, total_casos, indice_caso, intervalo_s, titulo, parar, login):
        resultado = None
        try:
            with self._fabrica() as cliente:
                def entrar():
                    # Única autenticación de la sesión; los secretos se descartan en cuanto se usan.
                    try:
                        casos = cliente.autenticar(secretos["usuario"], secretos["clave"], tipo=tipo,
                                                   total_casos_esperado=total_casos, caso_login=secretos["caso_login"])
                    finally:
                        secretos.clear()
                    with self._lock:
                        if self._estado is Estado.AUTENTICACION_PENDIENTE:
                            self._estado = Estado.AUTENTICACION_CONFIRMADA
                    login.set()
                    return casos

                resultado = monitorear(
                    cliente, entrar, total_casos=total_casos, indice_caso=indice_caso, servicio=self._servicio,
                    etiqueta=titulo, intervalo_s=intervalo_s, reloj=self._reloj,
                    espera=lambda segundos: self._pausa(segundos, parar), emitir=self._emitir,
                    debe_detenerse=parar.is_set)
        except Exception:
            resultado = None
        finally:
            secretos.clear()
            self._finalizar(resultado, parar, login)

    def _finalizar(self, resultado, parar, login):
        with self._lock:
            if resultado is None:
                estado, motivo = Estado.ERROR, Motivo.ERROR_INESPERADO.value
            elif resultado.motivo is Motivo.INTERRUMPIDO:
                estado, motivo = Estado.DETENIDO, resultado.motivo.value
            elif resultado.motivo is Motivo.SESION_EXPIRADA:
                estado, motivo = Estado.SESION_EXPIRADA, resultado.motivo.value
            else:
                estado, motivo = Estado.ERROR, resultado.motivo.value
            if resultado is not None and resultado.motivo is Motivo.AUTENTICACION_FALLIDA:
                self._fallos_acceso.append(self._reloj())
            self._estado, self._motivo = estado, motivo
            bloqueo, self._bloqueo = self._bloqueo, None
        if bloqueo is not None:
            bloqueo.__exit__(None, None, None)
        login.set()  # el POST nunca queda esperando una sesión que ya terminó

    # --- Detención ----------------------------------------------------------------------------------------------
    def detener(self):
        """Detención cooperativa: una consulta en curso termina sola y su resultado no se persiste."""
        with self._lock:
            hilo = self._hilo
            if hilo is None or not hilo.is_alive():
                return self.snapshot()
            self._detencion_pedida = True
            self._parar.set()
            if self._estado in _ACTIVOS:
                self._estado = Estado.DETENIENDO
        hilo.join(self._espera_cierre_s)
        return self.snapshot()

    def apagar(self):
        """Cierre del proceso: no puede quedar un monitor vivo."""
        self.detener()
        hilo = self._hilo
        if hilo is not None:
            hilo.join(self._espera_cierre_s)
