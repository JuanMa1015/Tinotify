"""Monitor local y controlado de un expediente SIGAC durante UNA sesión autorizada.

Reutiliza el cliente SIGAC (sesión autenticada en memoria) y `ServicioNovedadesLocal` (seguimiento, reconciliación
y avisos existentes); no contiene un segundo motor. Nunca recibe credenciales: el llamador entrega una función
`autenticar()` que se invoca una sola vez. Si la sesión vence o SIGAC restringe el acceso, el monitor se detiene
y exige una nueva autorización interactiva; no reintenta el acceso, no mantiene la sesión artificialmente ni
intenta eludir controles. La API nunca importa este módulo ni puede iniciarlo.

La combinación de cliente SIGAC y persistencia real queda bloqueada hasta
validar el contrato institucional de identidad del expediente. El bucle sigue
probándose con clientes y actuaciones sintéticos.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from tinotify.demo.novedades import ObservacionRechazada
from tinotify.integrations.sigac.sigac_client import SigacClient, SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial, EtapaSigac
from tinotify.services.consulta_real_local import (
    IdentidadExpedienteNoVerificada, caso_local, etiqueta_valida,
)

INTERVALO_MINIMO_S = 600          # 10 minutos: nunca más agresivo
INTERVALO_PREDETERMINADO_S = 1800  # 30 minutos
INTERVALO_MAXIMO_S = 14400        # 4 horas
MAX_FALLOS_CONSECUTIVOS = 3
ESPERAS_TRANSITORIAS_S = (60, 120, 240)  # espera limitada ante errores de red; nunca reintentos inmediatos

# Fallos de comunicación: único caso que se reintenta (con espera). Todo lo demás de acceso detiene el monitor.
_TRANSITORIOS = {CodigoHistorial.TRANSPORTE}
_ACCESO = {
    CodigoHistorial.SESION_NO_CONFIRMADA, CodigoHistorial.PAGINA_NO_PROTEGIDA, CodigoHistorial.HTTP_INVALIDO,
    CodigoHistorial.NO_HTML, CodigoHistorial.NO_CLASIFICADO,
}


_EN_CURSO = threading.Lock()


class Motivo(str, Enum):
    INTERRUMPIDO = "interrumpido_por_el_usuario"
    MAX_CICLOS = "maximo_de_ciclos"
    SESION_EXPIRADA = "sesion_expirada_requiere_nueva_autorizacion"
    ACCESO_RESTRINGIDO = "acceso_restringido_o_respuesta_inesperada"
    AUTENTICACION_FALLIDA = "autenticacion_fallida"
    EXPEDIENTE_NO_LISTADO = "expediente_ya_no_figura_en_el_listado"
    LISTADO_NO_CONFIRMADO = "listado_no_confirmado"
    FALLOS_REPETIDOS = "fallos_consecutivos_repetidos"
    ERROR_INESPERADO = "error_inesperado"


# 0 = detención normal; 4 = hace falta una nueva autorización; 5 = fallos repetidos; 1 = otros.
CODIGOS_SALIDA = {
    Motivo.INTERRUMPIDO: 0, Motivo.MAX_CICLOS: 0, Motivo.SESION_EXPIRADA: 4, Motivo.ACCESO_RESTRINGIDO: 4,
    Motivo.AUTENTICACION_FALLIDA: 4, Motivo.EXPEDIENTE_NO_LISTADO: 1, Motivo.LISTADO_NO_CONFIRMADO: 1,
    Motivo.FALLOS_REPETIDOS: 5, Motivo.ERROR_INESPERADO: 1,
}


@dataclass(frozen=True)
class ResultadoMonitor:
    motivo: Motivo
    ciclos_correctos: int
    ciclos_fallidos: int

    @property
    def codigo_salida(self):
        return CODIGOS_SALIDA[self.motivo]


class MonitorEnEjecucion(RuntimeError):
    pass


class BloqueoMonitor:
    """Un solo monitor por almacén. No borra bloqueos ajenos: si quedó uno huérfano lo decide la persona."""

    def __init__(self, ruta_almacen):
        self.ruta = Path(str(ruta_almacen) + ".monitor.lock")
        self._fd = None

    def __enter__(self):
        try:
            self._fd = os.open(self.ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise MonitorEnEjecucion(
                "Ya hay un monitor activo para este almacén, o quedó un bloqueo de una ejecución interrumpida. "
                f"Si estás seguro de que no hay otro monitor, elimina manualmente {self.ruta.name}.") from None
        os.write(self._fd, str(os.getpid()).encode())
        return self

    def __exit__(self, *args):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
            self.ruta.unlink(missing_ok=True)
        return False


def clasificar(error):
    """'transitorio' (se reintenta con espera), 'acceso' (se detiene) o 'extraccion' (no se modifica nada)."""
    if isinstance(error, SigacSessionExpired):
        return "acceso"
    codigo = error.codigo
    if codigo in _TRANSITORIOS:
        return "transitorio"
    # Antes, esos rechazos se envolvían como NO_CLASIFICADO (acceso). Conservar
    # su resultado al preservar ahora el código original y su etapa diagnóstica.
    if error.etapa in (EtapaSigac.LISTADO_INICIAL, EtapaSigac.LISTADO_REPETIDO):
        return "acceso"
    return "acceso" if codigo in _ACCESO else "extraccion"


def monitorear(cliente, autenticar, *, total_casos, indice_caso=None, caso_numero=None, servicio, etiqueta=None,
               total_actuaciones=None, contenedor_id=None, intervalo_s=INTERVALO_PREDETERMINADO_S, max_ciclos=None,
               reloj=time.monotonic, espera=time.sleep, emitir=lambda evento: None, ahora=datetime.now,
               debe_detenerse=None):
    """Consulta una vez al inicio y luego cada `intervalo_s`, hasta detenerse. Sin hilos ni consultas simultáneas.

    `autenticar()` se llama una sola vez y devuelve el listado; el monitor no ve las credenciales. `reloj` y
    `espera` se inyectan para las pruebas. Solo se emiten estados, cantidades, códigos y horas.
    `debe_detenerse()` permite una detención cooperativa desde otro hilo: se comprueba entre pasos y una consulta en
    curso termina sola (no se descarta a medias); su resultado no se persiste si ya se pidió detener.
    """
    if getattr(getattr(servicio, 'almacen', None), 'perfil', None) == 'real':
        # El monitoreo automático real NO está habilitado en esta etapa, ni siquiera con un contrato de
        # expediente: solo existe la consulta manual (consultar_caso_acreditado).
        raise IdentidadExpedienteNoVerificada('Monitor SIGAC real deshabilitado: solo se permite la consulta manual')
    if type(intervalo_s) is not int or not INTERVALO_MINIMO_S <= intervalo_s <= INTERVALO_MAXIMO_S:
        raise ValueError("Intervalo fuera del rango permitido")
    if max_ciclos is not None and (type(max_ciclos) is not int or max_ciclos < 1):
        raise ValueError("El máximo de ciclos debe ser un entero positivo")
    if (indice_caso is None) == (caso_numero is None):
        raise ValueError("Indique exactamente una selección: número de caso o posición")
    if type(total_casos) is not int or total_casos < 1:
        raise ValueError("Total o posición del listado no válidos")
    if indice_caso is not None and (type(indice_caso) is not int or not 1 <= indice_caso <= total_casos):
        raise ValueError("Total o posición del listado no válidos")
    if caso_numero is not None and (type(caso_numero) is not int or caso_numero < 1):
        raise ValueError("Número de caso no válido")
    titulo = etiqueta_valida(etiqueta)
    if not _EN_CURSO.acquire(blocking=False):  # un solo monitor por proceso; nunca consultas simultáneas
        raise MonitorEnEjecucion("Ya hay un monitor en curso en este proceso")

    def evento(nombre, **datos):
        emitir({"evento": nombre, "hora": ahora().isoformat(timespec="seconds"), **datos})

    def parar():
        return debe_detenerse is not None and bool(debe_detenerse())

    def detener(motivo, correctos, fallidos):
        evento("detenido", motivo=motivo.value, ciclos_correctos=correctos, ciclos_fallidos=fallidos)
        return ResultadoMonitor(motivo, correctos, fallidos)

    correctos = fallidos = consecutivos = intentos = 0
    try:
        evento("inicio", intervalo_s=intervalo_s)
        try:
            casos = autenticar()
            if caso_numero is not None:
                # Selección por número: debe aparecer exactamente una vez en el listado validado.
                if [c.numero for c in casos].count(caso_numero) != 1:
                    return detener(Motivo.EXPEDIENTE_NO_LISTADO, 0, 0)
                numero = caso_numero
            else:
                numero = casos[indice_caso - 1].numero
            caso_id = caso_local(numero)
        except KeyboardInterrupt:
            return detener(Motivo.INTERRUMPIDO, 0, 0)
        except (SigacClientError, IndexError, TypeError, ValueError):
            return detener(Motivo.AUTENTICACION_FALLIDA, 0, 0)
        except Exception:
            return detener(Motivo.ERROR_INESPERADO, 0, 0)
        if parar():
            return detener(Motivo.INTERRUMPIDO, 0, 0)
        proximo = reloj()
        primera = True
        while True:
            try:
                espera_s = max(0.0, proximo - reloj())
                if espera_s:
                    evento("espera", segundos=int(espera_s))
                    espera(espera_s)
            except KeyboardInterrupt:
                return detener(Motivo.INTERRUMPIDO, correctos, fallidos)
            if parar():
                return detener(Motivo.INTERRUMPIDO, correctos, fallidos)
            inicio = reloj()
            intentos += 1
            tipo, fase, codigo = None, "listado", None
            try:
                operacion = ({'clave': uuid4(), 'generacion_esperada': servicio.generacion(caso_id)}
                             if hasattr(servicio, 'generacion') else {})
                if not primera:  # mismo cliente y sesión; el listado confirma que sigue autenticado
                    casos = cliente.listar_casos(total_esperado=total_casos)
                    if numero not in {c.numero for c in casos}:
                        return detener(Motivo.EXPEDIENTE_NO_LISTADO, correctos, fallidos)
                    if parar():
                        return detener(Motivo.INTERRUMPIDO, correctos, fallidos)
                fase = "historial"
                actuaciones = cliente.consultar_historial(numero, total_esperado=total_actuaciones,
                                                          contenedor_id=contenedor_id)
                if parar():  # se pidió detener durante la consulta: no se persiste a medias
                    return detener(Motivo.INTERRUMPIDO, correctos, fallidos)
                resultado = servicio.observar(caso_id, actuaciones, titulo=titulo, **operacion)
            except KeyboardInterrupt:
                return detener(Motivo.INTERRUMPIDO, correctos, fallidos)
            except SigacSessionExpired:
                return detener(Motivo.SESION_EXPIRADA, correctos, fallidos)
            except ObservacionRechazada:
                tipo, codigo = "extraccion", "observacion_rechazada"
            except SigacClientError as error:
                tipo = clasificar(error)
                if tipo == "acceso":
                    return detener(Motivo.LISTADO_NO_CONFIRMADO if fase == "listado" and not primera
                                   else Motivo.ACCESO_RESTRINGIDO, correctos, fallidos)
                codigo = error.codigo.value
            except Exception:
                return detener(Motivo.ERROR_INESPERADO, correctos, fallidos)
            else:
                correctos, consecutivos, primera = correctos + 1, 0, False
                evento("ciclo", ciclo=intentos, duracion_s=round(reloj() - inicio, 1), **resultado)
                proximo = inicio + intervalo_s
                if max_ciclos is not None and intentos >= max_ciclos:
                    return detener(Motivo.MAX_CICLOS, correctos, fallidos)
                continue
            # Fallo transitorio o extracción rechazada: el historial no se modificó.
            fallidos += 1
            consecutivos += 1
            if consecutivos >= MAX_FALLOS_CONSECUTIVOS:
                evento("fallo", tipo=tipo, codigo=codigo, consecutivos=consecutivos)
                return detener(Motivo.FALLOS_REPETIDOS, correctos, fallidos)
            if tipo == "transitorio":
                pausa = min(ESPERAS_TRANSITORIAS_S[consecutivos - 1], intervalo_s)
                proximo = reloj() + pausa
            else:
                proximo = inicio + intervalo_s  # una extracción dudosa no se reintenta antes del intervalo normal
            evento("fallo", tipo=tipo, codigo=codigo, consecutivos=consecutivos,
                   proximo_en_s=int(max(0, proximo - reloj())))
            if max_ciclos is not None and intentos >= max_ciclos:
                return detener(Motivo.MAX_CICLOS, correctos, fallidos)
    finally:
        _EN_CURSO.release()
