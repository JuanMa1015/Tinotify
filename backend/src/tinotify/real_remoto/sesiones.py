"""Gestor de acceso SIGAC remoto: una sola lectura a la vez, presupuesto de intentos y cierre del cliente.

Las credenciales solo existen como argumentos de `iniciar` y se pasan al cliente SIGAC: no se asignan a atributos,
no se registran y no sobreviven a la llamada. Tras la lectura el cliente HTTP se cierra (las cookies SIGAC se
descartan): no se retiene ninguna sesión SIGAC viva. Solo queda, en `HistorialTemporal`, el contenido con vencimiento.
"""

from collections import deque
import threading
import time

from tinotify.integrations.sigac.sigac_client import SigacClient
from tinotify.services.historial_temporal import leer_con_referencia


class SesionOcupada(Exception):
    pass


class DemasiadosIntentosLogin(Exception):
    def __init__(self, espera_s):
        super().__init__("presupuesto de intentos agotado")
        self.espera_s = espera_s


class GestorSesion:
    def __init__(self, *, config, politica, referencia, historial, fabrica_cliente=SigacClient, reloj=time.monotonic):
        self._config, self._politica, self._referencia = config, politica, referencia
        self._historial, self._fabrica, self._reloj = historial, fabrica_cliente, reloj
        self._ocupado = threading.Lock()
        self._intentos = deque()
        self._lock = threading.Lock()

    def _presupuesto(self):
        """Cuenta CADA intento que llegaría a SIGAC (éxito o fallo): la política de bloqueo de SIGAC es desconocida."""
        with self._lock:
            ahora = self._reloj()
            while self._intentos and ahora - self._intentos[0] >= self._config.ventana_login_s:
                self._intentos.popleft()
            if len(self._intentos) >= self._config.max_logins:
                raise DemasiadosIntentosLogin(max(1, int(self._config.ventana_login_s - (ahora - self._intentos[0]))))
            self._intentos.append(ahora)

    def iniciar(self, usuario, clave, caso_login=None):
        if not self._ocupado.acquire(blocking=False):
            raise SesionOcupada()
        try:
            self._presupuesto()
            cliente = self._fabrica()
            with cliente:
                return leer_con_referencia(
                    cliente, usuario, clave, tipo=self._config.tipo, total_casos=self._config.total_casos,
                    caso_numero=self._referencia.numero, politica=self._politica, entradas=self._referencia.entradas(),
                    huella=self._referencia.huella, caso=self._referencia.caso_id, historial=self._historial,
                    ttl_s=self._config.ttl_s, caso_login=caso_login)
        finally:
            self._ocupado.release()
