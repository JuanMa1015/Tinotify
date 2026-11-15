"""Monitor SINTÉTICO: simula periódicamente que aparece una actuación nueva en un caso ficticio.

No usa ni importa el monitor real ni el cliente SIGAC: no hay red, sesión ni credenciales. Reutiliza solo la
reconciliación y la persistencia genéricas a través de `ServicioNovedadesLocal.observar_html`.

- Inicio único por instancia (un segundo `iniciar` falla); detención cooperativa (`parar` + `join` acotado).
- Recuperación tras reinicios: el punto de partida se deduce siempre de lo persistido, nunca de memoria.
- Crecimiento acotado: máximo de actuaciones por caso y tamaño máximo del archivo SQLite; al llegar, el monitor
  queda en reposo («tope») sin escribir más.
- Sin bloqueos en disco que puedan quedar huérfanos tras un corte: la exclusión es solo en memoria.
"""

import logging
import threading
import time

from tinotify.sintetico_remoto.datos import CASO_OBSERVADO, ObservacionRechazada, html_historial_sintetico
from tinotify.sintetico_remoto.errores import AlmacenNoDisponible

registro = logging.getLogger("tinotify.sintetico_remoto")

INICIAL = 3
MAX_FALLOS_SEGUIDOS = 5
ESPERA_CIERRE_S = 10.0
ESPERA_MAXIMA_ALMACEN_S = 300.0   # tope de la espera creciente cuando PostgreSQL no responde


class MonitorYaIniciado(RuntimeError):
    pass


class MonitorSintetico:
    def __init__(self, servicio, *, intervalo_s, max_actuaciones, max_bd_bytes, caso=CASO_OBSERVADO,
                 reloj=time.time, persistencia=None, exclusion=None):
        if not getattr(servicio, "sintetico", False):
            raise ValueError("El monitor sintetico exige un almacen de perfil sintetico")
        if not 3 <= max_actuaciones <= 200 or max_bd_bytes <= 0 or intervalo_s <= 0:
            raise ValueError("Limites del monitor sintetico no validos")
        self._servicio, self._intervalo, self._max, self._max_bytes = servicio, intervalo_s, max_actuaciones, max_bd_bytes
        self._caso, self._reloj = caso, reloj
        # Opcionales (almacen PostgreSQL): `persistencia` guarda/restaura contadores; `exclusion` impide dos monitores.
        self._persistencia, self._exclusion = persistencia, exclusion
        self._indisponible = 0
        self._lock = threading.Lock()          # protege estado observable e inicio único
        self._ciclo_lock = threading.Lock()    # serializa los ciclos (el hilo y llamadas manuales no se pisan)
        self._parar = threading.Event()
        self._hilo = None
        self._iniciado = False
        self._estado, self._motivo = "inactivo", None
        self._correctos = self._fallidos = self._seguidos = 0
        self._ultimo = None

    def snapshot(self):
        with self._lock:
            return {"estado": self._estado, "motivo": self._motivo, "intervalo_s": self._intervalo,
                    "ciclos_correctos": self._correctos, "ciclos_fallidos": self._fallidos,
                    "ultimo_ciclo": dict(self._ultimo) if self._ultimo else None,
                    "max_actuaciones": self._max, "sintetico": True}

    def _actuales(self):
        try:
            return self._servicio.detalle(self._caso)["total_actuaciones"]
        except KeyError:
            return 0

    def _tamano_bd(self):
        medir = getattr(self._servicio, "tamano_bytes", None)
        if medir is not None:
            return medir()
        try:
            return self._servicio.almacen.ruta.stat().st_size
        except OSError:
            return 0

    def ejecutar_ciclo(self):
        """Un ciclo. Devuelve 'ok', 'tope', 'limite_disco' o 'fallo'; nunca propaga errores internos."""
        with self._ciclo_lock:
            try:
                actuales = self._actuales()
                if actuales >= self._max:
                    return self._registrar("tope", actuales)
                if self._tamano_bd() >= self._max_bytes:
                    return self._registrar("limite_disco", actuales)
                resultado = self._servicio.observar_html(
                    self._caso, html_historial_sintetico(max(INICIAL, actuales + 1)))
                return self._registrar("ok", resultado["actuaciones"], resultado["novedades_nuevas"],
                                       resultado["generacion"])
            except ObservacionRechazada:
                return self._registrar("fallo", codigo="observacion_rechazada")
            except AlmacenNoDisponible:
                return self._registrar("fallo", codigo="almacen_no_disponible", transitorio=True)
            except Exception:  # noqa: BLE001 - el motivo se reduce a un código; nunca se propaga ni se registra el contenido
                return self._registrar("fallo", codigo="error_interno")

    def _registrar(self, resultado, actuaciones=0, novedades=0, generacion=None, codigo=None, transitorio=False):
        with self._lock:
            if resultado == "fallo":
                self._fallidos += 1
                # Una caida de PostgreSQL no es un fallo del monitor: se reintenta sin llegar al estado «error».
                self._indisponible = self._indisponible + 1 if transitorio else 0
                self._seguidos = self._seguidos if transitorio else self._seguidos + 1
                self._motivo = codigo
            else:
                self._seguidos = 0
                self._indisponible = 0
                self._motivo = resultado if resultado != "ok" else None
                if resultado == "ok":
                    self._correctos += 1
                    self._ultimo = {"hora": self._reloj(), "actuaciones": actuaciones,
                                    "novedades_nuevas": novedades, "generacion": generacion}
        registro.info("ciclo_sintetico resultado=%s", resultado)  # solo el código: sin contenido ni identificadores
        self._guardar_estado(resultado)
        return resultado

    def _guardar_estado(self, resultado):
        if self._persistencia is None or resultado == "fallo" and self._indisponible:
            return  # sin almacen persistente, o el propio almacen no responde
        with self._lock:
            estado = {"ciclos_correctos": self._correctos, "ciclos_fallidos": self._fallidos,
                      "motivo": self._motivo, "ultimo_ciclo": dict(self._ultimo) if self._ultimo else None}
        try:
            self._persistencia.guardar(estado)
        except Exception:  # noqa: BLE001 - el estado persistido es auxiliar; no detiene ni filtra detalles
            registro.warning("estado_monitor_no_guardado")

    def _restaurar_estado(self):
        if self._persistencia is None:
            return
        try:
            previo = self._persistencia.cargar()
        except Exception:  # noqa: BLE001
            registro.warning("estado_monitor_no_restaurado")
            return
        if previo:
            with self._lock:
                self._correctos = int(previo.get("ciclos_correctos", 0))
                self._fallidos = int(previo.get("ciclos_fallidos", 0))
                self._ultimo = previo.get("ultimo_ciclo")

    def iniciar(self):
        with self._lock:
            if self._iniciado:
                raise MonitorYaIniciado("El monitor sintetico solo se inicia una vez")
            self._iniciado = True
            self._estado = "activo"
            self._hilo = threading.Thread(target=self._bucle, name="monitor-sintetico", daemon=True)
            self._hilo.start()

    def _bucle(self):
        if self._exclusion is None:
            self._restaurar_estado()
        tenia = False
        try:
            while not self._parar.is_set():
                tengo = self._tengo_exclusion()
                if not tengo:
                    tenia = False
                    self._parar.wait(self._intervalo)   # otro proceso es el monitor: se espera y se reintenta
                    continue
                if not tenia:
                    tenia = True
                    if self._exclusion is not None:
                        self._restaurar_estado()   # al tomar el relevo se parte de lo que dejo el monitor anterior
                self.ejecutar_ciclo()
                with self._lock:
                    if self._seguidos >= MAX_FALLOS_SEGUIDOS:
                        self._estado = "error"
                        return
                    espera = self._intervalo
                    if self._indisponible:
                        espera = min(self._intervalo * 2 ** min(self._indisponible, 8), ESPERA_MAXIMA_ALMACEN_S)
                self._parar.wait(espera)
            # parada cooperativa: nunca se interrumpe un ciclo en curso (la transacción termina sola)
        finally:
            if self._exclusion is not None:
                try:
                    self._exclusion.liberar()
                except Exception:  # noqa: BLE001
                    pass

    def _tengo_exclusion(self):
        if self._exclusion is None:
            return True
        try:
            tengo = self._exclusion.mantiene() or self._exclusion.adquirir()
        except Exception:  # noqa: BLE001 - indisponibilidad del almacen: se reintenta
            tengo = False
            with self._lock:
                self._motivo = "almacen_no_disponible"
        with self._lock:
            if self._estado in ("activo", "en_espera"):
                self._estado = "activo" if tengo else "en_espera"
        return tengo

    def detener(self, espera_s=ESPERA_CIERRE_S):
        self._parar.set()
        hilo = self._hilo
        if hilo is not None:
            hilo.join(espera_s)
        with self._lock:
            if self._estado == "activo" and (hilo is None or not hilo.is_alive()):
                self._estado = "detenido"
            elif self._estado == "activo":
                self._estado = "deteniendo"
        return self.snapshot()
