"""Consulta LOCAL y protegida de los datos reales ya persistidos. Solo lectura.

La API nunca inicia consultas a SIGAC ni acepta credenciales de SIGAC: los datos llegan al archivo SQLite
(perfil «real») únicamente por la herramienta manual `backend/scripts/sigac_local.py`. Estas rutas exigen un
código de acceso local (`Authorization: Bearer ...`) y no existen si no se configuran explícitamente.
`adb reverse` solo es transporte local: no cuenta como autenticación.
"""

from collections import deque
import hashlib
import hmac
from threading import Lock
import time
from typing import Annotated
from uuid import UUID

from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.middleware.errors import ServerErrorMiddleware


class NoStoreReal:
    """Cabecera sobre el inicio de la respuesta final, solo en /real.

    El manejador interno conserva el 500 por defecto de esta aplicación y el
    relanzado de excepciones. Así ese 500 también atraviesa la frontera; un
    middleware situado dentro del ServerErrorMiddleware exterior no lo vería.
    No se capturan ni ocultan errores de transporte y no se almacena el cuerpo.
    """

    def __init__(self, app, *, debug=False):
        self.app = app
        self.errores_reales = ServerErrorMiddleware(app, debug=debug)

    async def __call__(self, scope, receive, send):
        ruta = scope.get('path', '')
        if scope['type'] != 'http' or not (ruta == '/real' or ruta.startswith('/real/')):
            await self.app(scope, receive, send)
            return

        async def enviar(message):
            if message['type'] == 'http.response.start':
                MutableHeaders(scope=message)['Cache-Control'] = 'no-store'
            await send(message)

        await self.errores_reales(scope, receive, enviar)


class DemasiadosIntentos(Exception):
    pass


class AccesoLocal:
    """Código de acceso local: comparación en tiempo constante y límite de intentos fallidos."""

    def __init__(self, codigo, *, reloj=time.monotonic, max_fallos=5, ventana=60.0):
        if not isinstance(codigo, str) or len(codigo) < 32 or codigo != codigo.strip():
            raise ValueError("El codigo de acceso local requiere al menos 32 caracteres sin espacios en los bordes")
        self._huella = hashlib.sha256(codigo.encode("utf-8")).digest()
        self._reloj, self._max, self._ventana = reloj, max_fallos, ventana
        self._fallos, self._lock = deque(), Lock()

    def comprobar(self, credencial):
        with self._lock:
            ahora = self._reloj()
            while self._fallos and ahora - self._fallos[0] >= self._ventana:
                self._fallos.popleft()
            if len(self._fallos) >= self._max:  # ni siquiera el código correcto durante el bloqueo
                raise DemasiadosIntentos
            valido = isinstance(credencial, str) and hmac.compare_digest(
                hashlib.sha256(credencial.encode("utf-8")).digest(), self._huella)
            if not valido:
                self._fallos.append(ahora)
                raise PermissionError("Acceso local requerido")


class InicioSesion(BaseModel):
    """Cuerpo de la autorización SIGAC. Los secretos son `SecretStr`: no se muestran en repr ni en errores."""

    model_config = ConfigDict(extra="forbid")
    usuario: SecretStr = Field(min_length=1, max_length=128)
    clave: SecretStr = Field(min_length=1, max_length=256)
    caso_login: SecretStr | None = Field(default=None, max_length=128)
    tipo: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f\x7f]+$")
    total_casos: int = Field(ge=1, le=1000)
    indice_caso: int = Field(ge=1, le=1000)
    intervalo_minutos: int = Field(ge=10, le=240)
    etiqueta: str | None = Field(default=None, max_length=60)
    confirmacion: Literal["SIGAC-MONITOR-LOCAL"]


_BUCLE_LOCAL = {"127.0.0.1", "::1"}
_NOMBRES_LOCALES = {"127.0.0.1", "::1", "localhost"}
_CABECERAS_DE_PROXY = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
                       "x-real-ip", "via", "cf-connecting-ip", "true-client-ip")


def exigir_transporte_local(request: Request):
    """Las credenciales solo se aceptan por el enlace local (USB con `adb reverse`), nunca por red ni túnel.

    Es una defensa de transporte, NO autenticación: el código de acceso local sigue siendo obligatorio. La
    detección de túneles locales es heurística (cabeceras de proxy y nombre de host).
    """
    cliente = request.client.host if request.client else None
    try:
        nombre = urlsplit("//" + request.headers.get("host", "")).hostname
    except ValueError:
        nombre = None
    if (cliente not in _BUCLE_LOCAL or nombre not in _NOMBRES_LOCALES
            or any(c in request.headers for c in _CABECERAS_DE_PROXY)):
        raise HTTPException(403, "Las credenciales solo se aceptan por la conexion local USB")


def registrar_rutas_reales(app: FastAPI, servicio, acceso: AccesoLocal, gestor=None, historial=None):
    if getattr(servicio, "sintetico", True):
        raise ValueError("Las rutas reales exigen un almacen de perfil real")
    app.add_middleware(NoStoreReal, debug=app.debug)
    bearer = HTTPBearer(auto_error=False)

    def autorizar(credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], respuesta: Response):
        respuesta.headers["Cache-Control"] = "no-store"
        try:
            acceso.comprobar(credencial.credentials if credencial else None)
        except PermissionError:
            raise HTTPException(401, "Acceso local requerido", headers={"WWW-Authenticate": "Bearer"}) from None

    protegidas = [Depends(autorizar)]

    @app.get("/real/cases", dependencies=protegidas)
    async def casos_reales():
        return servicio.listar_casos()

    @app.get("/real/cases/{caso}", dependencies=protegidas)
    async def detalle_real(caso: UUID):
        return servicio.detalle(str(caso))

    @app.get("/real/novedades", dependencies=protegidas)
    async def novedades_reales():
        raise HTTPException(410, 'Avisos reales deshabilitados; consultar /real/observaciones')

    @app.get("/real/observaciones", dependencies=protegidas)
    async def observaciones_reales():
        return servicio.observaciones()

    if historial is not None:
        # Historial completo SOLO en memoria (HistorialTemporal): sin SIGAC, sin credenciales y sin escritura. Además
        # del código de acceso exige transporte loopback, como la sesión SIGAC (defensa de transporte, no autenticación).
        locales = [Depends(autorizar), Depends(exigir_transporte_local)]

        @app.get("/real/historial/estado", dependencies=locales)
        async def estado_historial():
            return historial.estado()

        @app.get("/real/cases/{caso}/historial", dependencies=locales)
        async def historial_real(caso: UUID):
            datos = historial.listado(str(caso))
            if datos is None:
                raise HTTPException(404, "Sin historial temporal activo para este expediente")
            return datos

        @app.get("/real/cases/{caso}/historial/{indice}", dependencies=locales)
        async def actuacion_real(caso: UUID, indice: int, sesion: UUID):
            datos = historial.detalle(str(caso), str(sesion), indice)
            if datos is None:
                raise HTTPException(404, "Sin historial temporal activo para este expediente")
            return datos

        @app.delete("/real/historial", dependencies=locales)
        async def cerrar_historial():
            historial.invalidar()
            return {"activa": False}

    if gestor is None:
        return
    # Sesión SIGAC temporal: solo con activación explícita, solo en esta API local y nunca en producción.
    from tinotify.services.sesion_sigac_local import DemasiadosIntentosAcceso, SesionEnCurso

    @app.post("/real/sesion", dependencies=[Depends(autorizar), Depends(exigir_transporte_local)])
    async def iniciar_sesion(datos: InicioSesion, respuesta: Response):
        if datos.indice_caso > datos.total_casos:
            raise HTTPException(422, "Entrada no valida")
        try:
            estado = await run_in_threadpool(
                gestor.iniciar, usuario=datos.usuario.get_secret_value(), clave=datos.clave.get_secret_value(),
                caso_login=datos.caso_login.get_secret_value() if datos.caso_login else None, tipo=datos.tipo,
                total_casos=datos.total_casos, indice_caso=datos.indice_caso,
                intervalo_s=datos.intervalo_minutos * 60, etiqueta=datos.etiqueta)
        except SesionEnCurso:
            raise HTTPException(409, "Ya hay una sesion o un monitor en curso") from None
        except DemasiadosIntentosAcceso:
            raise HTTPException(429, "Demasiados intentos de autenticacion; espera") from None
        except ValueError:
            raise HTTPException(422, "Entrada no valida") from None
        respuesta.status_code = 202 if estado["estado"] == "autenticacion_pendiente" else 200
        return estado

    @app.get("/real/monitor", dependencies=protegidas)
    async def estado_monitor():
        return gestor.snapshot()

    @app.delete("/real/sesion", dependencies=protegidas)
    async def detener_sesion():
        return await run_in_threadpool(gestor.detener)
