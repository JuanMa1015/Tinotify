"""Utilidades de seguridad HTTP propias del backend real remoto.

Este paquete NO importa nada de `tinotify.sintetico_remoto`: en producción solo se ejecuta el backend real y el código
sintético permanece en el repositorio, sin cargarse. Las piezas de abajo reproducen deliberadamente el comportamiento ya
probado del entorno sintético (token en tiempo constante, validación de proxy/HTTPS y rechazo de configuraciones inseguras).
"""

from collections import deque
import hashlib
import hmac
import ipaddress
import math
import re
from threading import Lock
import time

from fastapi.responses import JSONResponse

MODO_LOCAL = "pruebas-locales"
MODO_REMOTO = "remoto"
TLS_DIRECTO = "directo"
TLS_PROXY = "proxy"
PROXIES_PRIVADAS = "privadas"  # solo pares TCP con IP privada (plataforma que aísla el contenedor)
REDES_PRIVADAS = tuple(ipaddress.ip_network(r) for r in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
_TOKEN_DEBIL = ("changeme", "password", "secret", "example", "ejemplo", "tinotify-desarrollo-local", "contrasena")
_CABECERAS_DE_PROXY = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
                       "x-real-ip", "via", "cf-connecting-ip", "true-client-ip")


class ConfiguracionInsegura(ValueError):
    """Configuración rechazada. `codigo` es estable y no contiene valores sensibles."""

    def __init__(self, codigo):
        super().__init__(f"Configuracion rechazada: {codigo}")
        self.codigo = codigo


def _rechazar(codigo):
    raise ConfiguracionInsegura(codigo)


def validar_token(token):
    if not isinstance(token, str) or not token:
        _rechazar("token_ausente")
    if len(token) < 32 or len(token) > 256 or re.search(r"\s", token) or not token.isascii() or not token.isprintable():
        _rechazar("token_inseguro")
    if len(set(token)) < 12 or any(p in token.lower() for p in _TOKEN_DEBIL):
        _rechazar("token_inseguro")
    return token


def _proxies(texto):
    if not texto or not texto.strip():
        _rechazar("proxies_confiables_ausentes")
    if texto.strip().lower() == PROXIES_PRIVADAS:
        return REDES_PRIVADAS
    redes = []
    for trozo in texto.split(","):
        trozo = trozo.strip()
        if not trozo or "*" in trozo:
            _rechazar("proxies_confiables_invalidos")
        try:
            red = ipaddress.ip_network(trozo, strict=True)
        except ValueError:
            _rechazar("proxies_confiables_invalidos")
        minimo = 24 if red.version == 4 else 64
        if red.network_address.is_unspecified or red.prefixlen < minimo:
            _rechazar("proxies_confiables_demasiado_amplios")
        redes.append(red)
    return tuple(redes)


def _numero(texto, minimo, maximo, codigo, *, tipo=float):
    try:
        valor = tipo(texto)
    except (TypeError, ValueError):
        _rechazar(codigo)
    if not minimo <= valor <= maximo or not math.isfinite(valor):
        _rechazar(codigo)
    return valor


class Acceso:
    """Token único: comparación en tiempo constante. Los intentos fallidos se limitan, pero el token correcto
    nunca queda bloqueado (un tercero no puede dejar fuera al usuario legítimo fallando a propósito)."""

    def __init__(self, token, *, reloj=time.monotonic, max_fallos=5, ventana=60.0):
        self._huella = hashlib.sha256(token.encode("utf-8")).digest()
        self._reloj, self._max, self._ventana = reloj, max_fallos, ventana
        self._fallos, self._lock = deque(), Lock()

    def comprobar(self, credencial):
        """True si es válido; False si no; None si hay demasiados fallos recientes y la credencial no es válida."""
        valido = isinstance(credencial, str) and hmac.compare_digest(
            hashlib.sha256(credencial.encode("utf-8")).digest(), self._huella)
        with self._lock:
            ahora = self._reloj()
            while self._fallos and ahora - self._fallos[0] >= self._ventana:
                self._fallos.popleft()
            if valido:
                return True
            bloqueado = len(self._fallos) >= self._max
            if not bloqueado:
                self._fallos.append(ahora)
            return None if bloqueado else False


def respuesta(codigo, mensaje, **cabeceras):
    return JSONResponse({"detail": mensaje}, status_code=codigo, headers={"Cache-Control": "no-store", **cabeceras})


def _ip(texto):
    try:
        return ipaddress.ip_address(texto)
    except ValueError:
        return None


def evaluar_transporte(config, par, esquema, cabeceras):
    """None si el transporte es aceptable o (código, motivo) si se rechaza. Función pura y comprobable.

    Los encabezados de proxy solo se creen cuando el par TCP directo está en la lista de proxies confiables configurada;
    en cualquier otro caso se ignoran como valor y, en modo directo, se rechazan. `X-Forwarded-For` nunca se usa.
    """
    ip = _ip(par or "")
    if ip is not None and getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    if not config.remoto:  # pruebas locales: HTTP permitido, pero solo desde la propia máquina
        if ip is None or not ip.is_loopback:
            return 403, "Solo se aceptan conexiones locales en el modo de pruebas"
        return None
    if config.tls == TLS_DIRECTO:
        if any(c in cabeceras for c in _CABECERAS_DE_PROXY):
            return 400, "Solicitud no valida"
        return None if esquema == "https" else (403, "Se requiere HTTPS")
    # tls == "proxy": el esquema efectivo solo puede venir de un proxy confiable
    if ip is None or not any(ip in red for red in config.proxies_confiables):
        return 403, "Se requiere HTTPS"
    proto = cabeceras.get("x-forwarded-proto", "")
    ultimo = proto.split(",")[-1].strip().lower()  # el proxy confiable añade el último valor
    return None if ultimo == "https" else (403, "Se requiere HTTPS")
