"""ASGI del entorno sintético remoto:

    uvicorn tinotify.sintetico_remoto.app:crear_app --factory --workers 1 --no-proxy-headers

`--no-proxy-headers` es obligatorio: la política de proxy confiable es la de esta aplicación (config), no la de uvicorn.
Solo datos ficticios; no existe ninguna ruta `/real/*` ni se aceptan credenciales institucionales.
"""

from collections import deque
from contextlib import asynccontextmanager
import hashlib
import hmac
import ipaddress
import logging
from threading import Lock
import time
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from tinotify.sintetico_remoto.config import Config, ConfiguracionInsegura
from tinotify.sintetico_remoto.errores import AlmacenIncompatible, AlmacenNoDisponible
from tinotify.sintetico_remoto.monitor import MonitorSintetico

registro = logging.getLogger("tinotify.sintetico_remoto")

_CABECERAS_DE_PROXY = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
                       "x-real-ip", "via", "cf-connecting-ip", "true-client-ip")
RUTAS_SIN_AUTENTICACION = ("/health",)


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


def _respuesta(codigo, mensaje, **cabeceras):
    return JSONResponse({"detail": mensaje}, status_code=codigo, headers={"Cache-Control": "no-store", **cabeceras})


def _ip(texto):
    try:
        return ipaddress.ip_address(texto)
    except ValueError:
        return None


def evaluar_transporte(config: Config, par, esquema, cabeceras):
    """Devuelve None si el transporte es aceptable o (código, motivo) si se rechaza. Función pura y comprobable.

    Los encabezados de proxy solo se creen cuando el par TCP directo está en la lista de proxies confiables
    configurada; en cualquier otro caso se ignoran como valor y, en modo directo, se rechazan.
    """
    ip = _ip(par or "")
    if ip is not None and getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    if not config.remoto:  # pruebas locales: HTTP permitido, pero solo desde la propia máquina
        if ip is None or not ip.is_loopback:
            return 403, "Solo se aceptan conexiones locales en el modo de pruebas"
        return None
    if config.tls == "directo":
        if any(c in cabeceras for c in _CABECERAS_DE_PROXY):
            return 400, "Solicitud no valida"
        return None if esquema == "https" else (403, "Se requiere HTTPS")
    # tls == "proxy": el esquema efectivo solo puede venir de un proxy confiable
    if ip is None or not any(ip in red for red in config.proxies_confiables):
        return 403, "Se requiere HTTPS"
    proto = cabeceras.get("x-forwarded-proto", "")
    ultimo = proto.split(",")[-1].strip().lower()  # el proxy confiable añade el último valor
    return None if ultimo == "https" else (403, "Se requiere HTTPS")


def _construir_almacen(config: Config):
    """Devuelve (servicio, persistencia, exclusion). PostgreSQL solo se importa si se pide (no carga psycopg en SQLite)."""
    if config.almacenamiento == "postgres":
        from tinotify.sintetico_remoto.postgres import (
            AlmacenPg, EstadoMonitorPg, ExclusionMonitor, ServicioSinteticoPostgres,
        )
        almacen = AlmacenPg(config.pg)
        return ServicioSinteticoPostgres(almacen), EstadoMonitorPg(almacen), ExclusionMonitor(config.pg)
    from tinotify.demo.novedades import ServicioNovedadesLocal
    from tinotify.persistence.sqlite_local import AlmacenSqliteLocal
    return ServicioNovedadesLocal(AlmacenSqliteLocal(config.ruta_bd, perfil="sintetico")), None, None


def crear_app(config: Config | None = None, *, servicio=None, monitor=None, reloj=time.monotonic):
    if config is None:
        config = Config.desde_entorno()  # lanza ConfiguracionInsegura: el proceso no arranca con una config insegura
    persistencia = exclusion = None
    if servicio is None:
        servicio, persistencia, exclusion = _construir_almacen(config)
    if not servicio.sintetico:
        raise ConfiguracionInsegura("almacen_no_sintetico")
    if monitor is None and config.monitor_activo:
        monitor = MonitorSintetico(servicio, intervalo_s=config.intervalo_s, max_actuaciones=config.max_actuaciones,
                                   max_bd_bytes=config.max_bd_bytes, persistencia=persistencia, exclusion=exclusion)
    acceso = Acceso(config.token, reloj=reloj)

    @asynccontextmanager
    async def ciclo_de_vida(app):
        almacen = getattr(servicio, "almacen", None)
        if hasattr(almacen, "verificar_inicio"):
            try:
                await run_in_threadpool(almacen.verificar_inicio)
            except AlmacenNoDisponible:   # PostgreSQL caido al arrancar: la API vive y responde 503 hasta que vuelva
                registro.warning("almacen_no_disponible_al_iniciar")
            except AlmacenIncompatible:   # esquema o identidad incorrectos: no se arranca (falla cerrada)
                registro.error("almacen_incompatible")
                if hasattr(servicio, "cerrar"):
                    await run_in_threadpool(servicio.cerrar)
                raise
        try:
            if monitor is not None and config.monitor_activo:
                monitor.iniciar()
            yield
        finally:
            try:
                if monitor is not None:
                    await run_in_threadpool(monitor.detener)
            finally:
                if hasattr(servicio, "cerrar"):
                    await run_in_threadpool(servicio.cerrar)

    app = FastAPI(title="Tinotify sintetico remoto", lifespan=ciclo_de_vida,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def transporte(request: Request, siguiente):
        if request.url.path not in RUTAS_SIN_AUTENTICACION:
            par = request.client.host if request.client else None
            rechazo = evaluar_transporte(config, par, request.url.scheme, request.headers)
            if rechazo is not None:
                return _respuesta(*rechazo)
        respuesta = await siguiente(request)
        respuesta.headers["Cache-Control"] = "no-store"
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        if config.remoto:
            respuesta.headers["Strict-Transport-Security"] = "max-age=31536000"
        return respuesta

    @app.exception_handler(RequestValidationError)
    async def _validacion(request, error):
        return _respuesta(422, "Entrada no valida")

    @app.exception_handler(HTTPException)
    async def _http(request, error):
        return _respuesta(error.status_code, error.detail if isinstance(error.detail, str) else "Error",
                          **(error.headers or {}))

    @app.exception_handler(AlmacenNoDisponible)
    async def _no_disponible(request, error):
        registro.warning("almacen_no_disponible")
        return _respuesta(503, "Almacen no disponible", **{"Retry-After": "30"})

    @app.exception_handler(AlmacenIncompatible)
    async def _incompatible(request, error):
        registro.error("almacen_incompatible")
        return _respuesta(503, "Almacen no disponible", **{"Retry-After": "30"})

    @app.exception_handler(Exception)
    async def _interno(request, error):
        registro.error("error_interno tipo=%s", type(error).__name__)  # nunca el mensaje, la ruta ni el contenido
        return _respuesta(500, "Error interno")

    bearer = HTTPBearer(auto_error=False)

    def autorizar(credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        resultado = acceso.comprobar(credencial.credentials if credencial else None)
        if resultado is True:
            return
        if resultado is None:
            raise HTTPException(429, "Demasiados intentos")
        raise HTTPException(401, "Acceso requerido", headers={"WWW-Authenticate": "Bearer"})

    protegidas = [Depends(autorizar)]

    @app.get("/health")
    async def salud():
        return {"estado": "ok"}  # sin datos, rutas, versiones ni configuración

    @app.get("/sintetico/casos", dependencies=protegidas)
    async def casos():
        return await run_in_threadpool(servicio.listar_casos)

    @app.get("/sintetico/casos/{caso}", dependencies=protegidas)
    async def detalle(caso: UUID):
        try:
            return await run_in_threadpool(servicio.detalle, str(caso))
        except KeyError:
            raise HTTPException(404, "No encontrado") from None

    @app.get("/sintetico/novedades", dependencies=protegidas)
    async def novedades():
        return await run_in_threadpool(servicio.novedades)

    @app.get("/sintetico/monitor", dependencies=protegidas)
    async def estado_monitor():
        return monitor.snapshot() if monitor is not None else {"estado": "desactivado", "sintetico": True}

    return app
